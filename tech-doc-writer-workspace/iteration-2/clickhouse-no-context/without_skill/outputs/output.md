# ClickHouse 数据源支持可行性调研报告

**日期**：2026-03-24
**项目**：registration-service（数据资产注册服务）
**结论**：建议支持，优先级中等，实现成本低

---

## 一、背景

registration-service 是一个数据资产注册服务，提供 gRPC 接口，支持对数据源、资源、产品的全生命周期管理。目前已支持以下数据源驱动：

| 枚举值 | 数据库类型 |
|--------|-----------|
| Mysql (1) | MySQL |
| Kingbase (2) | 人大金仓 |
| LLMHub (3) | LLM Hub |
| TiDB (4) | TiDB |
| TDSQL (5) | 腾讯 TDSQL |
| VastBase (6) | 海量数据库 |
| GBase8a (7) | 南大通用 GBase8a |
| Dameng (9) | 达梦数据库 |

本报告调研是否应将 ClickHouse 纳入支持范围。

---

## 二、ClickHouse 技术特性

### 2.1 定位与架构

ClickHouse 是由 Yandex 开发、现由 ClickHouse Inc. 维护的开源列式分析型数据库（OLAP）。其核心设计目标是超大规模数据的高性能聚合查询，与本服务已支持的 OLTP 数据库（MySQL、Dameng 等）在使用场景上有本质区别。

| 特性 | ClickHouse | MySQL/PostgreSQL |
|------|-----------|-----------------|
| 存储模型 | 列式存储 | 行式存储 |
| 主要场景 | OLAP（分析） | OLTP（事务） |
| 写入模式 | 批量写入 | 单行写入 |
| 事务支持 | 有限（不支持标准多行事务） | 完整 ACID |
| 典型查询 | 聚合、宽表扫描 | 点查、关联查询 |

### 2.2 协议与接口

ClickHouse 提供两种主要接口：

- **HTTP 接口**：端口 8123，支持 SQL 查询
- **Native TCP 接口**：端口 9000，性能更高
- **MySQL 协议兼容层**：端口 9004，部分支持 MySQL 协议

