# 注册服务实时推送功能技术设计方案

## 1. 背景与目标

### 1.1 背景

注册服务（registration-service）当前采用纯请求-响应模式，客户端只能通过轮询获取资源上链状态、产品发布状态等异步操作的最终结果。

典型场景：
- 用户创建数据资源后，资源上链需要等待区块链确认（`OnChainState: 上链中 → 上链成功/失败`），客户端需要反复调用 `GetResourceInfo` 轮询结果
- 用户发布数据产品后，发布流程需要经过合约事件回调才能完成（`PublishState: 发布中 → 已发布/驳回`），同样需要轮询

轮询方式存在以下问题：
- 实时性差：轮询间隔导致状态感知延迟
- 资源浪费：大量无效请求消耗服务器和网络资源
- 客户端实现复杂：需要自行管理轮询逻辑和超时

### 1.2 目标

为注册服务增加 **gRPC Server Streaming** 实时推送能力，让客户端能够订阅感兴趣的事件，服务端主动推送状态变更通知，替代客户端轮询。

### 1.3 设计原则

- 最小化对现有业务逻辑的侵入，推送逻辑与业务逻辑解耦
- 利用现有 Redis 基础设施，不引入新的中间件
- 与现有 gRPC 架构保持一致，不引入 WebSocket 等异构协议
- 单节点和多节点部署均可正常工作

---

## 2. 推送事件范围

根据现有异步流程，以下状态变更需要推送通知：

| 事件类型 | 触发来源 | 说明 |
|---------|---------|------|
| `RESOURCE_ON_CHAIN_STATE_CHANGED` | 合约事件处理器 / 交易轮询 | 资源上链状态变更（上链中→成功/失败） |
| `RESOURCE_UPDATED` | 合约事件处理器 | 资源信息被链上同步更新 |
| `RESOURCE_DELETED` | 合约事件处理器 | 资源被链上删除 |
| `PRODUCT_PUBLISH_STATE_CHANGED` | 合约事件处理器 / 交易轮询 | 产品发布状态变更（发布中→已发布/驳回/已下架） |
| `PRODUCT_ON_CHAIN_STATE_CHANGED` | 合约事件处理器 / 交易轮询 | 产品上链状态变更 |
| `RESOURCE_REF_CHANGED` | 合约事件处理器 | 资源引用关系批量增删 |

---

## 3. 技术方案选型

### 3.1 方案对比

| 方案 | 优点 | 缺点 | 适配性 |
|-----|------|------|--------|
| **gRPC Server Streaming** | 与现有 gRPC 架构完全一致，天然支持流式传输，go-zero 框架原生支持 | 需要长连接，需要处理连接管理 | ✅ 最佳 |
| WebSocket | 浏览器友好 | 需要新增 HTTP 层，与纯 gRPC 架构不一致 | ❌ 不适合 |
| SSE（Server-Sent Events） | 简单 | 单向，HTTP 层，不符合现有架构 | ❌ 不适合 |
| gRPC Bidirectional Streaming | 更灵活 | 实现复杂度高，双向通信在此场景没有必要 | ⚠️ 过度设计 |

**结论：采用 gRPC Server Streaming 方案。**

### 3.2 消息分发方案

服务可能多实例部署，客户端连接的实例不一定是处理事件的实例，需要跨实例消息分发。

采用 **Redis Pub/Sub** 作为内部消息总线：
- 事件产生时，发布到 Redis Channel
- 每个服务实例订阅 Redis Channel，转发给本实例上的连接客户端
- 利用现有 Redis 基础设施（`EventConf` 中已有 Redis 配置），无需引入新组件

```
事件触发（合约事件处理器/交易轮询）
        ↓
  Redis Pub/Sub（内部消息总线）
        ↓
  各实例订阅并过滤
        ↓
  gRPC Stream 推送给客户端
```

---

## 4. 详细设计

### 4.1 Proto 定义

在 `proto/registration.proto` 中新增以下定义：

