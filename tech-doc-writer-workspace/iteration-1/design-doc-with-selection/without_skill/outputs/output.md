# 技术设计方案：数据源连接状态实时推送

**文档版本**：v1.0
**日期**：2026-03-24
**服务**：registration-service

---

## 1. 背景与目标

### 1.1 背景

数据资产注册服务（registration-service）目前通过 gRPC 接口提供数据源的增删改查及连通性检查能力。前端在触发连通性检查后，只能通过轮询接口获取结果，用户体验较差。此外，后台定时任务（cron）也会周期性地检测数据源连通性，但检测结果对前端不可见。

### 1.2 目标

- 当数据源连接状态发生变化（连通 → 断开，断开 → 连通）时，实时推送通知到前端
- 推送范围：仅推送给当前登录用户（租户隔离、用户隔离）
- 不影响现有 gRPC 服务的正常运行

### 1.3 不在范围内

- 推送历史消息记录持久化
- 跨实例的消息广播（本期仅单实例，多实例扩展见第 7 节）
- 前端实现细节

---

## 2. 技术选型：SSE vs WebSocket

### 2.1 需求分析

| 维度 | 说明 |
|------|------|
| 通信方向 | **单向**：服务端 → 客户端（前端无需向服务端发送数据） |
| 消息频率 | 低频（仅在状态变化时触发，非持续高频） |
| 消息类型 | 文本 JSON |
| 客户端 | 浏览器 |

**结论：单向推送场景，SSE 是更自然的选择。**

### 2.2 三个方案横向对比

| 特性 | gorilla/websocket | nhooyr.io/websocket | **SSE（标准库）** |
|------|-------------------|---------------------|------------------|
| 通信方向 | 双向 | 双向 | 单向（服务端推送） |
| 协议 | WebSocket | WebSocket | HTTP/1.1 长连接 |
| 外部依赖 | 需要（~30k stars，稳定） | 需要（较小社区） | **无，使用标准库** |
| API 风格 | 同步，需手动管理 pump goroutine | Context-aware，现代风格 | 原生 `net/http` |
| 代理/防火墙穿透 | 需要代理支持 Upgrade | 需要代理支持 Upgrade | **对 HTTP 代理天然友好** |
| 断线重连 | 需客户端手动实现 | 需客户端手动实现 | **浏览器原生支持自动重连** |
| 心跳机制 | 需手动实现 Ping/Pong | 内置 | 通过 comment 行实现 |
| 实现复杂度 | 高（双向管理、消息帧） | 中 | **低** |
| 适用场景 | 即时通讯、游戏等交互场景 | 同上，现代 Go 项目 | **通知、状态更新、日志流** |

### 2.3 最终选型：**SSE（Server-Sent Events）**

**理由：**

1. **需求完全匹配**：数据源状态变化推送是纯服务端→客户端的单向推送，WebSocket 的双向能力完全浪费。
2. **零外部依赖**：当前项目依赖已较重（go.mod 超过 100 个依赖），使用标准库 `net/http` 实现 SSE，无需新增依赖。
3. **与现有架构契合**：`registration.go` 已经引入 `net/http`（用于 pprof），可在同一进程内复用 HTTP 服务器。
4. **运维友好**：SSE 基于 HTTP，Nginx/API Gateway 无需特殊配置，而 WebSocket 的 Upgrade 握手在部分反向代理环境下需要额外配置。
5. **浏览器原生支持**：`EventSource` API 内置断线重连（默认 3 秒），无需前端额外实现重连逻辑。

> **何时应选 WebSocket？** 若未来需要前端向服务端发送指令（如主动触发检测、取消检测），则应迁移到 WebSocket，推荐届时使用 `nhooyr.io/websocket`（Context 原生支持，API 更符合现代 Go 风格，相比 gorilla 不需要手写 pump goroutine）。

---

## 3. 系统架构

### 3.1 整体架构

