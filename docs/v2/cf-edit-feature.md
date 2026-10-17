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

## 开关究竟控制什么

**产品默认无需手动开启。**

- 全新 CloudFile V2：默认安装 3 张原有扩展表 **+ 1 张 `cf_edit_guard`**，C/Go 原生写入围栏自动启用，Hub 提供 Checkout 操作和查询。
- 仅当全新实例明确不支持 Checkout 时，部署管理员在部署环境设置 `CF_V2_CHECKOUT_ENABLED=false`，只安装原有 3 表。普通编辑仍可以使用 Rust Agent 的乐观提交。
- 为兼容已有配置，旧环境变量 `CF_V2_AGENT_EDIT_ENABLED` 暂作为同义配置读取；与新变量值冲突时启动报错。**首选只配置 `CF_V2_CHECKOUT_ENABLED`，不要同时配置两个。**
- 底层旧键 `[cloudfile] v2_edit_enabled` 不再代表“编辑总开关”，而是**当前运行实例已安装 Guard 且必须执行原生独占围栏**。禁止把它当普通编辑控制项交给用户/前端切换。
- Hub 内部 `CF_V2_AGENT_EDIT_ENABLED` 同样仅用于是否支持 **Checkout**，普通本地编辑授权不再检查此项。

**禁止在存在 Guard 表的已支持实例通过设置 false 绕过锁保护**：部署器对此明确拒绝。已存在的 Checkout 应按正常 Checkin/Release 结束；需要永久退出该能力必须经过独立的管理员迁移和数据核对，不允许把活跃锁直接忽略。

## 既有环境和部署人员

- 全新 V2 默认支持；**不需要**系统管理员每次启动时点“启用 Checkout”，也无用户级开关。
- 复用的 CE14/V2 数据目录若已经包含 **结构经过完整校验**的单表 `cf_edit_guard`，自动启用原生 Guard 保护；即使曾有旧参数，也不能通过 false 跳过。
- 复用数据目录没有 Guard：维持普通编辑，不自动新增表。请求显式开启 Checkout 将报出缺少 Guard 的诊断信息；需先由部署管理员完成受控的一次性单表迁移，再重启。
- 若已有 Guard 结构不匹配，启动拒绝，而不是带着无法执行的锁机制继续服务。
- Docker `build/v2/start-dev.py` 只改动复用目录**临时运行配置**，不会覆盖旧 CE14 的原始 `seafile.conf`、删除文件或升级原生版本。

## 最小 API

- Hub `POST /api/v2.1/cloudfile/edit/v1/open/`：浏览器当前用户签发短期文件授权；普通模式始终可以申请，独占模式只在能力存在时申请。
- Hub `GET /api/v2.1/cloudfile/edit/v1/lock-info/`：返回 Checkout 支持能力和当前占用；终端/IP 仅向持有人或管理员展示。
- Go Fileserver `/cf-edit/v1/read|status|publish`：普通编辑不要求 Guard 表；独占发布仍须 Guard 证明。
- Go `/cf-edit/v1/checkout|renew|release`：仅安装 Guard 的实例提供；Checkout 原子写入 + 当前用户及文件权限校验。
- 所有最终原生 Branch 写入：安装 Guard 时仍执行 Guard 围栏；独占 Commit/Checkin 与 Guard 基线/释放处于同一个数据库事务。

## DEV 验收建议

1. 验证未传任何 Checkout 环境变量时，**全新 V2 安装四张扩展表**、普通/独占入口均可用。
2. 全新 V2 设置 `CF_V2_CHECKOUT_ENABLED=false`：安装三张表，普通编辑仍可保存，独占返回 `CHECKOUT_UNSUPPORTED`；Web/原生读写不受影响。
3. 复用 V2 且已有 Guard：即使环境变量被设为 false 也应拒绝启动，不得关闭围栏。
4. 实测两用户编辑同一文件的版本冲突、有效 Checkout 阻断原生写入、多个 Commit/Checkin 和浏览器重新授权。
5. 测试网络异常、权限撤销、状态不明时 Rust Journal 保留文件，禁止覆盖。
6. 所有功能验收先在隔离 DEV 进行；不自动发布 PROD。

只有 `cf_edit_guard` 为本功能扩展状态；**不重新引入服务器 Intent、设备账户、编辑 Session 或历史锁表。**
