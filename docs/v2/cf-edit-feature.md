# CloudFile V2 — 普通编辑始终可用，Checkout 默认启用

> 2026-10-17 配置语义收敛：**Checkout 是安装能力，不是普通编辑总开关。** 本次不部署生产；既有数据不做静默破坏性迁移。

## 两种编辑及唯一一张 Guard 表

| 能力 | 不支持 Checkout 的兼容实例 | 安装了 Guard 的 V2 实例 |
| --- | --- | --- |
| Seafile 原生 Web 上传/下载 | 始终支持 | 始终支持 |
| Rust Agent2 普通本地编辑 | 允许；原生 File ID 乐观条件提交 | 允许；原生 File ID 条件提交且最终检查有效 Guard |
| Rust Agent2 独占 Checkout / Commit / Checkin | 不支持，返回 `CHECKOUT_UNSUPPORTED` | **默认支持** |
| 文件读取 / 列表 | 不依赖 Guard | 不依赖 Guard |
| 普通编辑锁或服务器 Intent | **无** | **无** |
| 独占数据 | 无额外编辑表 | 单张 `cf_edit_guard` |
| 断线后恢复 | Rust 本地 Journal + Seafile File/Commit | Rust Journal + 原生版本 + Guard |

Checkout 本身是独占机制，但普通编辑**不申请锁、不续租、不创建 Guard 行**。普通编辑的版本冲突保守拒绝，保留本地副本，不覆盖他人的更新。独占中的文件不能由普通保存、原生 Web/Sync 或删除/改名绕过 Guard。

## Checkout 能力如何自动识别（无启用参数）

**CloudFile V2 不再提供 Checkout 功能开关。**

- 全新 V2 始终安装三张已批准核心扩展表和独立 `cf_edit_guard` 表；Hub/C/Go 依数据库实际结构识别能力并强制执行 Guard。
- 已有实例无 Guard 表：仍可进行原生文件读写和普通乐观编辑；不自动新增表，独占请求明确返回 `CHECKOUT_UNSUPPORTED`。
- 已有实例存在 Guard：必须按经过校验的结构执行围栏；结构异常或查询失败不能解释为“Checkout 关闭”，必须拒绝不安全的写入。
- 移除 `CF_V2_CHECKOUT_ENABLED`、`CF_V2_AGENT_EDIT_ENABLED`、`[cloudfile] v2_edit_enabled` 作为产品配置的语义。遗留配置不再用于放行或拒绝；升级后的受控运行环境应清理其残留。
- Guard 的安装/退出属于受控 Schema 迁移，需要重启原生进程和 Hub，绝不是配置开关操作。已有 Checkout 必须经过 Checkin/Release 和数据核对，不允许绕过活动锁。

## 既有环境和部署人员

- 全新 V2 默认支持；**不需要**系统管理员每次启动时点“启用 Checkout”，也无用户级开关。
- 复用的 CE14/V2 数据目录若已经包含 **结构经过完整校验**的单表 `cf_edit_guard`，自动启用原生 Guard 保护；无论旧配置值是什么都不能绕过。
- 复用数据目录没有 Guard：维持普通编辑，不自动新增表。独占请求返回 `CHECKOUT_UNSUPPORTED`；需由部署管理员完成受控的一次性单表迁移，再重启 Hub/C/Go。
- 若已有 Guard 结构不匹配，启动拒绝，而不是带着无法执行的锁机制继续服务。
- Docker `build/v2/start-dev.py` 只改动复用目录**临时运行配置**，不会覆盖旧 CE14 的原始 `seafile.conf`、删除文件或升级原生版本。

## 最小 API

- Hub `POST /api/v2.1/cloudfile/edit/v1/open/`：浏览器当前用户签发短期文件授权；普通模式始终可以申请，独占模式只在能力存在时申请。
- Hub `GET /api/v2.1/cloudfile/edit/v1/lock-info/`：返回 Checkout 支持能力和当前占用；终端/IP 仅向持有人或管理员展示。
- Go Fileserver `/cf-edit/v1/read|status|publish`：普通编辑不要求 Guard 表；独占发布仍须 Guard 证明。
- Go `/cf-edit/v1/checkout|renew|release`：仅安装 Guard 的实例提供；Checkout 原子写入 + 当前用户及文件权限校验。
- 所有最终原生 Branch 写入：安装 Guard 时仍执行 Guard 围栏；独占 Commit/Checkin 与 Guard 基线/释放处于同一个数据库事务。

## DEV 验收建议

1. 不配置任何 Checkout 开关，新装 V2 自动安装四张扩展表；普通/独占入口及 C/Go 围栏一致。
2. 复用旧 CE14 且无 Guard：普通编辑可用、独占返回 `CHECKOUT_UNSUPPORTED`，不会因开关缺失触发迁移。
3. 已安装 Guard 即使残留旧 `enabled=false` 参数，也不得绕过任何原生写入检查。
4. Guard 表存在但结构损坏、权限不足或数据库暂时故障时拒绝不安全写入，不将异常当作 Guard 缺失。
5. 两用户冲突、Checkout 阻断 Web/Sync/原生变更、多次 Commit/Checkin、权限撤销及 Rust Journal 恢复均进行隔离 DEV 联验。
6. 所有源代码/配置变更均不直接发布 PROD，不静默改动旧数据。


只有 `cf_edit_guard` 为本功能扩展状态；**不重新引入服务器 Intent、设备账户、编辑 Session 或历史锁表。**