```protobuf
// ============ 实时推送接口定义 ================

// 推送事件类型
enum PushEventType {
  PUSH_EVENT_TYPE_UNSPECIFIED = 0;
  // 资源上链状态变更
  PUSH_EVENT_TYPE_RESOURCE_ON_CHAIN_STATE_CHANGED = 1;
  // 资源信息更新
  PUSH_EVENT_TYPE_RESOURCE_UPDATED = 2;
  // 资源删除
  PUSH_EVENT_TYPE_RESOURCE_DELETED = 3;
  // 产品发布状态变更
  PUSH_EVENT_TYPE_PRODUCT_PUBLISH_STATE_CHANGED = 4;
  // 产品上链状态变更
  PUSH_EVENT_TYPE_PRODUCT_ON_CHAIN_STATE_CHANGED = 5;
  // 资源引用关系变更
  PUSH_EVENT_TYPE_RESOURCE_REF_CHANGED = 6;
}

// 订阅推送请求
message SubscribePushReq {
  // 链空间唯一标识（必填）
  string sid = 1 [(google.api.field_behavior) = REQUIRED];
  // 链账户（必填）
  string address = 2 [(google.api.field_behavior) = REQUIRED];
  // 订阅的事件类型，为空则订阅全部
  repeated PushEventType eventTypes = 3 [(google.api.field_behavior) = OPTIONAL];
}

// 推送事件消息
message PushEvent {
  // 事件类型
  PushEventType eventType = 1;
  // 事件 ID（唯一标识，用于去重）
  string eventId = 2;
  // 事件发生时间（Unix 毫秒时间戳）
  int64 occurredAt = 3;
  // 关联资源 ID（资源类事件）
  int64 resourceId = 4;
  // 关联产品 ID（产品类事件）
  int64 productId = 5;
  // 资源上链状态（PUSH_EVENT_TYPE_RESOURCE_ON_CHAIN_STATE_CHANGED 时有效）
  int32 resourceOnChainState = 6;
  // 产品发布状态（PUSH_EVENT_TYPE_PRODUCT_PUBLISH_STATE_CHANGED 时有效）
  int32 productPublishState = 7;
  // 产品上链状态（PUSH_EVENT_TYPE_PRODUCT_ON_CHAIN_STATE_CHANGED 时有效）
  int32 productOnChainState = 8;
  // 心跳标识，为 true 时表示心跳包，其余字段无意义
  bool heartbeat = 9;
}

// SubscribePush 订阅实时推送（Server Streaming RPC）
rpc SubscribePush(SubscribePushReq) returns (stream PushEvent) {}
```

### 4.2 推送管理器（PushManager）

新建 `internal/push/manager.go`，负责：
1. 管理客户端连接（订阅注册/注销）
2. 订阅 Redis Pub/Sub 频道
3. 将 Redis 消息分发到匹配的客户端连接

```go
// internal/push/manager.go

package push

// Manager 推送管理器，负责连接管理与消息分发
type Manager struct {
    redisClient *redis.Client   // 使用现有 EventConf 的 Redis 配置
    subs        sync.Map        // key: subscriptionKey, value: *Subscription
    logger      logx.Logger
}

// Subscription 单个客户端订阅
type Subscription struct {
    sid       string
    address   string
    eventTypes map[PushEventType]struct{}
    ch        chan *registrationpb.PushEvent   // 推送通道
}

// Subscribe 注册订阅，返回事件 channel
func (m *Manager) Subscribe(sid, address string, eventTypes []PushEventType) (subKey string, ch <-chan *registrationpb.PushEvent)

// Unsubscribe 注销订阅
func (m *Manager) Unsubscribe(subKey string)

// Publish 发布事件（由事件处理器/交易轮询调用）
func (m *Manager) Publish(ctx context.Context, event *PushEventMessage)
```

**订阅键设计**：`{sid}:{address}:{uuid}`，其中 uuid 保证同一 address 多次订阅互不干扰。

**Redis Channel 设计**：`push:event:{sid}`，按 sid 分 channel，减少不必要的消息过滤。

### 4.3 PushManager 消息流转

```
Publish(event)
    ↓
将 event 序列化（JSON）
    ↓
PUBLISH 到 Redis Channel: push:event:{event.Sid}
    ↓
（所有实例）Redis Subscribe 回调触发
    ↓
遍历本实例 subs，过滤 sid + address + eventType 匹配的订阅
    ↓
向匹配订阅的 ch 发送事件（非阻塞，channel 满则丢弃并记录日志）
```

### 4.4 PushEventMessage 内部消息结构

Redis Pub/Sub 传递的内部消息体（与 proto 定义分离，避免版本依赖问题）：