Go 生态中成熟的驱动：
- [`github.com/ClickHouse/clickhouse-go/v2`](https://github.com/ClickHouse/clickhouse-go)：官方驱动，支持 `database/sql` 接口，维护活跃
- [`gorm.io/driver/clickhouse`](https://github.com/go-gorm/clickhouse)：GORM 社区维护的 ClickHouse 方言，基于 `clickhouse-go/v2`

### 2.3 SQL 兼容性差异

ClickHouse 的 SQL 方言与标准 SQL 存在若干差异，对本服务的影响如下：

| 查询场景 | 差异说明 |
|---------|---------|
| `information_schema` | 支持，但部分字段语义不同 |
| `PRIMARY KEY` | 语义不同（是排序键/稀疏索引，非唯一约束） |
| `UNIQUE` 约束 | **不支持** |
| `AUTO_INCREMENT` | **不支持**（无自增列） |
| Schema 概念 | 有 database，无 schema（与 MySQL 类似） |
| `ColumnTypes` 查询 | 需要定制，`information_schema.columns` 可用但字段有差异 |

---

## 三、与现有架构的适配性分析

### 3.1 Datasource 接口

现有接口定义如下：

```go
type Datasource interface {
    Open() (*gorm.DB, error)
    Ping() error
    ColumnTypes(schema, tableName string) ([]*ColumnType, error)
    GetTables(schema string) ([]string, error)
    GetSchemas() ([]string, error)
}
```

ClickHouse 驱动对各方法的适配情况：

| 方法 | 可行性 | 备注 |
|------|--------|------|
| `Open()` | ✅ 可行 | 使用 `gorm.io/driver/clickhouse`，需添加超时 goroutine 模式（与 MySQL/PgSQL 驱动一致） |
| `Ping()` | ✅ 可行 | 执行 `SELECT 1` 探活 |
| `GetTables()` | ✅ 可行 | `SHOW TABLES` 或查询 `information_schema.tables` |
| `GetSchemas()` | ✅ 可行（返回 nil）| ClickHouse 无独立 schema 层级，与 MySQL 驱动的 `GetSchemas()` 处理方式相同 |
| `ColumnTypes()` | ⚠️ 需定制 | 可查询 `information_schema.columns`，但 `PRIMARY KEY`、`UNIQUE`、`AUTO_INCREMENT` 语义不同，需特殊处理 |

### 3.2 ColumnType 映射的注意事项

ClickHouse 的主要列类型与标准 SQL 的映射关系：

| ClickHouse 类型 | 对应 `DatabaseTypeName` 建议 | 特殊处理 |
|----------------|----------------------------|---------|
| `UInt8/16/32/64` | 原样返回 | 无 `AutoIncrement` |
| `Int8/16/32/64` | 原样返回 | — |
| `Float32/Float64` | 原样返回 | — |
| `String` | `String` | 无长度限制 |
| `FixedString(N)` | `FixedString` | Length = N |
| `DateTime/Date` | 原样返回 | — |
| `Nullable(T)` | 解包内层类型 | Nullable = true |
| `Array(T)` | 原样返回 | — |
| `LowCardinality(T)` | 解包内层类型 | — |

`PrimaryKey` 字段：ClickHouse 的 `ORDER BY` / `PRIMARY KEY` 是排序键，不是唯一约束，建议统一置为 `false`，或通过 `system.columns` 表获取排序键信息后标注。

### 3.3 TLS 支持

`clickhouse-go/v2` 原生支持 TLS 配置，支持：
- `tls.Config` 注入（InsecureSkipVerify、CA 证书、客户端证书）
- 与现有 `Tls` 结构体完全兼容

实现方式可参考 `MysqlDriverSource.tlsConfig()` 的现有逻辑，直接复用。

---

## 四、实现方案

### 4.1 新增枚举

在 `datasource.go` 中添加：

```go
const (
    // ... 现有枚举
    ClickHouse Type = iota + ... // ClickHouse
)

var TypeList = []Type{..., ClickHouse}
```

### 4.2 新建驱动文件

创建 `internal/utils/datasource/clickhouse_driver.go`，实现 `Datasource` 接口。结构体参考 `MysqlDriverSource`：

```go
type ClickHouseDriverSource struct {
    Host     string
    Port     int
    User     string
    Password string
    Database string
    Params   []*Param
    Tls      *Tls
}
```

`ColumnTypes` 实现建议通过以下 SQL 查询：

```sql
SELECT
    name, type, is_in_primary_key, default_kind, default_expression, comment
FROM system.columns
WHERE database = ? AND table = ?
```

`system.columns` 是 ClickHouse 原生系统表，信息比 `information_schema.columns` 更完整，推荐优先使用。

### 4.3 依赖引入

```bash
go get github.com/ClickHouse/clickhouse-go/v2
go get gorm.io/driver/clickhouse
```

---

## 五、需求侧分析

### 5.1 用户场景

ClickHouse 在以下场景中是用户的强需求数据源：

- **数据资产盘点**：企业存在大量 ClickHouse 日志表、事件表，需要登记为数据资产
- **数据流通**：ClickHouse 中的分析表作为数据产品对外开放
- **数据目录**：元数据管理平台需要采集 ClickHouse 表结构

相较于 VastBase、GBase8a 等小众国产数据库，ClickHouse 在互联网行业和大数据平台中的用户覆盖面更广，需求优先级不低。

### 5.2 竞品对比

主流数据资产管理平台（如 DataHub、Apache Atlas、OpenMetadata）均已支持 ClickHouse 作为数据源。若本服务不支持，会形成明显的功能缺口。

---

## 六、风险与局限

| 风险项 | 风险等级 | 说明 |
|--------|---------|------|
| `ColumnTypes` 语义差异 | 中 | PRIMARY KEY、UNIQUE、AUTO_INCREMENT 含义不同，需在文档中明确说明，前端展示侧需做适配 |
| GORM 方言兼容性 | 低 | `gorm.io/driver/clickhouse` 不支持迁移（Migrate）功能，但本服务仅做连接/读取，不涉及 DDL，不影响 |
| 批量写入场景 | 低 | 本服务定位为"注册"（元数据管理），不涉及数据写入，无性能隐患 |
| 驱动维护风险 | 低 | `clickhouse-go/v2` 由 ClickHouse Inc. 官方维护，长期可靠 |
| 认证机制 | 低 | ClickHouse 支持用户名/密码认证，与现有参数结构兼容 |

---

## 七、实现工作量评估

| 工作项 | 估时 |
|--------|------|
| 驱动实现（`clickhouse_driver.go`） | 0.5 天 |
| 单元测试 | 0.5 天 |
| proto 枚举更新 + 上层逻辑适配 | 0.5 天 |
| 集成测试（需 ClickHouse 实例） | 0.5 天 |
| **合计** | **约 2 天** |

整体实现成本低，与已有驱动（如 `dameng_driver.go`）的复杂度相当。

---

## 八、结论与建议

**建议支持 ClickHouse 数据源。**

核心理由：

1. **技术可行**：现有 `Datasource` 接口对 ClickHouse 全部适配，驱动生态成熟，实现模式与现有驱动高度一致。
2. **成本极低**：约 2 个工作日，无架构改动，仅新增一个驱动文件。
3. **需求真实**：ClickHouse 在日志分析、实时报表场景下有广泛用户群，主流竞品均已支持。
4. **风险可控**：唯一需注意的是 `PRIMARY KEY`/`UNIQUE`/`AUTO_INCREMENT` 语义差异，可通过注释说明和前端展示适配解决。

**实施建议**：

- `ColumnTypes` 实现优先使用 `system.columns` 系统表，而非 `information_schema.columns`
- `PrimaryKey` 字段建议映射为 ClickHouse 的排序键（`is_in_primary_key`），并在接口文档中注明其含义与 OLTP 数据库的差异
- `GetSchemas()` 返回 `nil`，与 MySQL 驱动保持一致
- 连接超时、TLS 配置复用现有实现模式，无需额外设计

---

*本报告基于 registration-service 当前代码库（`internal/utils/datasource/` 目录）及 ClickHouse 官方文档（截至 2026-03-24）编写。*