```
┌──────────────────────────────────────────────────────────────┐
│                    registration-service                       │
│                                                              │
│  ┌─────────────┐    ┌──────────────────────────────────────┐ │
│  │ gRPC Server │    │         HTTP Server (:8081)           │ │
│  │   (:8080)   │    │                                       │ │
│  │             │    │  GET /api/v1/datasource/status/stream │ │
│  │  CheckData  │    │           SSE Handler                 │ │
│  │  SourceValid│    └─────────────────┬────────────────────┘ │
│  │  ity Logic  │                      │ 注册/注销             │
│  └──────┬──────┘    ┌─────────────────▼────────────────────┐ │
│         │           │           SSE Hub                     │ │
│  ┌──────▼──────┐    │  clients map[userKey]*sseClient       │ │
│  │  Cron Job   │    │  subscribe(userKey) chan Event         │ │
│  │  (定时检测)  │    │  publish(userKey, Event)              │ │
│  └──────┬──────┘    └─────────────────▲────────────────────┘ │
│         │                             │                       │
│         └─────────────────────────────┘                       │
│              发布连接状态变更事件                               │
└──────────────────────────────────────────────────────────────┘
         │ SSE 长连接 (HTTP/1.1)
┌────────▼───────────┐
│      前端浏览器      │
│   new EventSource  │
│  ('/api/v1/...')   │
└────────────────────┘
```

### 3.2 数据流

```
1. 触发路径（主动检测）
   前端 → gRPC CheckDataSourceValidity → 检测结果 → Hub.Publish → SSE 推送到前端

2. 触发路径（定时检测）
   Cron Job → 遍历数据源 → 检测连通性 → 状态变化 → Hub.Publish → SSE 推送到前端

3. SSE 订阅建立
   前端 → GET /api/v1/datasource/status/stream?token=xxx
       → 鉴权（从 user-center 验证 token）
       → Hub.Subscribe(tenantID:userID)
       → 保持长连接，持续接收事件
```

---

## 4. 详细设计

### 4.1 目录结构

在现有项目结构下新增以下文件：

```
internal/
├── push/
│   ├── hub.go          # SSE Hub：管理所有连接，发布/订阅事件
│   ├── event.go        # 事件类型定义
│   └── handler.go      # HTTP Handler：处理 SSE 连接请求
├── http/
│   └── sse_server.go   # HTTP 服务器启动（复用或新建）
```

`ServiceContext` 中新增 `Hub *push.Hub` 字段。

### 4.2 事件定义

```go
// internal/push/event.go

package push

// EventType 推送事件类型
type EventType string

const (
    // EventTypeDataSourceStatus 数据源连接状态变更事件
    EventTypeDataSourceStatus EventType = "datasource_status"
)

// DataSourceStatusEvent 数据源连接状态变更事件数据
type DataSourceStatusEvent struct {
    // DataSourceID 数据源 ID
    DataSourceID uint64 `json:"datasourceId"`
    // DataSourceName 数据源名称
    DataSourceName string `json:"datasourceName"`
    // Connected 是否连通
    Connected bool `json:"connected"`
    // Message 附加信息（断开时的错误信息）
    Message string `json:"message,omitempty"`
    // Timestamp 事件发生时间（Unix 毫秒）
    Timestamp int64 `json:"timestamp"`
}

// Event SSE 推送事件
type Event struct {
    Type EventType `json:"type"`
    Data any       `json:"data"`
}
```

### 4.3 SSE Hub

Hub 负责管理所有 SSE 连接，以 `tenantID:userID` 作为订阅 key，支持同一用户的多个标签页（多连接）。

```go
// internal/push/hub.go

package push

import (
    "encoding/json"
    "fmt"
    "sync"
)

// userKey 用于区分不同用户的订阅 key
type userKey = string

func buildUserKey(tenantID, userID string) userKey {
    return fmt.Sprintf("%s:%s", tenantID, userID)
}

// subscriber 表示单个 SSE 连接
type subscriber struct {
    ch     chan Event
    closed chan struct{}
}

// Hub 管理所有 SSE 连接
type Hub struct {
    mu   sync.RWMutex
    // subs key=userKey，value=该用户的所有连接（支持多标签页）
    subs map[userKey][]*subscriber
}

func NewHub() *Hub {
    return &Hub{
        subs: make(map[userKey][]*subscriber),
    }
}

// Subscribe 为指定用户创建一个订阅，返回事件 channel 和取消订阅函数
func (h *Hub) Subscribe(tenantID, userID string) (<-chan Event, func()) {
    key := buildUserKey(tenantID, userID)
    sub := &subscriber{
        ch:     make(chan Event, 16),
        closed: make(chan struct{}),
    }

    h.mu.Lock()
    h.subs[key] = append(h.subs[key], sub)
    h.mu.Unlock()

    cancel := func() {
        h.mu.Lock()
        defer h.mu.Unlock()
        list := h.subs[key]
        for i, s := range list {
            if s == sub {
                h.subs[key] = append(list[:i], list[i+1:]...)
                break
            }
        }
        if len(h.subs[key]) == 0 {
            delete(h.subs, key)
        }
        close(sub.closed)
    }

    return sub.ch, cancel
}

// Publish 向指定用户的所有连接推送事件
func (h *Hub) Publish(tenantID, userID string, event Event) {
    key := buildUserKey(tenantID, userID)
    h.mu.RLock()
    list := h.subs[key]
    h.mu.RUnlock()

    for _, sub := range list {
        select {
        case sub.ch <- event:
        case <-sub.closed:
            // 连接已关闭，跳过
        default:
            // 缓冲区满，丢弃（避免慢客户端阻塞）
        }
    }
}

// formatSSE 将事件格式化为 SSE 文本协议
func formatSSE(event Event) (string, error) {
    data, err := json.Marshal(event)
    if err != nil {
        return "", err
    }
    return fmt.Sprintf("event: %s\ndata: %s\n\n", event.Type, data), nil
}
```

