# CF-EDIT V2 — 单 Guard / Rust Agent2 人工 DEV 验收

> **2026-10-17 合并口径：代码可进入 V2 `dev`，功能默认关闭；真实 Agent2 文件操作人工验证前不得对共用实例或生产启用。**

## 收敛的状态模型

- **Seafile CE14 原生**：File/Block/Commit/Branch、版本与现有身份/ACL 是唯一文件事实。
- **`cf_edit_guard`**：唯一可选扩展表，只记录当前 Checkout，路径槽位的 `generation` 单调增加；持有人、原生用户名、终端类型/名称、受信来源 IP、租约与基线 File ID 可查询。
- **Rust Agent2 本地 Journal**：冻结 Snapshot、待处理的原始操作与不确定 HTTP 结果；不建设服务器 `cf_commit_intent`、Device、Session 或额外历史流水表。
- **普通编辑**：不生成 Guard、不保存服务端 Intent；最终原生提交比较原 File ID 并检查当时有效的 Checkout。
- **独占编辑**：Checkout → 多次 Commit → Checkin/Release；Guard 基线或释放与原生 Branch 发布在同一 InnoDB 事务，陈旧凭据拒绝；网络不明时保留本地文件、保守核对，不保证历史 Exactly Once。
- **外部 PLM API、CDC 新集成**：不属于当前验收和合并门槛。

## 默认关闭和部署边界

标准 V2 启动只安装三张原有 `cf_` 扩展表。可选 `scripts/sql/mysql/cloudfile-v2-edit.sql` **只定义一张 `cf_edit_guard`**，不会作为普通安装执行。

`build/v2/start-dev.py` 仅在 **新建、隔离、可丢弃的 DEV 实例** 中设置环境变量 `CF_V2_AGENT_EDIT_ENABLED=true` 时安装 Guard，并设置两端 `[cloudfile] v2_edit_enabled=true` 与 Hub 的 `CF_V2_AGENT_EDIT_ENABLED`。该开关默认为 false；对已识别的旧版 CE14 数据目录开启会明确拒绝。既有数据/两表部署不允许直接导入单表 DDL；不执行自动破坏性迁移。

**合并代码不会自动执行任何部署、创建 Guard、开启服务端开关或更新 PROD。**

## HTTP / Native 对接

| 入口 | 方法与契约 | 权限边界 |
| --- | --- | --- |
| Hub `api/v2.1/cloudfile/edit/v1/open/` | `POST` `{repo_id,path,mode}` → `open_uri` | 当前浏览器 Session + CSRF；不接受客户端提交的用户名 |
| Hub `api/v2.1/cloudfile/edit/v1/lock-info/` | `GET` `repo_id,path` → 当前 Checkout 状态 | 文件读取权限；终端/IP 只向持有人或管理员显示 |
| Fileserver `cf-edit/v1/read` | `GET` 使用浏览器短期签发的单文件 Bearer | 校验 native File ID 与当前 ACL |
| Fileserver `cf-edit/v1/checkout` | `POST` 用当前 File ID 获取 Guard | Branch 锁 + Guard 行；单文件独占 |
| Fileserver `cf-edit/v1/publish` | `POST` Full 文件字节，`optimistic/commit/checkin` | 当前用户/ACL、File ID、Guard/版本 + 原生事务 |
| Fileserver `cf-edit/v1/status` | `GET` 当前原生 File ID、内容摘要与 Guard 状态 | 仅是当前事实；不是历史回执 |
| Fileserver `cf-edit/v1/renew` / `release` | `POST` Guard 凭据 | 原持有人 + 完整 Guard proof；失效租约只能经安全恢复 |

Fileserver 经现有同源 **`/seafhttp/`**（或 **`/cfhttp/`**）代理访问。带 `SITE_ROOT` 的 Hub 部署使用对应前缀，不可以绕过当前的 Nginx/CSRF/ACL。Rust Agent 使用 `cloudfile-open://v2/open` 交付；旧 `local-edit/v1` 协议仍保留于旧任务的兼容代码，不作为 V2 必需服务。

浏览器授权时效约 1 小时，不能把 Agent 视为具有永久用户身份。长时间独占时从已登录网页再次打开相同文件，Rust 会尝试用新授权重新验证并续租原 Guard，不覆盖既有工作副本。客户端将到期提示显示在任务中心；离线或令牌过期时应保存本地工作副本。

## 人工 DEV 验收顺序

1. 从合并后的三仓 `dev` 的 **实际 SHA** 更新 `build/v2/source-set.json` 和 CI 固定检出脚本；运行 `CloudFile V2 clean CE14 isolated checks` 确认 C/Go 编译、RPC 文件字节和默认三表。
2. 在全新、隔离 DEV 数据目录和专用数据库上显式启用 `CF_V2_AGENT_EDIT_ENABLED=true`。核对表结构是原三表 + **只有一张 Guard**，确认普通启动默认未开启。
3. 在网页完成真实登录，使用文件的真实 `repo_id,path` 调 `edit/v1/open/`，将返回的 `open_uri` 交给 Rust Agent2/Chrome Native Messaging；验证下载原内容、操作系统默认应用打开，以及本地工作副本可恢复。
4. **普通编辑**：保存 → 观察约 3 秒自动回传 → 检查原生 File ID 与真实下载字节；同时让第二用户改同一文件，后保存必须返回冲突，保留本地变更，Guard 表不新增普通编辑记录。
5. **独占编辑**：Checkout → 查询显示持有人/终端/IP/时间 → Commit 多次（Guard 不释放）→ Checkin（Branch 与 Guard 原子成功）→ 再次由他人编辑。验证网页/同步器/移动、删除文件及父级目录都不能绕过有效 Guard。
6. **恢复和权限**：断网、HTTP 已提交但响应丢失、进程重启、超过一小时浏览器重授权、Guard 自然过期、权限被撤销、Checkout 争用；结果不确定时禁止盲目覆盖或删本地快照。所有授权失败必须拒绝写入。
7. 验收完关闭专用 DEV 开关。只有全套真实结果和浏览器/Agent 日志通过后，才讨论共用 DEV 启用或生产发布。

## 当前自动测试的证明范围

- Server `CF-EDIT single-Guard MariaDB`：真实 MariaDB 表结构、Guard/Branch 原子事务回滚与索引；不能代表用户文件内容的完整 E2E。
- Docker `CloudFile V2 clean CE14 isolated checks`：固定 CE14 C + Go 构建、原生文件上传/下载/RPC 和默认三表；**未执行开启 Guard 后的完整 Rust 编辑 E2E**。
- Rust Agent2 `Rust Agent CI`：Windows、macOS Intel、Apple Silicon 完整构建和客户端测试；**不能替代真实网页登录、反向代理、Guard 发布的人工验收**。

> 对齐失败、缺少当前凭据或疑似覆盖风险时，应保持 `v2_edit_enabled=false` 并保留本地 Journal；不进行生产发布。