```go
// internal/push/event.go

type PushEventMessage struct {
    Sid        string        `json:"sid"`
    Address    string        `json:"address"`
    EventType  PushEventType `json:"eventType"`
    EventId    string        `json:"eventId"`
    OccurredAt int64         `json:"occurredAt"`
    ResourceId uint64        `json:"resourceId,omitempty"`
    ProductId  uint64        `json:"productId,omitempty"`
    // 以下字段根据 EventType 填充
    ResourceOnChainState int8 `json:"resourceOnChainState,omitempty"`
    ProductPublishState  int8 `json:"productPublishState,omitempty"`
    ProductOnChainState  int8 `json:"productOnChainState,omitempty"`
}
```

### 4.5 gRPC Server Streaming 处理逻辑

新建 `internal/logic/subscribe_push_logic.go`：

```go
// SubscribePush 订阅实时推送
func (l *SubscribePushLogic) SubscribePush(
    in *registrationpb.SubscribePushReq,
    stream registrationpb.Registration_SubscribePushServer,
) error {
    // 1. 参数校验
    if errCode, detail := l.checkParams(in); errCode != code.Success {
        return l.responseErr(errCode, detail)
    }

    // 2. 注册订阅
    subKey, ch := l.svcCtx.PushManager.Subscribe(
        in.GetSid(), in.GetAddress(), in.GetEventTypes(),
    )
    defer l.svcCtx.PushManager.Unsubscribe(subKey)

    // 3. 启动心跳定时器（30s）
    heartbeatTicker := time.NewTicker(30 * time.Second)
    defer heartbeatTicker.Stop()

    // 4. 事件循环
    for {
        select {
        case event, ok := <-ch:
            if !ok {
                return nil
            }
            if err := stream.Send(event); err != nil {
                l.Logger.Errorf("SubscribePush send event failed, subKey: %s, err: %v", subKey, err)
                return err
            }
        case <-heartbeatTicker.C:
            // 发送心跳包，维持长连接
            if err := stream.Send(&registrationpb.PushEvent{Heartbeat: true}); err != nil {
                l.Logger.Errorf("SubscribePush send heartbeat failed, subKey: %s, err: %v", subKey, err)
                return err
            }
        case <-stream.Context().Done():
            // 客户端断开连接
            l.Logger.Infof("SubscribePush client disconnected, subKey: %s", subKey)
            return nil
        }
    }
}
```

### 4.6 事件发布集成点

在现有代码的以下位置集成 `PushManager.Publish` 调用：

#### 4.6.1 合约事件处理器

| 文件 | 集成位置 | 事件类型 |
|-----|---------|---------|
| `internal/event/create_resources.go` | `processSingleResource` 成功后 | `RESOURCE_ON_CHAIN_STATE_CHANGED` |
| `internal/event/update_resource.go` | `handleEvent` 成功后 | `RESOURCE_UPDATED` |
| `internal/event/delete_resource.go` | `handleEvent` 成功后 | `RESOURCE_DELETED` |
| `internal/event/publish_product.go` | `handleEvent` 成功后 | `PRODUCT_PUBLISH_STATE_CHANGED` |
| `internal/event/unpublish_product.go` | `handleEvent` 成功后 | `PRODUCT_PUBLISH_STATE_CHANGED` |
| `internal/event/approve_publish_product.go` | `handleEvent` 成功后 | `PRODUCT_PUBLISH_STATE_CHANGED` |
| `internal/event/approve_unpublish_product.go` | `handleEvent` 成功后 | `PRODUCT_PUBLISH_STATE_CHANGED` |
| `internal/event/batch_add_resource_ref.go` | `handleEvent` 成功后 | `RESOURCE_REF_CHANGED` |
| `internal/event/batch_remove_resource_ref.go` | `handleEvent` 成功后 | `RESOURCE_REF_CHANGED` |

集成示例（`publish_product.go` 中）：

```go
// 在 handleEvent 最后，数据库更新成功后
svcCtx.PushManager.Publish(ctx, &push.PushEventMessage{
    Sid:                 h.sid,
    Address:             product.Ownership.OwnerAddress,
    EventType:           push.PushEventTypeProductPublishStateChanged,
    EventId:             uuid.NewString(),
    OccurredAt:          time.Now().UnixMilli(),
    ProductId:           productModel.ID,
    ProductPublishState: int8(constant.ProductPublishStatePublished),
})
```

> **注意**：事件处理器目前没有 `svcCtx` 依赖注入（除 `CreateResourcesEventHandler` 外），需要在构造函数中补充传入 `*push.Manager`。

#### 4.6.2 交易轮询器

