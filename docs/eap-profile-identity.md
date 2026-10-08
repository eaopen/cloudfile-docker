# EAP、Authentik 与 CloudFile 身份契约

采用原生 Profile，不新增 `cf_eap_user_binding`。EAP UID 为业务权限主体，
Authentik 继续接受工号与密码；OIDC 的稳定 `sub` 不替换为工号或 UID。

| 字段 | 用途 |
|---|---|
| `sub` | 现有 provider 内稳定的 OIDC 身份，保留原绑定 |
| `userId` | 字符串 EAP UID；ID Token、userinfo 与 EAP 必须一致 |
| `preferred_username` | EAP 工号；仅命名新账号 |
| `Profile.login_id` | EAP UID |
| `Profile.user` | 新账号为 `工号@auth.local`；已有账号保持原值 |
| `email` | 可选联系信息；共享邮箱不合并身份 |

## 配置与上线顺序

`CF_SSO_EAP_PROFILE_IDENTITY=false` 默认关闭。先在 Authentik DEV 配置
可信 EAP 目录解析得到的 `userId`，并同时输出到 ID Token 和 userinfo；
不能由用户自行编辑属性指定 UID。EAP 的 DEV 登录兑换校验 UID 与本地用户相同。

CloudFile 配置 `CF_SSO_OAUTH_UID_CLAIM=sub`、
`CF_SSO_OAUTH_LOGIN_ID_CLAIM=userId`、scope 含 `openid`，并填写该 provider
准确的 `CF_SSO_EAP_OIDC_ISSUER` 和 `CF_SSO_EAP_OIDC_JWKS_URL` 后，才启用
`CF_SSO_EAP_PROFILE_IDENTITY=true`。app 与 worker 使用相同配置。
现有 provider 名称、client ID、sub 模式应保留，避免产生另一套身份。

回调使用一次性 state、nonce、S256 PKCE，并验证 RS256 签名、issuer、audience、
过期时间和 userinfo 的 sub/UID。随后从受认证的 EAP 目录核对 UID、工号及有效状态，
Profile 提交后触发登录权限刷新。新入口沿用已登记的 `seahub/oauth/views.py`
最小分发补丁，身份逻辑位于 `cloudfile_ext/sso/eap_oauth.py`。

## 存量与异常数据

- 已有 UID 精确绑定直接复用；旧工号 login_id 只允许在已有可信 provider/sub
  绑定和当前 EAP 目录一致时升级为 UID。不进行批量工号猜测或账号合并。
- EAP 有效用户按工号确定性选择字典序最小 UID，只保留选中记录的部门、角色关系，
  不合并重复人员权限，不清理原始业务数据。`cfadmin` 排除在员工同步之外。
- 重复 Profile 或跨组 UID 冲突保持未解析，只隔离受影响组的撤权；正常身份继续处理。
  整体目录结构损坏、数据库不可用仍拒绝整次同步，不能当作空目录。
- Seafile 原生建号通过 RPC，不能与 Profile SQL 回滚成同一事务。RPC 成功后 SQL
  失败可能留下未绑定原生账号；重试遇到同名冲突会拒绝，需核对后人工修复。
- 权限同步的 apply 开关、最大撤员数量与比例保护独立生效。本次身份配置不解除
  DEV 的零撤员保护；同步拒绝保持可重试。

## 验证入口

Hub：`CF_TEST_DB_PORT=<隔离 MariaDB 端口> python -m pytest cloudfile_ext/ cloudfile_extensions/ -q`。
OAuth 数据库测试覆盖新建、重复登录、停用、UID 变化、旧账号复用和 RPC 失败。
Docker：`python3 tools/test-bootstrap-settings.py`，并对示例配置执行 compose config。
EAP：Java 17 下执行目录测试及 `AuthentikSupportTest`；真实数据库用
`CF_DIRECTORY_TEST_DB_PORT` 指向隔离 MariaDB。测试数据库随机创建并清理。

这些是代码与本地回归入口，不代表 DEV 已完成发布或浏览器端登录验收。
