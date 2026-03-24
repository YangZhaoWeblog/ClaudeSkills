# ClickHouse 数据源支持调研报告

**类型：** 调研报告
**结论：** 建议支持。ClickHouse 是典型的分析型数据库，用户数据资产中存在真实需求；Go 生态有成熟的官方 GORM 驱动可用；接入工作量与达梦驱动相当，核心障碍是元数据查询需要绕过 GORM Migrator（改用 system.columns），以及事务、UPDATE/DELETE 的语义差异需要在文档层面说明限制。

---

## 一、背景：为什么要考虑支持 ClickHouse

registration-service 当前支持 9 种数据源类型（MySQL、TiDB、TDSQL、VastBase、GBase8a、Kingbase、Dameng、LLMHub、Minio）。

ClickHouse 是目前主流的列式分析型数据库，广泛用于日志分析、用户行为分析、实时报表等场景。随着"数据资产登记"业务扩展到 OLAP 场景，用户持有 ClickHouse 数据源的情况会逐渐增多。

本次调研的决策点：**我们是否应该将 ClickHouse 纳入支持的数据源类型，以及接入代价如何？**

---

## 二、ClickHouse 是什么，适合哪些场景

ClickHouse 是列式 OLAP 数据库，核心优势是高吞吐量的分析查询。

与本服务当前支持的数据库的定位对比：

| 维度 | MySQL 系（MySQL/TiDB/TDSQL） | PostgreSQL 系（Kingbase/VastBase） | ClickHouse |
|------|----------------------------|------------------------------------|------------|
| 定位 | OLTP | OLTP | OLAP |
| 典型场景 | 业务库、交易库 | 业务库、国产替代 | 日志、分析、报表 |
| 事务支持 | 完整 ACID | 完整 ACID | 仅限单次 INSERT，实验性多语句事务 |
| UPDATE/DELETE | 标准 SQL | 标准 SQL | 异步 Mutation，代价高 |
| 主键语义 | 唯一约束 | 唯一约束 | 排序键，无唯一约束 |

**本服务对数据源的操作**仅限于：连接测试（Ping）、获取表列表（GetTables）、获取 Schema 列表（GetSchemas）、获取列元数据（ColumnTypes）。这四个操作全部是只读的，ClickHouse 的事务/UPDATE/DELETE 限制对本服务**没有影响**。

---

## 三、Go 驱动与 GORM 支持现状

| 维度 | 情况 |
|------|------|
| 官方 Go 驱动 | ClickHouse/clickhouse-go v2，官方维护，支持 TLS、database/sql 接口（来源：[官方文档](https://clickhouse.com/docs/integrations/go)） |
| GORM Dialector | gorm.io/driver/clickhouse，最新版本 v0.6.x，2025 年 5 月仍有更新（来源：[pkg.go.dev](https://pkg.go.dev/gorm.io/driver/clickhouse)） |
| TLS 支持 | 原生支持，可通过 `clickhouse.Options.TLS` 配置，与其他驱动模式一致 |
| ColumnTypes via GORM Migrator | **不可用**，见下节 |

---

## 四、核心技术障碍：ColumnTypes 必须绕过 GORM Migrator

这是接入 ClickHouse 唯一的非平凡工作量。

**问题：** 现有 MySQL 驱动通过 `db.Migrator().ColumnTypes(tableName)` 获取列元数据；PostgreSQL 驱动通过 `information_schema.columns` + `pg_attribute` 查询。ClickHouse 的 `information_schema` 是部分兼容的视图，`pg_catalog` 不存在。GORM ClickHouse Dialector 的 Migrator 实现的 ColumnTypes 方法签名存在，但其底层依赖的系统表查询路径与 ClickHouse 原生路径不同（待验证：GORM Migrator ColumnTypes 在 ClickHouse 上的实际返回结果是否完整可用）。

**解法：** 直接查询 ClickHouse 原生系统表 `system.columns`：

```sql
SELECT name, type, is_in_primary_key, comment, default_expression
FROM system.columns
WHERE database = ? AND table = ?
```

这与达梦驱动的做法一致：达梦同样无法依赖 GORM Migrator，改为查询 `ALL_TAB_COLUMNS`。工作量属于已知模式，有成熟参考。

**GetTables 和 GetSchemas** 可使用 `system.tables` 和 `system.databases` 查询，或通过 `information_schema.tables` 的兼容接口。

---

## 五、实现方案

按现有 `Datasource` 接口，新增 `ClickhouseDriverSource`，需实现 4 个方法：

| 方法 | 实现路径 | 参考 |
|------|----------|------|
| `Open()` | `gorm.io/driver/clickhouse` + `clickhouse-go/v2` | GORM ClickHouse Dialector |
| `Ping()` | 复用 Open() + db.Ping() | 同 MySQL/Dameng |
| `GetTables(schema)` | `SELECT name FROM system.tables WHERE database = ?` | system.tables |
| `GetSchemas()` | `SELECT name FROM system.databases WHERE name NOT IN ('system', 'information_schema', 'INFORMATION_SCHEMA')` | system.databases |
| `ColumnTypes(schema, table)` | `SELECT name, type, ... FROM system.columns WHERE database = ? AND table = ?` | system.columns |

TLS 配置通过 `clickhouse.Options.TLS` 注入，与现有 TLS 模式（Require/VerifyCa/FullVerification）对齐。

**工作量估算：** 参考达梦驱动约 366 行。ClickHouse 的列类型解析比达梦简单（ClickHouse 类型名称即完整类型描述，如 `UInt64`、`Nullable(String)`），总工作量预估略低于达梦驱动。

---

## 六、结论与推荐方案

**推荐支持 ClickHouse。**

理由：
1. **需求真实**：用户数据资产中存在 ClickHouse 数据源，OLAP 场景是自然扩展方向
2. **接入成本可控**：驱动生态成熟（官方 GORM Dialector 持续维护），实现模式与达梦驱动高度一致，无架构风险
3. **本服务只读操作**：ClickHouse 的事务/写入限制与本服务的使用方式（仅 Ping、元数据查询）完全无关
4. **主要工作量**：`ColumnTypes` 需绕过 GORM Migrator，查询 `system.columns`，这是已知可解的问题

**注意事项（非阻塞，记录即可）：**
- ClickHouse 的"主键"是排序键，无唯一约束，`ColumnTypes` 返回的 `PrimaryKey` 字段含义与其他数据库不同；需在文档或注释中说明
- ClickHouse 没有独立的"schema"概念，database 即 schema，`GetSchemas()` 返回 database 列表；与 MySQL 的行为一致，无需特殊处理