### 4.4 SSE HTTP Handler

```go
// internal/push/handler.go

package push

import (
    "net/http"
    "time"

    "github.com/zeromicro/go-zero/core/logx"
)

const (
    // heartbeatInterval 心跳间隔，防止代理超时断开连接
    heartbeatInterval = 30 * time.Second
)

// Handler SSE HTTP 处理器
type Handler struct {
    hub      *Hub
    authFunc AuthFunc
}

// AuthFunc 鉴权函数，从请求中提取 tenantID 和 userID
type AuthFunc func(r *http.Request) (tenantID, userID string, err error)

func NewHandler(hub *Hub, authFunc AuthFunc) *Handler {
    return &Handler{hub: hub, authFunc: authFunc}
}

func (h *Handler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
    // 鉴权
    tenantID, userID, err := h.authFunc(r)
    if err != nil {
        http.Error(w, "unauthorized", http.StatusUnauthorized)
        return
    }

    // 设置 SSE 响应头
    w.Header().Set("Content-Type", "text/event-stream")
    w.Header().Set("Cache-Control", "no-cache")
    w.Header().Set("Connection", "keep-alive")
    // 允许跨域（根据实际部署调整）
    w.Header().Set("Access-Control-Allow-Origin", "*")

    flusher, ok := w.(http.Flusher)
    if !ok {
        http.Error(w, "streaming unsupported", http.StatusInternalServerError)
        return
    }

    // 订阅
    eventCh, cancel := h.hub.Subscribe(tenantID, userID)
    defer cancel()

    ticker := time.NewTicker(heartbeatInterval)
    defer ticker.Stop()

    logx.Infof("SSE client connected, tenantID=%s userID=%s", tenantID, userID)
    defer logx.Infof("SSE client disconnected, tenantID=%s userID=%s", tenantID, userID)

    for {
        select {
        case <-r.Context().Done():
            return

        case event := <-eventCh:
            text, err := formatSSE(event)
            if err != nil {
                logx.Errorf("SSE format event failed: %v", err)
                continue
            }
            if _, err = fmt.Fprint(w, text); err != nil {
                return
            }
            flusher.Flush()

        case <-ticker.C:
            // 发送心跳注释行，防止代理超时
            if _, err = fmt.Fprint(w, ": heartbeat\n\n"); err != nil {
                return
            }
            flusher.Flush()
        }
    }
}
```

### 4.5 鉴权实现

SSE 端点的鉴权通过 HTTP Header 中的 `Authorization: Bearer <token>` 实现，调用 user-center 服务验证 token 并提取用户身份信息。

```go
// internal/push/auth.go

package push

import (
    "fmt"
    "net/http"
    "strings"
)

// NewAuthFunc 创建鉴权函数，依赖 user-center gRPC 客户端
func NewAuthFunc(userCenterCli userCenterPb.UserCenter) AuthFunc {
    return func(r *http.Request) (tenantID, userID string, err error) {
        token := extractBearerToken(r)
        if token == "" {
            return "", "", fmt.Errorf("missing token")
        }

        resp, err := userCenterCli.VerifyToken(r.Context(), &userCenterPb.VerifyTokenReq{Token: token})
        if err != nil || !resp.GetValid() {
            return "", "", fmt.Errorf("invalid token")
        }

        return resp.GetTenantId(), resp.GetUserId(), nil
    }
}

func extractBearerToken(r *http.Request) string {
    auth := r.Header.Get("Authorization")
    if strings.HasPrefix(auth, "Bearer ") {
        return strings.TrimPrefix(auth, "Bearer ")
    }
    // 兼容 query 参数（EventSource 不支持自定义 Header 时使用）
    return r.URL.Query().Get("token")
}
```

