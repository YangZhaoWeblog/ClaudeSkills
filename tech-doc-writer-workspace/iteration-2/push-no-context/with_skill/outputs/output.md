# 注册服务实时推送功能技术设计方案

**背景：** 注册服务当前所有接口均为请求-响应模式，客户端无法得知链上事件处理结果（资源上链、数据产品发布审批等）的实时状态变更，需要轮询或依赖外部通知。
**核心结论：** 采用 **gRPC 服务端流式推送**，在现有 Redis Streams 事件消费链路末端插入推送逻辑，最小化改动存量代码，适配当前纯 gRPC 技术栈。

---

## 一、背景与问题根因

> 本节回答：为什么现在需要实时推送？

注册服务的核心状态变更由链上事件驱动，链路为：

```
链服务监听区块链 → 推送到 Redis Streams → 注册服务消费 → 写库
```

当前消费结果（资源创建成功、数据产品审批通过等）**不对外通知**。调用方只能通过两种方式感知状态变更：

1. **轮询查询接口**（现状）：实时性差，浪费链路资源，且轮询间隔与实际延迟存在偏差
2. **依赖外部系统通知**（当前无此机制）

需要推送的典型场景：

| 场景 | 触发事件 | 当前痛点 |
|------|---------|---------|
| 资源上链确认 | `create_resources` / `update_resource` | 前端不知何时刷新状态 |
| 数据产品发布审批 | `approve_publish_product` / `approve_unpublish_product` | 审批结果无法实时感知 |
| 交易状态轮询确认 | cron 任务更新 `resource_tx` / `product_tx` | 轮询结果无法向上游透传 |
| 产品目录化 | `catalog_product` | 同上 |

---

## 二、方案选型对比

> 本节回答：有哪些推送方案，应该选哪个？

**候选方案：**

| 维度 | 方案 A：gRPC 服务端流 | 方案 B：Redis Pub/Sub 输出 | 方案 C：Webhook 回调 |
|------|---------------------|--------------------------|-------------------|
| 与现有技术栈一致性 | ✅ 纯 gRPC，零新依赖 | ⚠️ 需客户端直连 Redis | ❌ 新增 HTTP 调用层 |
| 消费端接入复杂度 | ✅ 标准 gRPC streaming | ⚠️ 需订阅 Redis 频道 | ⚠️ 需维护回调服务 |
| 服务侧状态管理 | ⚠️ 需管理 stream 连接 | ✅ 无状态 | ✅ 无状态 |
| 背压 / 流控 | ✅ gRPC 内置 | ❌ 无内置背压 | ❌ 无背压，需重试 |
| 过滤订阅（按实体/类型）| ✅ 订阅时传参 | ⚠️ 需约定频道命名规范 | ⚠️ 客户端自行过滤 |
| 断线重连数据补发 | ⚠️ 需设计缓冲（待验证） | ❌ 断线期间消息丢失 | ✅ 可重试 |

**推荐方案 A（gRPC 服务端流）**，理由：
- 现有服务是纯 gRPC 服务，所有外部调用方均通过 gRPC 接入，方案 A 零增新依赖、接入成本最低
- gRPC streaming 有内置流控，避免推送风暴打垮消费端
- 事件过滤可在订阅请求参数中声明，不依赖频道命名约定

---

## 三、总体架构设计

> 本节回答：推送链路如何接入现有架构？

在现有消费链路末端增加一个 **推送中枢（PushHub）**，事件处理器写库后通知 PushHub，PushHub 将事件广播给已订阅的 gRPC 流连接：

```
链服务 → Redis Streams → eventManager → handler.handleEvent()
                                              ↓
                                         写数据库
                                              ↓
                                         PushHub.Publish()
                                              ↓
                                    [已订阅的 gRPC 流连接]
```

cron 任务更新交易状态后，同样调用 `PushHub.Publish()`。

**PushHub 职责：**
- 维护订阅者注册表（`map[subscriptionID]chan PushEvent`）
- 支持按 `entity_type`（resource / product / entity）和 `workspace`（链空间 sid）过滤
- 连接断开时自动清理注册表

---

## 四、接口设计

> 本节回答：新增哪些 proto 接口，消息结构如何定义？

在 `proto/registration.proto` 中新增一个 RPC 和相关消息类型：

