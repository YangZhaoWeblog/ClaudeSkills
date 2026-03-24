# ClickHouse 数据源支持可行性调研报告

**项目**：注册服务（registration-service）
**调研日期**：2026-03-24
**调研结论**：当前阶段**不建议**将 ClickHouse 纳入支持范围，主要受限于 DML 语义不兼容、GORM driver 维护状况不佳两个核心问题。若业务场景强烈需求，可采用本报告第六节描述的绕行方案，但需承担额外维护成本。

---

## 一、调研背景

注册服务当前支持的数据源类型（见 `internal/utils/datasource/datasource.go`）包括：MySQL、Kingbase、LLMHub、TiDB、TDSQL、VastBase、GBase 8a 和本地文件（MinIO）。业务侧提出是否将 ClickHouse 纳入支持范围，以满足对大规模 OLAP 分析型数据集进行注册、管理的需求。

本报告围绕以下三个核心问题展开分析：

1. ClickHouse 本身的特性与 Go 生态的适配情况；
2. ClickHouse GORM driver 的社区活跃度及工程风险；
3. ClickHouse 的 DML 限制与注册服务现有增删改查接口的兼容性。

---

## 二、ClickHouse 基本特性

ClickHouse 是由 Yandex 开源、目前由 ClickHouse Inc. 维护的列式 OLAP 数据库。其核心设计目标是高吞吐的批量写入和高性能的聚合查询，与注册服务目前支持的 OLTP 数据库在设计哲学上存在根本差异。

### 2.1 架构特点

| 特性 | ClickHouse | MySQL / PostgreSQL |
|---|---|---|
| 存储模型 | 列式存储（MergeTree 系列引擎） | 行式存储 |
| 适用场景 | OLAP：报表、日志分析、时序数据 | OLTP：事务型增删改查 |
| 事务支持 | 不支持完整的 ACID 事务 | 完整支持 |
| UPDATE / DELETE | 不支持标准 SQL，需使用 `ALTER TABLE ... UPDATE/DELETE`（异步执行） | 标准支持 |
| 主键约束 | 无唯一约束，主键仅为排序键 | 严格唯一约束 |
| 并发写入 | 推荐批量写入，不适合高频单行写入 | 支持高频单行写入 |

### 2.2 ClickHouse 中的数据变更操作

这是本次调研最核心的问题。ClickHouse **不支持**标准 SQL 的 `UPDATE` 和 `DELETE` 语句。其变更机制如下：

```sql
-- 标准 SQL（MySQL/PostgreSQL）
UPDATE table SET col = val WHERE id = 1;
DELETE FROM table WHERE id = 1;

-- ClickHouse 等效语法（Mutation）
ALTER TABLE table UPDATE col = val WHERE id = 1;
ALTER TABLE table DELETE WHERE id = 1;
```

**Mutation 的关键特性**：

- **异步执行**：Mutation 操作提交后立即返回，实际的数据变更在后台异步执行，无法立即保证数据一致性。
- **代价高昂**：Mutation 会重写受影响的数据分片（Part），是一个开销极大的操作，不适合频繁执行。
- **无法回滚**：Mutation 一旦提交无法撤销（除非手动终止后清理）。
- **无行级锁**：写入期间读操作不阻塞，但数据可能短暂处于旧版本状态。

ClickHouse 从 23.x 版本开始引入了轻量级的 `DELETE` 语法（Lightweight DELETE），本质是在数据行上打删除标记（而非立即删除），但仍然不保证立即可见的删除语义。

---

## 三、Go 驱动方案分析

### 3.1 clickhouse-go（官方驱动）

