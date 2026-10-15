# 设备本地编辑上传协议

状态：开发实现，默认关闭；真实部署验收前不开放产品能力。

Agent 手工捕获不可变快照，沿用原 CommitIntent。设备签名通过后，Hub 签发
60 秒内可开始上传的加密短期凭据（AES-256-GCM，专用派生密钥）。凭据只通过
Authorization 传送，不写 URL，不使用 Cookie；绑定会话、设备版本、资源、
原 Intent、基线、摘要、大小和操作。不同 worker 可使用同一配置密钥验证。

字节入口为同源 `/api/v2.1/cloudfile/extensions/local-edit/v1/agent/commit-upload/`，
复用现有 Hub httptemp 与原生 publish_edit RPC，避免新增 fileserver 授权体系。
最多 128 MiB；原始字节、准确 Content-Length、Idempotency-Key=Intent。
开始接收前验证凭据；流式写入私有临时文件并核验摘要/长度，再调用原生发布。
上传可能超过凭据启动期限；最终原生事务仍重复当前权限、设备、会话、Checkout
有效期和原文件版本校验。凭据不是离线发布授权。

原生事务仅允许 editing + local_commit 的设备写入条件；读用 local_session
永远不能作为写入条件。local_commit 使用服务端生成的设备/会话版本引用，
并校验 exclusive-edit 的真实 guard。提交结果、guard 基线和会话基线在同一
Branch 事务推进；Checkin 同事务结束会话并释放 guard。

仅 cf_commit_intent 中 published 的持久回执可显示成功。超时/丢失响应后，
Agent 用新设备签名查询原 Intent，不能以重新创建 Intent 来重试。查询不返回
路径、凭据或文件字节，允许完成/过期会话查询自己的历史回执；撤销设备拒绝查询。

验收用例：正常 Commit/Checkin、工作文件再修改不影响捕获快照、摘要/大小错误、
跨 Intent 凭据、过期凭据、设备撤销、会话取消、Checkout 过期/替换、版本冲突、
重复请求、发布后响应丢失、同资源其他会话不能读取 Intent。


## Device Agent Runtime Configuration

Ordinary Agent uploads use `CLOUDFILE_LOCAL_EDIT_ENABLED=true` and
`CLOUDFILE_AGENT2_OPTIMISTIC_UPLOAD_ENABLED=true`. They do not require enabling
exclusive Checkout. The defaults remain false.

A complete deployment also requires the native OIDC login host, a validated
`CLOUDFILE_OIDC_CONFIG_JSON`, `CLOUDFILE_POLICY_CONFIG_JSON`,
`CLOUDFILE_POLICY_WORKER_HOOKS=true`, and a stable `CLOUDFILE_RESOURCE_SECRET`
of at least 32 bytes. Set `CLOUDFILE_LOCAL_EDIT_INSTANCE` to the browser's
canonical HTTP/HTTPS origin, without `SITE_ROOT`. It must match the OIDC callback
origin. The renderer supplies the native lifecycle and version adapters.
These variables are passed to both app and worker services by Compose.

Before enabling the routes, complete the applicable schema migrations and
validate `cloudfile_extensions.schema check`. Do not enable flags over an old
ledger or substitute manually created tables for verified migrations. Native
OIDC requires disabling the legacy OAuth callback in that deployment; register
the native callback path at the IdP before switching login. Preserve a working
rollback configuration and validate upgrades in an isolated database first.

`local.open-edit` is advertised only by a current, non-draining worker with the
native login, policy, resource, device, session and read-ticket adapters assembled.
A requested capability in settings cannot manufacture runtime readiness.
This capability does not itself prove external IdP acceptance or a successful
file publication; those remain deployment acceptance checks.

## 管理员发布与本地编辑并用

管理员策略管理默认启用，复用已配置的 CloudFile/MySQL 连接与 Seahub 系统管理员
Token；管理员无需额外配置 OIDC、Redis、策略 JSON、worker hooks 或资源密钥。
每次请求使用独立数据库事务并检查 schema，目录共享生命周期通过原生 RPC 核验。
已显式启用 `CLOUDFILE_AUTHORIZATION_ENABLED` 的部署继续由用户授权通道持有路由，
不会重复挂载；管理员通道不自动开启用户授权或修改现有登录方式。
普通用户和资料库管理员 Token 不能取得系统管理员发布权限。

发布写入统一 `cf_dir_acl`，复用事务锁、共享生命周期、If-Match、原请求重试记录
及审计。原生管理员按 `native-account:` 服务主体记录，不伪造业务用户会话或目录
快照。账号停用、降权、库删除、虚拟库或正在迁移的库均拒绝请求；目录共享撤回
只撤回共享模式，保留已授权的库成员 ACL。该开关不开放普通用户的策略会话接口。
