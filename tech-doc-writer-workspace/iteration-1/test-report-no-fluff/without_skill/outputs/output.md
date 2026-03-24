# Kingbase SSL 连接功能测试报告

**日期**：2026-03-24
**测试人员**：yangzhao

---

## 测试环境

| 项目 | 值 |
|------|----|
| 数据库 | Kingbase（人大金仓） |
| 服务器地址 | 192.168.1.49:24321 |
| 用户名 | kingbase2 |
| 数据库名 | test |

---

## 测试范围

验证 Kingbase 数据库的三种 SSL 连接模式是否可正常建立连接并执行查询。

---

## 测试用例

### TC-01：SSL Require（不验证证书）

**描述**：使用 `sslmode=require` 建立加密连接，不对服务端证书进行任何验证。

**配置**：
- SSL 模式：`require`
- 证书：无

**验证操作**：执行 `SELECT 1`

**结果**：✅ 通过

---

### TC-02：SSL Verify CA（验证 CA 证书）

**描述**：使用 `sslmode=verify-ca` 建立连接，通过根证书验证服务端证书由受信任 CA 签发，但不校验主机名。

**配置**：
- SSL 模式：`verify-ca`
- 根证书文件：`root(2).crt`

**验证操作**：执行 `SELECT 1`

**结果**：✅ 通过

---

### TC-03：SSL Full Verification（完整验证）

**描述**：使用 `sslmode=verify-full` 建立连接，同时验证 CA 证书和主机名（SAN 字段）。

**配置**：
- SSL 模式：`verify-full`
- 根证书文件：`root(3).crt`
- 服务端证书 SAN：`DNS:example.com`、`IP:192.168.1.49`

**验证操作**：执行 `SELECT 1`

**结果**：✅ 通过

---

## 测试结果汇总

| 测试用例 | SSL 模式 | 证书 | 结果 |
|----------|----------|------|------|
| TC-01 | require | 无 | ✅ 通过 |
| TC-02 | verify-ca | root(2).crt | ✅ 通过 |
| TC-03 | verify-full | root(3).crt | ✅ 通过 |

3/3 用例通过，0 用例失败。

---

## 结论

Kingbase 数据库的 SSL 连接功能工作正常，三种模式（不验证证书、验证 CA、完整验证）均可成功建立连接并执行查询。服务端证书配置正确，SAN 字段包含必要的 DNS 和 IP 条目，支持 `verify-full` 模式下的主机名校验。