> **说明**：浏览器原生 `EventSource` API 不支持自定义 Header，因此需要兼容通过 query 参数传递 token（`?token=xxx`）。若前端使用 `fetch` + `ReadableStream` 实现 SSE，则可以通过 Header 传递。

### 4.6 HTTP 服务器集成

在 `registration.go` 的 `main` 函数中，在现有 gRPC server 旁边启动 HTTP 服务器：

```go
// registration.go 中新增（在 gRPC server 启动前）

// 初始化 SSE Hub
hub := push.NewHub()
svcCtx.Hub = hub

// 注册 SSE 路由
mux := http.NewServeMux()
mux.Handle("/api/v1/datasource/status/stream",
    push.NewHandler(hub, push.NewAuthFunc(svcCtx.UserCenterClient)))

// 启动 HTTP 服务器（SSE + 现有 pprof 复用一个 mux）
httpServer := &http.Server{
    Addr:    c.HttpListenOn, // 新增配置项，如 ":8081"
    Handler: mux,
}
go func() {
    if err := httpServer.ListenAndServe(); err != nil && err != http.ErrServerClosed {
        logx.Errorf("HTTP server error: %v", err)
    }
}()
```

### 4.7 发布事件的调用方

#### 4.7.1 主动检测触发（CheckDataSourceValidity Logic）

在 `check_data_source_validity_logic.go` 执行连通性检测后，发布状态事件：

```go
// 在 Logic 中注入 Hub，检测完成后发布事件
func (l *CheckDataSourceValidityLogic) publishStatusEvent(ds *model.DataSource, connected bool, msg string) {
    if l.svcCtx.Hub == nil {
        return
    }
    l.svcCtx.Hub.Publish(ds.TenantID, ds.CreateUin, push.Event{
        Type: push.EventTypeDataSourceStatus,
        Data: push.DataSourceStatusEvent{
            DataSourceID:   ds.ID,
            DataSourceName: ds.Name,
            Connected:      connected,
            Message:        msg,
            Timestamp:      time.Now().UnixMilli(),
        },
    })
}
```

#### 4.7.2 定时检测触发（Cron Job）

在 `internal/cron/` 中新增或修改定时连通性检测任务，检测完毕后比对上次状态，若发生变化则调用 `Hub.Publish`。

```go
// 伪代码示意
func (c *Cron) checkDataSourceConnectivity(ctx context.Context) {
    sources, _ := c.svcCtx.Dao.DataSource.ListAll(ctx)
    for _, ds := range sources {
        connected, msg := testConnection(ds)
        // 与上次缓存的状态比较，仅状态变化时推送
        if lastStatus[ds.ID] != connected {
            lastStatus[ds.ID] = connected
            c.svcCtx.Hub.Publish(ds.TenantID, ds.CreateUin, push.Event{
                Type: push.EventTypeDataSourceStatus,
                Data: push.DataSourceStatusEvent{
                    DataSourceID:   ds.ID,
                    DataSourceName: ds.Name,
                    Connected:      connected,
                    Message:        msg,
                    Timestamp:      time.Now().UnixMilli(),
                },
            })
        }
    }
}
```

---

## 5. 接口规范

### 5.1 SSE 端点

```
GET /api/v1/datasource/status/stream
```

**请求 Header（推荐）：**
```
Authorization: Bearer <token>
```

**请求 Query（兼容原生 EventSource）：**
```
?token=<token>
```

**响应 Header：**
```
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive
```

**SSE 事件格式：**

```
event: datasource_status
data: {"type":"datasource_status","data":{"datasourceId":42,"datasourceName":"生产MySQL","connected":false,"message":"dial tcp: connection refused","timestamp":1711267200000}}

```

**心跳（每 30 秒）：**
```
: heartbeat

```

### 5.2 前端接入示例