- **仓库**：[github.com/ClickHouse/clickhouse-go](https://github.com/ClickHouse/clickhouse-go)
- **维护状态**：由 ClickHouse Inc. 官方维护，v2 版本活跃，支持 `database/sql` 接口和原生协议（TCP）两种模式。
- **特点**：支持批量写入、列式数据传输、压缩等 ClickHouse 特有优化。

clickhouse-go 本身质量良好，是接入 ClickHouse 的首选方案。**问题在于下一层——GORM 集成层**。

### 3.2 GORM ClickHouse Driver 的社区活跃度问题

注册服务的技术规范（CLAUDE.md）明确要求**必须使用 gorm-gen 生成的 Query API**，禁止直接使用原生 GORM，这意味着必须有可用的 GORM Driver 才能接入现有的 DAO 层。

目前已知的 GORM ClickHouse Driver 方案：

| 方案 | 仓库 | 现状 |
|---|---|---|
| gorm.io/driver/clickhouse | [github.com/go-gorm/clickhouse](https://github.com/go-gorm/clickhouse) | 官方 GORM 组织下维护，但 Commit 频率极低，近期少有更新，Issues 有大量未解决问题 |
| uptrace/go-clickhouse | 已归档 | 停止维护 |

**gorm.io/driver/clickhouse 的主要问题**：

1. **Migrator 实现不完整**：注册服务在 `ColumnTypes()` 方法中依赖 `db.Migrator().ColumnTypes(tableName)` 获取表字段信息（参见 `mysql_driver.go:205`），ClickHouse GORM Driver 的 Migrator 对此方法的支持不完整，在列类型映射上存在已知缺陷。
2. **UPDATE/DELETE 语义问题**：GORM 的 `Save()`、`Updates()`、`Delete()` 等方法生成的是标准 SQL，ClickHouse Driver 需要在底层将其转换为 `ALTER TABLE ... UPDATE/DELETE`，这种转换并不可靠，且丢失了 Mutation 的异步性语义——调用方无从感知操作是否真正完成。
3. **事务支持缺失**：GORM 大量使用事务保证操作原子性，而 ClickHouse 不支持事务，Driver 层只能做虚假的事务模拟（no-op），存在数据不一致风险。
4. **gorm-gen 兼容性未验证**：项目使用 gorm-gen（`gorm.io/gen v0.3.27`）自动生成 DAO 代码，gorm-gen 依赖 GORM 的 Schema 解析能力，而 ClickHouse Driver 的 Schema 解析实现有缺口，可能导致生成的代码不可用。

---

## 四、与注册服务现有架构的兼容性分析

### 4.1 `Datasource` 接口层

注册服务为每类数据源定义了统一的接口（`datasource.go:56`）：

```go
type Datasource interface {
    Open() (*gorm.DB, error)
    Ping() error
    ColumnTypes(tableName string) ([]*ColumnType, error)
    GetTables() ([]string, error)
}
```

ClickHouse 实现这个接口在技术上是可行的：
- `Open()`：使用 `gorm.io/driver/clickhouse` 加 `clickhouse-go` 可以建立连接。
- `Ping()`：可通过 `database/sql` 接口实现，无阻碍。
- `GetTables()`：ClickHouse 支持 `SHOW TABLES`，可以实现。
- `ColumnTypes()`：**存在风险**。ClickHouse 的系统表（`system.columns`）结构与 MySQL/PostgreSQL 的 `information_schema` 差异较大，`ColumnType` 结构体中的部分字段（如 `PrimaryKey`、`AutoIncrement`、`Unique`）在 ClickHouse 中无对应语义，必须手动填充占位值，可能误导上层业务。

### 4.2 数据源的增删改查操作

注册服务对外暴露数据源相关的管理接口：`create_data_source`、`update_data_source`、`delete_data_source`，这些接口管理的是注册服务**自身数据库**中的数据源元数据（存储在 MySQL/PostgreSQL），与 ClickHouse 无关。

但当注册服务作为**数据资产的连接器**，需要与 ClickHouse 实例交互（例如测试连接、同步表结构）时，GORM 的 ORM 操作映射到 ClickHouse 就会引发上述问题。

### 4.3 DAO 层代码生成

项目使用 gorm-gen 基于 GORM Model 生成 DAO 代码，生成过程依赖 GORM 连接到目标数据库做反射。**ClickHouse 不能作为 gorm-gen 的代码生成目标**——这一层面不存在问题，因为 gorm-gen 只针对注册服务自身的存储数据库（MySQL/PostgreSQL），而非用户注册的 ClickHouse 数据源。

### 4.4 兼容性矩阵

| 能力点 | 可行性 | 风险等级 | 说明 |
|---|---|---|---|
| 建立连接（Open/Ping） | ✅ 可行 | 低 | clickhouse-go 官方支持 |
| 获取表列表（GetTables） | ✅ 可行 | 低 | `SHOW TABLES` 语法支持 |
| 获取列类型（ColumnTypes） | ⚠️ 有限 | 中 | 部分字段无 ClickHouse 语义对应 |
| 标准 UPDATE/DELETE | ❌ 不支持 | 高 | 需用 Mutation 替代，语义不一致 |
| 事务保证 | ❌ 不支持 | 高 | ClickHouse 无 ACID 事务 |
| gorm-gen 代码生成 | ✅ 无影响 | 无 | 生成针对注册服务自身 DB，与 ClickHouse 无关 |
| GORM Driver 稳定性 | ⚠️ 存疑 | 中-高 | 社区活跃度低，已知 Bug 较多 |

---

## 五、实现成本评估

若决定支持 ClickHouse，需完成以下工作：

### 5.1 必须完成

1. **新增 `clickhouse_driver.go`**：实现 `Datasource` 接口，参考 `mysql_driver.go` 和 `pgsql_driver.go` 的模式。连接建立、Ping、GetTables 部分约 100 行代码，工作量可接受。

2. **定制 `ColumnTypes()` 实现**：不能依赖 GORM Migrator，需要直接查询 `system.columns` 系统表，并做字段映射转换。此部分需要处理 ClickHouse 特有类型（如 `LowCardinality`、`Nullable(T)`、`Array(T)`、`Tuple(...)`），工作量中等，且需要专项测试。

3. **在 `datasource.go` 中注册新类型**：在 `Type` 枚举、`TypeList`、`String()` 方法、`FormatXxx` 常量中各增加一项，约 10 行改动。

4. **在 `list_data_source_type_logic.go` 中注册枚举映射**：增加 ClickHouse 类型 Code 与显示名的映射。

5. **TLS 连接支持**：clickhouse-go 支持 TLS，但配置方式与 MySQL/PostgreSQL 有差异，需参照现有 `tlsConfig()` 模式实现。

### 5.2 难以解决的问题（工程债）

1. **Mutation 异步语义的处理**：若上层调用 `UPDATE`/`DELETE` 类操作（当前注册服务主要用于探索表结构，此类操作较少，但不排除未来扩展），需要在 Driver 层做特殊处理或明确禁止，否则会产生静默的数据不一致。

2. **GORM Driver 的长期维护**：`gorm.io/driver/clickhouse` 的低活跃度意味着版本升级风险——若 GORM 或 clickhouse-go 升级后 Driver 不跟进适配，可能造成项目阻断。这是一个长期的维护成本。

3. **ColumnType 语义失真**：ClickHouse 中不存在 `AutoIncrement`、`Unique` 约束的概念，`ColumnType` 结构体中这些字段将始终为零值，若上层业务依赖这些信息做决策，会产生误判。

**综合估算**：
- 初期实现（仅连接和表结构探索）：2～3 个工作日
- 完整可靠实现（含异常处理、TLS、类型映射完善）：1～2 周
- 长期维护风险：高

---

## 六、绕行方案

若业务确实需要支持 ClickHouse 场景，可考虑以下折中方案，规避 GORM Driver 的风险：

### 方案 A：绕过 GORM，直接使用 `clickhouse-go` 原生接口

放弃对 ClickHouse 使用 GORM，在 `clickhouse_driver.go` 中通过 `database/sql` 或 clickhouse-go 原生接口实现 `Datasource` 接口，`Open()` 方法返回的 `*gorm.DB` 可以通过 `gorm.Open(clickhouseDialector)` 仅用于维持接口签名，实际的 `ColumnTypes()`、`GetTables()` 等操作绕过 GORM 直接执行原生 SQL。

**优点**：不依赖不稳定的 GORM Driver；
**缺点**：打破了 `Datasource` 接口返回 `*gorm.DB` 的约定，`Open()` 的返回值在 ClickHouse 场景下意义受限，容易误用。

### 方案 B：将 ClickHouse 定位为只读数据源

在业务层约定 ClickHouse 类型的数据源**仅支持只读操作**（连接测试、表结构探索），在 Driver 层对 `Save()`、`Updates()`、`Delete()` 等写操作返回明确错误，避免静默的数据不一致问题。

**优点**：与 ClickHouse 的 OLAP 定位吻合，适配当前注册服务"元数据注册"的核心场景；
**缺点**：需要在接口层添加能力声明或限制，对框架有一定侵入。

### 方案 C：等待 GORM ClickHouse Driver 成熟

观望 `gorm.io/driver/clickhouse` 的维护状态，等待其完整实现 Migrator 和解决已知 Bug 后再接入。从当前 commit 频率来看，短期内（6 个月内）不太可能有显著改善。

---

## 七、结论与建议

### 结论

| 维度 | 评估 |
|---|---|
| 技术可行性 | 有限可行（仅只读场景） |
| 工程稳定性 | 较差（GORM Driver 活跃度低） |
| DML 兼容性 | 不兼容（UPDATE/DELETE 语义根本差异） |
| 实现成本 | 中等（初期2～3天，长期维护成本高） |
| 整体建议 | 当前阶段不建议引入 |

### 建议

1. **短期（当前版本）**：不引入 ClickHouse 支持。ClickHouse 的 Mutation 异步语义与注册服务的数据一致性要求存在根本冲突，GORM Driver 的低维护活跃度也带来不可控的工程风险。

2. **若业务优先级较高**：采用**方案 B（只读数据源）**，明确将 ClickHouse 定位为仅支持连接测试和表结构元数据探索的只读数据源，规避 DML 不兼容问题，并在 Driver 层使用 clickhouse-go 原生接口实现 `ColumnTypes()` 和 `GetTables()`，不依赖 GORM Migrator。

3. **长期**：持续跟踪 `gorm.io/driver/clickhouse` 的维护状态，以及 ClickHouse 官方对标准 SQL DML 支持的改进进展（如 Lightweight DELETE 的进一步完善），在条件成熟时重新评估。

---

## 附录：参考资料

- ClickHouse 官方文档 - ALTER TABLE UPDATE/DELETE: https://clickhouse.com/docs/en/sql-reference/statements/alter/update
- ClickHouse 官方文档 - Lightweight DELETE: https://clickhouse.com/docs/en/sql-reference/statements/delete
- clickhouse-go 官方仓库: https://github.com/ClickHouse/clickhouse-go
- gorm.io/driver/clickhouse: https://github.com/go-gorm/clickhouse
- 注册服务现有数据源接口: `internal/utils/datasource/datasource.go`
- 注册服务 MySQL Driver 实现参考: `internal/utils/datasource/mysql_driver.go`
