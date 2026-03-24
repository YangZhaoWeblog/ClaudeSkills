# 数据源连接状态实时推送功能设计方案

**文档类型：** 设计方案
**读者：** 负责实现本功能的后端/前端工程师、技术 Leader
**决策点：** 确定推送技术选型（gorilla/websocket / coder/websocket / SSE），并明确在现有 gRPC 服务中的落地架构

---

**背景：** 前端用户需要实时感知其注册的数据源连接状态变化（连通/断开），当前只能依赖手动刷新或轮询。

**结论：选用 SSE（Server-Sent Events）**。本场景是纯服务端→客户端的单向推送，SSE 用标准库即可实现，无需引入额外依赖，浏览器原生支持断线重连，实现复杂度最低，完全满足需求。两个 WebSocket 方案在此场景是过度设计。

---

## 一、背景与问题根因

> 本节回答：为什么需要这个功能，现有方案为何不够？

数据源注册后，其连接状态（数据库是否可达、连接参数是否有效）会因网络变化、目标数据库重启等原因发生改变。当前前端获取连接状态的途径只有：

1. **手动触发**：调用"测试连接"接口（主动拉取，非实时）
2. **页面刷新**：重新 ListDataSource（无法感知状态变化时机）

当数据源连接断开时，前端无法及时提示用户，可能导致用户在不可用的数据源上继续操作（创建资源、发布产品），产生无效工作。

**触发时机来源**（现有架构中已有两处可感知连接状态变化）：

- `internal/cron/`：定时轮询任务，可定期探测数据源连通性
- `internal/event/service/`：来自 connector-manager 的服务事件，connector 下线/上线时会发送事件

---

## 二、技术选型对比

> 本节回答：gorilla/websocket、coder/websocket、SSE 三者哪个最适合本场景？

### 场景特征

本功能的通信模式是：**服务端单向推送状态变更事件到前端**，前端无需向服务端发送任何消息（除初始订阅请求外）。

### 对比表

| 维度 | gorilla/websocket | coder/websocket | SSE（标准库） |
|------|-----------------|-----------------|-------------|
| 通信方向 | 双向 | 双向 | 单向（服务端→客户端）✅ 匹配本场景 |
| 额外依赖 | 需引入 `github.com/gorilla/websocket` | 需引入 `github.com/coder/websocket` | 无，`net/http` 标准库即可 |
| 维护状态 | 活跃（v1.5.3，2024-06）| 活跃（coder 2024 年接手维护）| HTTP 标准协议，无维护风险 |
| `context.Context` 支持 | ❌ 原生不支持，需手动封装 | ✅ 原生支持 | ✅ 原生支持（request context） |
| 断线自动重连 | ❌ 需客户端自行实现 | ❌ 需客户端自行实现 | ✅ 浏览器原生支持 `EventSource` |
| HTTP/2 支持 | ❌ | 规划中 | ✅ |
| 连接升级协议 | WebSocket 握手（需 Upgrade header）| WebSocket 握手 | 普通 HTTP 长连接，无需升级 |
| 实现复杂度 | 高（需处理 ping/pong、消息类型、并发写锁）| 中 | 低（写 `text/event-stream` 响应即可）|
| 与现有 gRPC 服务集成 | 需额外 HTTP 服务器，两种方案相同 | 同左 | 同左 |

### 推荐方案：SSE

**理由：**
1. **功能匹配**：单向推送场景中，WebSocket 的双向能力完全没有用武之地，引入即是技术负债。
2. **零依赖**：go-zero 框架本身已包含 `net/http`，无需新增 `go.mod` 依赖。
3. **客户端简单**：浏览器 `EventSource` API 原生支持断线重连（指数退避），无需前端额外处理。
4. **运维友好**：SSE 基于普通 HTTP，经过 Nginx 反向代理时无需特殊配置（WebSocket 需要 `proxy_upgrade` 配置）。

**排除 gorilla/websocket 的额外理由**：`context.Context` 支持缺失意味着无法干净地与 go-zero 的请求生命周期集成，需要手动封装，增加维护成本。

---

## 三、落地架构

> 本节回答：如何在现有服务中加入 SSE 推送，各组件职责是什么？

### 整体数据流

```
[连通性检测来源]                  [SSE 层]                    [前端]
  cron 定期探测           →   NotifyHub.Publish()   →   EventSource 接收事件
  connector 服务事件      →   (按 datasource_id 路由)
  手动测试连接结果        →
```

### 组件职责

**新增组件：`internal/push/hub.go`**

维护所有活跃的 SSE 连接，按 `datasource_id` 分组路由推送。核心数据结构：

```go
// Hub 管理所有活跃 SSE 订阅
type Hub struct {
    mu          sync.RWMutex
    // key: datasource_id, value: 该数据源的订阅者集合
    subscribers map[uint64]map[string]*subscriber
}

// subscriber 单个 SSE 连接
type subscriber struct {
    id     string          // 连接唯一 ID（UUID）
    ch     chan Event       // 事件投递通道
    ctx    context.Context
}

// Event 推送的事件结构
type Event struct {
    DatasourceID uint64 `json:"datasource_id"`
    Status       string `json:"status"`  // "connected" | "disconnected"
    CheckedAt    int64  `json:"checked_at"`
}
```

