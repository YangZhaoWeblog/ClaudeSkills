# ClickHouse 数据源支持调研报告

**文档类型：** 调研报告
**读者：** 负责注册服务的技术 leader
**决策点：** 是否将 ClickHouse 纳入注册服务支持的数据源类型

---

**根因：** 业务侧有通过注册服务管理 ClickHouse 数据资产的需求，需评估其技术可行性与集成成本。

**结论：当前不建议支持 ClickHouse。** 核心障碍是 ClickHouse 不支持标准 UPDATE/DELETE，这与注册服务现有的数据源元数据增删改查接口语义直接冲突，且无低成本的解决方案。如果仅需只读（连通性校验、表结构探查）场景，技术上可行，但需限制接口语义并单独维护一套驱动，工程收益与维护成本需权衡。

---

## 一、背景与根因

> 本节回答：为什么要调研这个问题？

注册服务当前支持的数据源类型（来源：`datasource.TypeList`）为：

```
Mysql / Kingbase / LLMHub / TiDB / TDSQL / VastBase / GBase8a / LocalFile
```

所有关系型数据源统一实现 `Datasource` 接口（`Open / Ping / ColumnTypes / GetTables`），通过 GORM 进行元数据读取。业务侧希望将 ClickHouse 纳入支持，以便管理列存 OLAP 数据资产。

ClickHouse 的核心设计目标是高吞吐分析查询，其 SQL 方言与事务型数据库存在显著差异，这是本次调研的核心技术风险点。

---

## 二、ClickHouse 与现有接口的兼容性分析

> 本节回答：ClickHouse 的技术特性是否与注册服务现有接口语义兼容？

### 2.1 Datasource 接口需求映射

| 接口方法 | 用途 | ClickHouse 支持情况 |
|---------|------|-------------------|
| `Open()` | 建立连接，返回 `*gorm.DB` | ⚠️ 需通过 GORM ClickHouse driver 或 database/sql 桥接 |
| `Ping()` | 连通性检测 | ✅ 支持（SELECT 1 即可） |
| `GetTables()` | 获取表列表 | ✅ 支持（查询 `system.tables`） |
| `ColumnTypes()` | 获取列类型信息 | ✅ 支持（查询 `system.columns`） |

仅看 `Datasource` 接口本身，ClickHouse **只读场景完全可行**。

### 2.2 UPDATE / DELETE 兼容性问题

注册服务的数据源记录本身存储在 MySQL/PostgreSQL（注册服务自身数据库），不涉及对 ClickHouse 执行 DML。然而，**若注册服务将来需要对 ClickHouse 中的数据资产执行元数据写入操作**（如写入数据资产标签、更新数据资源状态到 ClickHouse 中），则面临如下限制：

| 操作 | 标准 SQL | ClickHouse 的替代写法 | 兼容性 |
|------|---------|---------------------|-------|
| INSERT | `INSERT INTO t VALUES (...)` | 相同 | ✅ 兼容 |
| UPDATE | `UPDATE t SET ...` | `ALTER TABLE t UPDATE col=val WHERE ...` | ❌ GORM 不支持，需裸 SQL |
| DELETE | `DELETE FROM t` | `ALTER TABLE t DELETE WHERE ...` | ❌ GORM 不支持，需裸 SQL |
| 事务 | `BEGIN / COMMIT` | 不支持跨行事务 | ❌ 完全不兼容 |