`internal/cron/tx_polling.go` 中，当交易状态从 `上链中` 变更为 `上链成功/失败` 时，发布对应推送事件。

### 4.7 ServiceContext 扩展

在 `internal/svc/service_context.go` 中增加 `PushManager` 字段：

```go
type ServiceContext struct {
    Config             config.Config
    Dao                *dao.Dao
    ChainServiceClient chainCli.Chain
    KeyServiceClient   keyCli.Key
    ConnectorClient    connectorCli.Connector
    UserCenterClient   userCenterCli.UserCenter
    Http               *http.Http
    PushManager        *push.Manager   // 新增
}
```

在 `NewServiceContext` 中初始化：

```go
pushManager, err := push.NewManager(&c.EventConf)
if err != nil {
    panic(fmt.Sprintf("failed to init push manager: %v", err))
}
svcCtx.PushManager = pushManager
```

### 4.8 配置扩展

`PushManager` 复用 `EventConf` 中的 Redis 配置（已有 Host、Password、ConfType、Username、MasterName），不需要新增配置项。

可选：在 `config.go` 中增加推送专项配置，仅当有特殊需求时使用：

```go
type PushConf struct {
    // ChannelBufferSize 每个订阅的事件 channel 缓冲大小，默认 64
    ChannelBufferSize int
    // HeartbeatInterval 心跳间隔（秒），默认 30
    HeartbeatInterval int
}
```

---

## 5. 目录结构变化

```
internal/
├── push/
│   ├── manager.go       # PushManager：连接管理、Redis Pub/Sub、消息分发
│   ├── event.go         # PushEventMessage 内部消息结构及事件类型枚举
│   └── manager_test.go  # 单元测试
├── logic/
│   └── subscribe_push_logic.go   # 新增 SubscribePush gRPC 处理逻辑
├── server/
│   └── registration_server.go    # 新增 SubscribePush 方法路由（goctl 生成）
└── svc/
    └── service_context.go        # 增加 PushManager 字段
```

---

## 6. 错误处理与边界情况

### 6.1 客户端断线重连

gRPC Stream 本身不支持自动重连，客户端断连后需重新调用 `SubscribePush` 建立新的订阅。服务端检测到 `stream.Context().Done()` 后自动清理订阅。

客户端重连期间可能错过事件，业务上需要配合 `GetResourceInfo` / `GetProductInfo` 在重连时查询一次最新状态作为补偿。

### 6.2 消息积压

每个订阅的 channel 设置固定大小缓冲（默认 64）。当客户端处理速度跟不上事件产生速度时，采用**丢弃策略**：非阻塞发送，channel 满时跳过并打 warning 日志，不影响其他订阅。

### 6.3 Redis 连接断开

`PushManager` 内部对 Redis Pub/Sub 连接进行监控，断连后自动重订阅（指数退避重试），期间新产生的事件会丢失，这在当前业务场景下可接受（用户感知到推送超时后可手动刷新）。

### 6.4 服务重启

服务重启后所有 gRPC 长连接断开，客户端需要重新订阅。服务端无需持久化订阅状态。

### 6.5 多实例部署

通过 Redis Pub/Sub 广播，每个实例独立处理本实例上的订阅，天然支持多实例部署。

---

## 7. 实现步骤

1. **新增 proto 定义** → `make protoc` 生成代码
2. **实现 `internal/push/` 包**（Manager + PushEventMessage）
3. **扩展 ServiceContext**，初始化 PushManager
4. **实现 `subscribe_push_logic.go`**
5. **注册 server 路由**（goctl 生成或手动添加至 `registration_server.go`）
6. **在各事件处理器中集成 `Publish` 调用**
7. **在交易轮询器中集成 `Publish` 调用**
8. **本地联调验证**

---

## 8. 与现有架构的契合点

| 现有设计 | 本方案的利用/兼容 |
|---------|---------------|
| Redis 已作为事件总线（`EventConf`） | 复用同一 Redis 配置，采用 Pub/Sub 作为内部消息总线 |
| 纯 gRPC 服务架构 | 使用 gRPC Server Streaming，无需引入新协议 |
| go-zero 框架 | Server Streaming 路由注册与普通 RPC 方式一致 |
| 事件处理器已有完整业务上下文 | 在事件处理器末尾追加 `Publish` 即可，侵入最小 |
| `ServiceContext` 依赖注入容器 | PushManager 作为新字段注入，与现有模式一致 |