```javascript
// 使用原生 EventSource（token 通过 query 传递）
const es = new EventSource(`/api/v1/datasource/status/stream?token=${token}`);

es.addEventListener('datasource_status', (e) => {
  const event = JSON.parse(e.data);
  const { datasourceId, datasourceName, connected, message } = event.data;
  console.log(`数据源 [${datasourceName}] 连接状态：${connected ? '已连通' : '已断开'}`);
});

es.onerror = () => {
  // EventSource 会自动重连，此处可做 UI 提示
};
```

---

## 6. 配置项

在 `internal/config/config.go` 中新增：

```go
type Config struct {
    // ... 现有字段 ...

    // SSEConf SSE 服务配置
    SSEConf SSEConf
}

type SSEConf struct {
    // ListenOn HTTP 监听地址，默认 ":8081"
    ListenOn string `json:",default=:8081"`
}
```

`etc/registration-service.yaml` 中对应新增：

```yaml
SSEConf:
  ListenOn: ":8081"
```

---

## 7. 扩展性：多实例部署

当前方案使用进程内 Hub（`sync.RWMutex` + `map`），仅支持单实例。多实例扩展方案：

**方案：基于 Redis Pub/Sub 的 Hub**

项目已经依赖 Redis（用于 Redis Streams 事件消费），可以直接复用：

1. `Hub.Publish` → 写入 Redis Channel（`datasource:status:{tenantID}:{userID}`）
2. 每个实例订阅 Redis Channel → 转发到本地连接的 SSE 客户端

```
实例A                   Redis                  实例B
 │  Hub.Publish()         │                     │
 ├──PUBLISH channel──────►│                     │
 │                        │──SUBSCRIBE──────────►│
 │                        │                     │ 转发到本地 SSE 客户端
```

> 本期不实现，待服务横向扩展需求出现时再引入。

---

## 8. 风险与缓解措施

| 风险 | 描述 | 缓解措施 |
|------|------|----------|
| 连接数过多 | 大量用户同时在线，goroutine 和内存占用增加 | 每个 SSE 连接消耗约 1 个 goroutine + channel 缓冲（< 1KB），万级连接可接受；必要时加最大连接数限制 |
| 慢客户端阻塞 | 客户端消费事件过慢，channel 满 | 采用 `default` 分支丢弃策略（hub.go 第 60 行），状态事件为幂等通知，丢弃后前端可下次重连时重新拉取状态 |
| 代理超时断开 | Nginx 默认 60s 无数据断开 | 每 30 秒发送 SSE 心跳注释行（`: heartbeat`），保持连接活跃 |
| EventSource 不支持 Header | 浏览器原生 API 无法设置 Authorization | 兼容 query 参数 `?token=xxx`，注意 HTTPS 防止 token 泄漏；或要求前端使用 fetch + ReadableStream |
| 事件丢失 | 网络抖动导致重连期间事件丢失 | 结合 `Last-Event-ID`（SSE 协议支持），服务端缓存最近 N 条事件重发（本期暂不实现，前端重连后可主动查询最新状态） |

---

## 9. 实施计划

### Phase 1：核心推送功能（必须）
1. 新增 `internal/push/` 目录，实现 `hub.go`、`event.go`、`handler.go`、`auth.go`
2. 在 `ServiceContext` 中注入 `Hub`
3. 修改 `registration.go`，启动 HTTP 服务器
4. 在 `CheckDataSourceValidity` 逻辑中发布事件
5. 新增配置项 `SSEConf`

### Phase 2：定时检测推送（可选）
1. 新增 `internal/cron/datasource_check.go`，实现定时连通性检测
2. 检测结果与上次状态比对，仅状态变化时推送

### Phase 3：可靠性增强（未来）
1. 支持 `Last-Event-ID` 断线重连补偿
2. 多实例支持（基于 Redis Pub/Sub）

---

## 10. 总结

| 方案 | 结论 |
|------|------|
| **选型** | SSE（Server-Sent Events），使用标准库 `net/http` |
| **不选 gorilla/websocket** | 双向协议，对本场景过度设计；需额外依赖和 pump goroutine 管理 |
| **不选 nhooyr.io/websocket** | 同上，双向能力在本场景无价值；社区较小 |
| **核心组件** | `push.Hub`（进程内发布/订阅） + `push.Handler`（SSE HTTP 处理） |
| **集成方式** | 与 gRPC server 共进程，独立监听 HTTP 端口（可配置） |
| **扩展路径** | 单实例 → 多实例扩展时替换 Hub 实现为 Redis Pub/Sub，对调用方无感知 |