对外暴露两个方法：
- `Subscribe(ctx, datasourceID) (<-chan Event, unsubscribeFunc)` — HTTP handler 调用，建立订阅
- `Publish(datasourceID, event)` — 检测层调用，推送状态变更

**新增组件：`internal/push/handler.go`**

SSE HTTP handler，供 go-zero 注册为 HTTP 路由：

```go
// GET /api/v1/datasource/{id}/status/stream
// 认证：Bearer Token（复用现有中间件）
func (h *Handler) StreamDatasourceStatus(w http.ResponseWriter, r *http.Request) {
    // 1. 解析 datasource_id，校验权限（调用 helper.CheckAuth）
    // 2. 设置 SSE 响应头
    w.Header().Set("Content-Type", "text/event-stream")
    w.Header().Set("Cache-Control", "no-cache")
    w.Header().Set("X-Accel-Buffering", "no")  // 禁止 Nginx 缓冲
    // 3. 订阅 Hub，循环写事件直到 context 取消
}
```

**修改现有组件**

| 组件 | 修改内容 |
|------|---------|
| `internal/cron/` 定时任务 | 探测连通性后，调用 `hub.Publish()` |
| `internal/event/service/` 事件消费 | connector 状态事件触发 `hub.Publish()` |
| `internal/svc/service_context.go` | 注入 `*push.Hub` 实例 |
| `main.go` / 启动入口 | 启动额外 HTTP 服务器（或复用 go-zero rest server）|

### HTTP 服务器集成方式

go-zero 支持同一进程中同时运行 gRPC 和 REST 服务。推荐在现有启动逻辑中**新增一个 `rest.Server`**，专门承载 SSE endpoint，避免与 gRPC 端口混用：

```
gRPC: :8080  （现有）
HTTP: :8081  （新增，仅 SSE + 少量 REST）
```

---

## 四、接口定义

> 本节回答：前端调用什么接口，事件格式是什么？

### 接口

```
GET /api/v1/datasource/{datasource_id}/status/stream
Authorization: Bearer <token>
Accept: text/event-stream
```

### 事件格式（SSE 标准格式）

```
event: status_change
data: {"datasource_id": 123, "status": "disconnected", "checked_at": 1711234567}

event: status_change
data: {"datasource_id": 123, "status": "connected", "checked_at": 1711234590}
```

- `status` 取值：`connected`（连通）| `disconnected`（断开）
- `checked_at`：Unix 时间戳（秒），表示本次检测时间

### 前端使用示例（参考）

> ⚠️ **注意**：浏览器原生 `EventSource` API 不支持自定义请求头，无法直接传 `Authorization` header。认证方案有两种选择：
> 1. **Cookie 认证**（推荐）：token 写入 HttpOnly Cookie，SSE 请求自动携带，无需额外处理
> 2. **Query 参数**：将 token 以 `?token=xxx` 附在 URL 中，服务端从 query 读取并校验（有 URL 暴露 token 的安全风险，仅用于内网场景）

```javascript
// 方案一：Cookie 认证（token 已由登录写入 Cookie）
const es = new EventSource(`/api/v1/datasource/${id}/status/stream`);
es.addEventListener('status_change', (e) => {
  const { status } = JSON.parse(e.data);
  updateUI(status);
});
// 断线时浏览器自动重连，无需额外处理
```

---

## 五、风险与局限

> 本节回答：这个方案有哪些已知问题和限制？

| 风险 | 影响 | 处理方式 |
|------|------|---------|
| **连接数上限** | 每个 SSE 连接占用一个 goroutine 和文件描述符；同时打开大量标签页时可能超出 fd 上限 | 建议在 hub 中设置单 datasource 最大订阅数（如 10），超出时返回 429；同时调大服务器 `ulimit -n`（待验证具体阈值）|
| **多实例部署** | Hub 是进程内内存结构；多副本部署时，Publish 事件只触达当前实例的订阅者 | 推荐用 Redis Pub/Sub 替换内存 channel 作为跨实例广播层（设计已预留扩展点，Hub.Publish 可切换实现）|
| **Nginx 长连接超时** | Nginx 默认 `proxy_read_timeout 60s`，会断开空闲 SSE 连接 | 服务端每 30s 发送一次 SSE comment（`: heartbeat\n\n`）保活；前端 EventSource 断线后自动重连 |
| **认证 token 过期** | SSE 连接建立后不再重新鉴权，token 过期期间连接仍保持 | 连接建立时校验一次 token；服务端在 token 过期时主动关闭连接（通过 context cancel）。待验证：现有 token 有效期配置（待验证）|
| **事件丢失** | 客户端断线重连期间发生的状态变更无法补发 | 连接建立时立即推送一次当前状态（快照），保证前端初始状态正确 |

---

## 六、实施顺序

> 本节回答：按什么顺序实现，最小可验证步骤是什么？

1. **实现 Hub**（`internal/push/hub.go`）— 纯内存实现，单元测试可独立验证
2. **实现 SSE Handler**（`internal/push/handler.go`）— 手动 curl 验证事件格式
3. **集成到 ServiceContext** — 注入 Hub 实例
4. **接入 cron 探测** — 现有定时任务调用 `hub.Publish()`，端到端验证推送
5. **（可选）接入 connector 事件** — 处理 connector-manager 的上下线事件
6. **（可选）Redis Pub/Sub 替换内存 Hub** — 多实例部署时再做