```protobuf
// Subscribe 订阅实时事件推送
rpc Subscribe(SubscribeReq) returns (stream PushEvent);

message SubscribeReq {
    string request_id    = 1;
    // 订阅的实体类型，空表示订阅所有类型
    // 取值：resource / product / entity
    repeated string entity_types = 2;
    // 订阅的链空间 sid，空表示订阅所有空间
    repeated string sids         = 3;
}

message PushEvent {
    string event_id      = 1;  // 事件唯一 ID
    string entity_type   = 2;  // resource / product / entity
    string entity_id     = 3;  // 实体业务 ID
    string event_type    = 4;  // 事件名，与 handler.eventName() 对齐
    string sid           = 5;  // 所属链空间
    int64  timestamp     = 6;  // 事件发生时间（Unix ms）
    string payload       = 7;  // JSON 序列化的事件附加信息（待验证：是否需要结构化字段）
}
```

事件类型 `event_type` 复用现有事件名称（来自各 handler 的 `eventName()` 返回值），例如：`create_resources`、`approve_publish_product`。

---

## 五、PushHub 设计

> 本节回答：PushHub 内部如何实现？

```go
// PushHub 推送中枢，管理所有订阅者的事件分发
type PushHub struct {
    mu          sync.RWMutex
    subscribers map[string]*subscriber  // key: subscriptionID
}

type subscriber struct {
    id          string
    entityTypes map[string]bool  // 空 map 表示订阅所有类型
    sids        map[string]bool  // 空 map 表示订阅所有空间
    ch          chan *PushEvent
}
```

核心方法：

- `Register(id string, req *SubscribeReq) (<-chan *PushEvent, cancel func())`：注册订阅，返回事件 channel 和取消函数
- `Publish(event *PushEvent)`：向匹配订阅者的 channel 非阻塞写入事件（channel 满则丢弃并打印告警日志，避免推送阻塞链路）

**PushHub 注入位置：** 在 `ServiceContext` 中作为字段注入，事件 handler 通过 `svcCtx.PushHub.Publish()` 调用。

---

## 六、改动范围

> 本节回答：需要改哪些文件，改动量有多大？

| 文件 / 目录 | 改动类型 | 说明 |
|------------|---------|------|
| `proto/registration.proto` | 新增 | 添加 `Subscribe` RPC 和消息定义 |
| `pb/registrationpb/` | 生成 | 执行 `make protoc` 自动生成 |
| `internal/push/hub.go` | 新增 | PushHub 实现 |
| `internal/svc/service_context.go` | 修改 | 注入 `PushHub` 字段 |
| `internal/server/registration_server.go` | 修改（生成） | 添加 `Subscribe` server-streaming handler |
| `internal/logic/subscribe_logic.go` | 新增 | Subscribe 逻辑层，调用 PushHub.Register |
| `internal/event/*.go`（各 handler） | 修改 | 在写库后调用 `svcCtx.PushHub.Publish()` |
| `internal/cron/tx_polling.go` | 修改 | 交易状态更新后调用 `svcCtx.PushHub.Publish()` |

存量业务逻辑无侵入修改，仅在事件处理函数末端增加 `Publish()` 调用。

---

## 七、风险与局限

> 本节回答：该方案有哪些已知风险和不适用场景？

| 风险项 | 说明 | 缓解措施 |
|--------|------|---------|
| **消息丢失（断线重连）** | 客户端断线期间产生的事件无法补发，重连后只收新事件 | 标记为当前版本局限；若需补发，需持久化事件队列（待验证：是否业务必须） |
| **内存堆积** | 慢消费客户端的 channel 填满后丢弃事件 | channel 满时记录告警，运营侧可据此发现消费能力不足的客户端 |
| **连接数限制** | 大量客户端长连接可能超出 gRPC server 默认连接数 | 待验证：当前部署规模的实际连接数上限 |
| **单点 PushHub** | PushHub 是进程内内存结构，多副本部署时事件只推送给订阅所在副本 | 当前注册服务部署为单副本（待验证），多副本场景需引入跨进程广播（如 Redis Pub/Sub） |
| **payload 体积** | 事件附带的 payload 字段未定义大小限制 | 初版仅包含实体 ID 和状态，不传递完整实体数据 |