来源：ClickHouse 官方文档 [Mutations](https://clickhouse.com/docs/en/sql-reference/statements/alter#mutations)（待结合实测验证）。

**当前结论：** 注册服务对 ClickHouse 只做"连通校验 + 表结构读取"，不执行 DML，因此 UPDATE/DELETE 问题**不直接阻塞**当前 `Datasource` 接口的实现。但若将来业务扩展为向 ClickHouse 写数据，该限制将成为硬性障碍。

---

## 三、驱动选型对比

> 本节回答：接入 ClickHouse 应该选哪个 Go 驱动？

当前注册服务全部使用 GORM，驱动选型应优先考虑与 GORM 的兼容程度。

| 维度 | clickhouse-go（官方） | gorm-clickhouse（社区） | database/sql 直接使用 |
|-----|--------------------|----------------------|-------------------|
| 官方维护 | ✅ ClickHouse 官方 | ❌ 第三方社区 | — |
| GORM 适配 | ❌ 需桥接 | ✅ 原生支持 `gorm.Open` | ❌ 需手动封装 |
| Migrator 支持 | ❌ 无（`GetTables`/`ColumnTypes` 需手写 SQL） | ⚠️ 部分支持，实现不完整 | ❌ 无 |
| 社区活跃度 | ✅ 高（官方驱动） | ⚠️ 一般（issue 响应慢） | — |
| TLS 支持 | ✅ 支持 | ✅ 继承底层驱动 | ✅ 支持 |
| 与项目现有架构匹配度 | ⚠️ 中（需适配层） | ⚠️ 中（活跃度风险） | ❌ 低 |

来源：[clickhouse-go GitHub](https://github.com/ClickHouse/clickhouse-go)，[gorm-clickhouse GitHub](https://github.com/go-gorm/clickhouse)，现状评估为"待验证"（未对 gorm-clickhouse 做完整功能测试）。

**推荐驱动：clickhouse-go（官方驱动）+ 手动实现 `ColumnTypes`/`GetTables`。** 理由：官方驱动稳定性和长期维护有保障；gorm-clickhouse 社区活跃度低，Migrator 实现不完整，引入后维护风险高。代价是需要绕过 GORM Migrator，用 `system.columns` / `system.tables` 手写元数据查询 SQL，与现有 MySQL/PgSQL driver 实现方式不同，但工程上完全可行。

---

## 四、工程改造范围评估

> 本节回答：接入 ClickHouse 需要改哪些地方，工程量多大？

### 必须改动的位置

| 文件/模块 | 改动内容 |
|----------|---------|
| `internal/utils/datasource/datasource.go` | 新增 `ClickHouse Type` 常量，加入 `TypeList` |
| `internal/utils/datasource/clickhouse_driver.go`（新建） | 实现 `Datasource` 接口，手写 `GetTables`/`ColumnTypes`（查询 `system.*` 表），不依赖 GORM Migrator |
| `internal/helper/datasource.go` → `BuildDatasource()` | 新增 ClickHouse 分支 |
| `internal/utils/datasource/datasource.go` → `String()` | 新增 ClickHouse format 常量及 case |
| `go.mod` | 新增 `github.com/ClickHouse/clickhouse-go/v2` 依赖 |

### 连锁影响排查

- **`DeriveResourceFormat`（`internal/logic/create_resource_logic.go`）**：需确认 ClickHouse 对应的 resource format 是否复用 `FormatMySQL` 或新增，待业务确认。
- **ValidateDsnParamKeys**：ClickHouse DSN 参数白名单需单独定义（如 `compress`、`dial_timeout` 等）。
- **UPDATE/DELETE 路径**：当前注册服务不对被接入的数据源执行写操作，风险可控；但需在接口文档和代码注释中明确声明 ClickHouse 仅支持只读操作。

**改动量：** 约 1 个新文件（150–200 行），3–4 处已有文件的小改动。工程量可控。

---

## 五、风险与局限

> 本节回答：接入后有哪些持续风险？

| 风险 | 等级 | 说明 |
|-----|------|------|
| UPDATE/DELETE 语义缺失 | 高 | 若未来业务需要向 ClickHouse 写入或更新数据，必须绕过 GORM，改造成本高 |
| GORM Migrator 不可用 | 中 | `ColumnTypes`/`GetTables` 无法复用现有 GORM 工具链，需维护独立实现 |
| ClickHouse 列类型体系差异 | 中 | 类型映射（如 `UInt64`、`Array(String)`、`LowCardinality`）与 MySQL/PgSQL 差异大，`ColumnType` 结构体映射需仔细处理 |
| 事务不支持 | 低（当前） | 当前注册服务不对 ClickHouse 开事务，暂不影响 |
| gorm-clickhouse 社区风险 | 低（若选官方驱动则规避） | 选 clickhouse-go 官方驱动可绕过此风险 |

---

## 六、结论与推荐方案

> 本节回答：最终建议是什么？

### 场景一：仅需连通校验 + 表结构探查（只读）

**可以支持，建议有条件推进。**

- 使用 clickhouse-go 官方驱动，手动实现 `GetTables`（查询 `system.tables`）和 `ColumnTypes`（查询 `system.columns`），不依赖 GORM Migrator。
- 在接口层和代码注释中明确标注：ClickHouse 数据源仅支持连通性检测与元数据读取，不支持写操作。
- 改动范围可控，新增约 1 个驱动文件 + 少量现有文件修改。

### 场景二：需要对 ClickHouse 执行写入或更新操作

**暂不建议支持。**

ClickHouse 的 mutation 语义（`ALTER TABLE ... UPDATE/DELETE`）与 GORM 不兼容，且为异步执行，与注册服务现有的同步增删改查接口语义根本冲突。强行支持需要绕过整个 GORM 层，形成特例代码，长期维护成本高。

### 决策建议

优先确认业务需求属于哪个场景。若当前需求仅为"注册 ClickHouse 数据源、查看其表结构"，按场景一推进；若需要写回数据到 ClickHouse，建议推迟支持，待有明确业务量再评估专项改造。
