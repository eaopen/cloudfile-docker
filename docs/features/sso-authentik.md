<!-- generated-by: gsd-doc-writer -->
# Authentik 与企业认证

> 用途：说明默认企业身份入口、协议、字段映射、恢复方式和实现边界
> 适用版本：Seafile CE 14 参考基线；authentik stable 2026.5.6（截至 2026-08-11）
> 当前状态：部分完成；通用 OAuth2/OIDC 配置和组织映射已有，Authentik MVP 端到端验收仍待完成

## 官方参考基线

本文按 authentik stable 2026.5.6 编写。版本与修复项见 authentik 官方
[2026.5 release notes](https://docs.goauthentik.io/releases/2026.5/)，Provider、端点、issuer、
scope 和流程语义见官方
[OAuth 2.0 provider](https://docs.goauthentik.io/add-secure-apps/providers/oauth2/) 文档。

生产部署应固定到已验证的 stable patch（当前参考为 `2026.5.6`），不要使用会随时间变化的
`latest` tag。升级到后续 patch 或 release train 前，应重新执行本文的 MVP 验收清单。

## 产品定义

CloudFile 默认以 Authentik 作为企业身份协议与 Seafile 之间的身份代理或统一认证入口。
企业的 OpenID Connect（OIDC）、SAML 2.0、LDAP、Active Directory（AD）或其他身份源，
优先在 Authentik 中完成协议适配和身份源集成，再由 CloudFile 连接 Authentik。

这一定义不表示 CloudFile 自主实现这些协议，也不表示存在 Authentik 专用协议实现：

- Authentik 负责连接企业身份源、认证策略、MFA 和对外 OAuth2/OIDC Provider。
- Seafile CE 自带通用 OAuth2/OIDC Authorization Code 登录，以及 SAML、LDAP 等认证代码。
- CloudFile 只把 `.env` 翻译成 Seafile CE 设置，并新增独立的组织/组同步。

## 当前实现与边界

CloudFile 与 Authentik 的当前技术路径是 Seafile CE 的通用 OAuth2/OIDC Authorization Code
流程，使用 user-info claim 做身份映射。仓库没有 Authentik 专属 Compose 服务、blueprint、
协议适配代码或端到端测试，也没有把 OIDC discovery 文档自动翻译为 Seahub 配置；操作员必须
填写精确端点。因此当前结论是“已有通用 OIDC 接线，可配置 Authentik”，不是“Authentik
MVP 已验收”或“已验证支持 Authentik”。

SAML、LDAP、AD 等应先接入 Authentik。仓库虽保留 Seafile CE 的直接 SAML/LDAP 配置，
但它们不是 CloudFile 默认企业认证路径，也未被 Authentik 门禁覆盖。

代码证据边界：[`bootstrap.py`](../../scripts/scripts_14.0/bootstrap.py) 的
`_settings_block_sso()` 只生成 `ENABLE_OAUTH`、端点、client、scope、provider、redirect
和 claim 映射；实际授权码登录由
[`views.py`](../../../cloudfile-hub/seahub/oauth/views.py) 的 `OAuth2Session` 完成。两处代码
均没有 Authentik 专用分支。

## Authentik Provider 配置

为 CloudFile 创建独立的 Authentik Application 与 OAuth2/OIDC Provider，并采用以下设置：

- 使用 confidential client，保存独立的 `client_id` 与 `client_secret`；不要把 secret 写入
  镜像、仓库或前端代码。
- 使用 Authorization Code；不要启用或依赖 implicit flow。
- Redirect URI 精确登记为 `https://<CloudFile 主机>/oauth/callback/`，包括 HTTPS、主机名、
  路径和末尾 `/`；不要用通配符或让首次请求自动学习 URI。
- 保持 Authentik 默认的 per-provider issuer。其 issuer 为
  `https://<Authentik 主机>/application/o/<application_slug>/`，discovery 地址为
  `https://<Authentik 主机>/application/o/<application_slug>/.well-known/openid-configuration`。
- 只配置并请求登录所需的 `openid email profile` scope；不要加入 `offline_access`、
  `goauthentik.io/api` 或其他自定义 scope，除非已有明确需求和验收。
- 将稳定、不随邮箱、用户名或显示名变化的 subject 作为 `sub`。在 Authentik Application
  上显式绑定允许访问的用户、组或策略，避免“创建应用即全员可用”的隐式授权。

Authentik 当前官方标准端点及对应 CloudFile 变量如下。端点前三项是全局 OAuth2 端点，
discovery、JWKS 和 end-session 带 application slug：

| CloudFile 变量或用途 | 精确路径 |
|---|---|
| `CF_SSO_OAUTH_AUTHORIZATION_URL` | `https://<Authentik 主机>/application/o/authorize/` |
| `CF_SSO_OAUTH_TOKEN_URL` | `https://<Authentik 主机>/application/o/token/` |
| `CF_SSO_OAUTH_USER_INFO_URL` | `https://<Authentik 主机>/application/o/userinfo/` |
| OIDC discovery | `https://<Authentik 主机>/application/o/<application_slug>/.well-known/openid-configuration` |
| JWKS | `https://<Authentik 主机>/application/o/<application_slug>/jwks/` |
| end-session | `https://<Authentik 主机>/application/o/<application_slug>/end-session/` |

最小 CloudFile 配置形态为：

```dotenv
CF_ENABLE_SSO=true
CF_SSO_OAUTH_CLIENT_ID=<authentik provider client id>
CF_SSO_OAUTH_CLIENT_SECRET=<authentik provider client secret>
CF_SSO_OAUTH_AUTHORIZATION_URL=https://<Authentik 主机>/application/o/authorize/
CF_SSO_OAUTH_TOKEN_URL=https://<Authentik 主机>/application/o/token/
CF_SSO_OAUTH_USER_INFO_URL=https://<Authentik 主机>/application/o/userinfo/
CF_SSO_OAUTH_SCOPE=openid email profile
CF_SSO_OAUTH_PROVIDER=authentik:<application_slug>
CF_SSO_OAUTH_UID_CLAIM=sub
CF_SSO_OAUTH_EMAIL_CLAIM=email
CF_SSO_OAUTH_NAME_CLAIM=name
CF_SSO_OAUTH_INSECURE=false
```

`CF_SSO_OAUTH_PROVIDER` 是 Seahub 写入 `SocialAuthUser.provider` 的本地稳定标识，并非
discovery URL。上线后不要修改；多个 Authentik Provider 必须使用不同且稳定的值，否则既有
账号绑定可能失联或冲突。

## 登录流程

1. 用户访问 `/oauth/login/`，Seahub 创建 OAuth state 并跳转到
   `CF_SSO_OAUTH_AUTHORIZATION_URL`。
2. Authentik 完成认证后回调 `https://<CloudFile 主机>/oauth/callback/`。
3. Seahub 以 confidential client 的 client secret 向 token endpoint 交换授权码，再从
   user-info endpoint 读取 claim。
4. `OAUTH_PROVIDER` 与 `uid` 识别外部账号；首次登录时默认允许创建激活的 OAuth 用户，
   并写入 `SocialAuthUser` 绑定。
5. CloudFile 的登录信号可触发单人组关系刷新；完整组织同步仍由 `cf-worker` 周期任务完成。

Seahub 当前 `OAuth2Session` 调用没有生成或发送 `code_challenge`、`code_verifier`，因此本文
不宣称 PKCE；不得在 Authentik 端把“要求 PKCE”设为本次接入的先决条件。state 已用于回调
关联，但不能把它写成 PKCE 已实现。

证据：[`views.py`](../../../cloudfile-hub/seahub/oauth/views.py)、
[`backends.py`](../../../cloudfile-hub/seahub/oauth/backends.py)、
[`cloudfile_ext/sso/`](../../../cloudfile-hub/cloudfile_ext/sso/) 和
[`bootstrap.py`](../../scripts/scripts_14.0/bootstrap.py)。

> **限制：** bootstrap 当前没有暴露 `OAUTH_CREATE_UNKNOWN_USER`。首次登录自动建用户沿用
> Seafile CE 默认值；在完成 Authentik 验收前，不应假设已提供“仅允许预建用户”开关。

## 字段映射

| CloudFile 变量 | 默认 claim | Seahub 用途 | 要求 |
|---|---|---|---|
| `CF_SSO_OAUTH_UID_CLAIM` | `sub` | 外部稳定用户 ID | 必须跨登录稳定，不能使用会变化的邮箱、用户名或显示名 |
| `CF_SSO_OAUTH_EMAIL_CLAIM` | `email` | 联系邮箱与创建用户回退值 | 当前映射标记为必需 |
| `CF_SSO_OAUTH_NAME_CLAIM` | `name` | 显示名称 | 可选 |
| `CF_SSO_OAUTH_PROVIDER` | 无 | `SocialAuthUser.provider` | 部署后不应更改，否则既有绑定会失联 |

当 UID claim 与 email claim 同名时，bootstrap 只生成一个 email 映射，避免 Python 字典
键覆盖。Authentik 应保证 `sub` 不因邮箱、用户名或显示名修改而改变。

## 登出

`/accounts/logout/` 会清除 Seahub 本地会话。Seafile CE 只有设置 `OAUTH_LOGOUT_URL` 时才
继续跳转到身份提供方登出地址；当前 CloudFile `.env` 和 bootstrap 没有暴露该设置，
因此 Authentik end-session 端点虽然已知，单点登出仍未接线和验收。项目负责人需确认回跳
地址和多应用会话策略后再增加配置与测试。

## 组织与组同步

认证与组织同步是两条独立链路。`CF_PROVIDER_SSO_DIRECTORY` 当前支持：

- 留空：只登录，不同步组；
- `static`：从 `CF_SSO_DIRECTORY_STATIC` 读取完整快照，已用于能力门禁；
- `external-service`：从项目定义的 `/groups` 接口拉取，代码与单测存在。

仓库没有直接读取 Authentik group claim、API、LDAP 或 AD 的 provider。Authentik 的“可发
group claim”不能自动写成 CloudFile“已支持组织同步”；要么实现并验证 Authentik 目录
provider，要么由外部适配服务提供当前契约。

组织同步只管理自己创建并登记在 `cf_sso_group_map` 的组，不删除离开目录的组；空快照和
异常大批量移除会被拒绝。未在 Seafile 中存在的用户不会由目录同步创建，只会出现在未解析
报告中。

## 密钥轮换与故障恢复

当前 `CF_ENABLE_SSO` 只设置 `ENABLE_OAUTH=True`，没有关闭本地密码登录。部署时必须保留
一个不依赖 Authentik 的本地管理员，并验证 `/accounts/login/` 可用；凭据应离线保管，
不得同步到企业目录。

Client secret 轮换应作为受控变更：先保留本地管理员恢复能力，在 Authentik 生成或替换
secret，将 `CF_SSO_OAUTH_CLIENT_SECRET` 同步更新到部署密钥存储并重启 CloudFile，然后
分别验证新登录与既有本地管理员登录。若 Authentik 的轮换方式不能让新旧 secret 短暂并存，
应安排维护窗口；不得在确认新 secret 生效前销毁恢复凭据。

Authentik 故障时：

1. 使用本地管理员登录；不要删除既有 `SocialAuthUser` 绑定。
2. 核对 Authentik、DNS、TLS、三个精确 OAuth 端点、client secret、Redirect URI 和系统时间。
3. 组织同步失败时保持上次成功状态；不得把“请求失败”解释为空目录。
4. 如需临时关闭 CloudFile SSO，设置 `CF_ENABLE_SSO=false` 并重启；先确认仍有本地登录账号。

## 密钥、证书与配置位置

- OAuth client secret：`deploy/compose/.env` 中的
  `CF_SSO_OAUTH_CLIENT_SECRET`，由 Compose 传给 bootstrap；生产环境应通过受控密钥存储
  注入，避免提交到仓库。
- 生成设置：运行时写入容器持久化目录中的 Seahub 设置文件，位于标记配置块内；该文件
  由 [`bootstrap.py`](../../scripts/scripts_14.0/bootstrap.py) 生成，不是仓库源文件。
- SAML SP key/certificate：仅用于直接 SAML 路径；不属于当前 Authentik OIDC 验证范围。
- Authentik 服务器证书信任由容器操作系统/反向代理负责；
  `CF_SSO_OAUTH_INSECURE=true` 只允许实验环境 HTTP，不是证书修复方案。

## MVP 验收状态

当前实现已有代码或自动化证据的范围：

- 通用 OAuth 配置生成，包括固定回调地址、最小 scope 默认值与 claim 映射；
- Seahub CE Authorization Code、state、token 交换和 user-info 处理代码；
- 静态目录两阶段组织同步、删除保护和本地 CE 冒烟。

以下均为 Authentik MVP 接受条件，当前仍待完成；在全部通过前不得把状态升级为“已完成”：

- 固定 authentik `2026.5.6`，按 per-provider discovery 核对 issuer、authorization、token、
  user-info 与 JWKS，验证 confidential client 的完整登录流程；
- 验证精确 HTTPS Redirect URI，确认错误协议、主机、路径或末尾 `/` 会被拒绝；
- 验证 `sub`、`email`、`name` 实际映射、首次用户创建，以及修改邮箱后仍通过稳定 `sub`
  命中原 `SocialAuthUser`；
- 验证 Application 显式用户/组/策略 binding：授权用户可登录，未绑定用户被拒绝；
- 证明请求使用 Authorization Code 且没有 implicit flow；记录当前不支持 PKCE 的事实；
- 完成 client secret 轮换、Authentik 不可用、TLS 证书轮换和本地管理员恢复演练；
- 决定并验证 Authentik end-session 与 Seahub 本地登出的组合；
- 决定 Authentik 组织/组同步适配方式，并验证上游 LDAP、AD、SAML 或 OIDC 身份源场景。
