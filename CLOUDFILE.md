# CloudFile v0.2 容器集成

本仓库从 `build/seafile_14.0/release.json` 锁定 CloudFile 与上游 Seafile 14.0.8 源码，避免构建时重新落到未定制的上游 Seahub。`seafile-build.sh` 可不传版本；如传入版本，必须与清单一致。

尚未由人工推送的本地提交可通过 `CLOUDFILE_SERVER_SOURCE`、`CLOUDFILE_HUB_SOURCE` 提供给构建容器。两个值必须是绝对路径，且工作区干净、HEAD 与 `release.json` 的 40 位提交完全一致；构建器会复制 Git 对象后再构建，不修改来源仓库。未设置时继续只从清单中的 HTTPS 远端构建。例如在构建容器中把两个仓库只读挂载到 `/sources/cloudfile-server`、`/sources/cloudfile-hub`，并把对应环境变量设为这些容器内路径。该覆盖只用于本地已提交但尚未推送的 CloudFile 源码，不能绕过 release pin。

源码包成功生成后，运行 `build/seafile_14.0/build-local-image.sh [镜像标签]`。脚本使用临时 Docker context 组合已验证包、14.0 运行脚本及公共镜像资源，并把产品版本、Seafile 版本及 Hub/Server 精确提交写入镜像标签；它只构建本地镜像，不执行 push。

## 扩展配置

容器每次启动都会幂等更新 `seahub_settings.py` 中的 CloudFile 配置块，并保留块外的本地配置。

- `CLOUDFILE_EXTENSION_APPS`：额外 Django 应用，逗号分隔。
- `CLOUDFILE_EXTENSION_URLCONFS_JSON`：扩展名到 URLConf 模块的 JSON 对象。
- `CLOUDFILE_CAPABILITIES_JSON`：请求启用已注册实现；公开字段仅限 `enabled`、`version`、`provider`，配置不能开启缺失实现或绕过依赖。
- `CLOUDFILE_WEBDAV_ENABLED`：声明已配置启用 WebDAV，默认 `false`；它不代替 WebDAV 服务本身的启停配置。
- `CLOUDFILE_AUTHORIZATION_ENABLED`：挂载内建 authorization v1 路由，默认 `false`；必须同时启用 post-fork policy worker，并配置真实目录、主体刷新和委托发行运行时。该开关不自动声明 capability 已交付。
- `CLOUDFILE_POLICY_CONFIG_JSON`：严格 JSON 的可信 worker 配置；包含数据库、专属 Redis、Directory Adapter、C ACL 库、机器凭证范围、刷新 provider grant 与独立委托签名键。`CLOUDFILE_AUTHORIZATION_ENABLED=true` 时必须同时设置它和 `CLOUDFILE_POLICY_WORKER_HOOKS=true`，重复字段或不完整安全配置拒绝启动。
- `CLOUDFILE_LOCAL_EDIT_ENABLED`：挂载内建 local-edit URL，默认 `false`；只有同时配置 post-fork policy worker、资源生命周期读取器、本地编辑版本读取器和固定 HTTPS 实例 origin 后才可设为 `true`，该开关本身不声明能力已交付。
- `CLOUDFILE_TRANSFER_ENABLED`：挂载 cookie-free 的 `transfer/v1/delegated-read-tickets/`，默认 `false`；必须同时启用 post-fork policy worker，并由完整 `CLOUDFILE_POLICY_CONFIG_JSON` 构造独立委托验签键、共享撤销存储与 native ticket RPC。该开关不挂载 OIDC 会话票据，也不自动声明 `transfer.web` 已交付。

部署 URLConf 不得占用 directory、authorization、library-policy、directory-acl、annotations、audit、search、locks、local-edit、migration、transfer、identity 核心域。自有能力由受信 Python 启动代码注册，配置 JSON 不能注册实现。

authorization/transfer 的 `CLOUDFILE_POLICY_CONFIG_JSON` 最小结构如下；示例值必须由部署密钥系统替换，机器凭证密钥与委托签名密钥不得相同：

```json
{
  "database": {"host":"db","port":3306,"user":"cloudfile","name":"seafile_db","password":"replace-me"},
  "redis": {"host":"redis","port":6379,"password":"replace-me"},
  "provider":"etech",
  "native_schema":"ccnet_db",
  "identity_schema":"seahub_db",
  "directory_url":"https://etech.example.com/eap/cloudDrive/directory/v2",
  "directory_bearer_token":"replace-me",
  "attribute_allowlist":[],
  "core_library":"/opt/seafile/seafile-server-latest/seafile/lib/libcloudfile_acl.so.1",
  "cloud_mode":false,
  "service_credentials":{"login-v1":{"service_id":"etech-login","issuer":"etech-login","audience":"cloudfile-authorization","secret":"replace-with-machine-secret-32-bytes-min","scopes":["subject.refresh","user.delegation.issue"],"maximum_ttl":120}},
  "refresh_provider_grants":{"etech-login":["etech"]},
  "delegation_signing_keys":{"etech-login":{"kid":"delegation-v1","issuer":"cloudfile","audience":"cloudfile-download","secret":"replace-with-distinct-signing-secret-32-bytes-min"}}
}
```

上述 JSON 只在 Gunicorn worker fork 后构造 Redis 撤销存储、机器 verifier 和委托 signer；URLConf/preload master 不持有连接。生产环境应限制生成的 `seahub_settings.py` 读取权限，并通过编排系统注入秘密，不能把实际值提交到源码仓库。

## 完整 OIDC 的显式部署接线

v0.2 的完整 OIDC 使用既有签名校验、登录资源、原生 session backend 和 guarded session middleware，默认关闭。先部署 schema、预绑定账号、真实目录与权限配置，再显式设置：

```dotenv
CLOUDFILE_OIDC_ENABLED=true
CLOUDFILE_POLICY_WORKER_HOOKS=true
CLOUDFILE_OIDC_JIT_ENABLED=false
CLOUDFILE_AUTHENTIK_ENABLED=false
```

同时提供 `CLOUDFILE_POLICY_CONFIG_JSON` 和严格 `CLOUDFILE_OIDC_CONFIG_JSON`，例如：

```json
{
  "issuer":"https://auth.example.com/application/o/cloudfile/",
  "client_id":"cloudfile",
  "client_secret":"replace-through-deployment-secret-store",
  "redirect_uri":"https://files.example.com/api/v2.1/cloudfile/extensions/identity/v1/callback/",
  "authorization_url":"https://auth.example.com/application/o/authorize/",
  "token_url":"https://auth.example.com/application/o/token/",
  "userinfo_url":"https://auth.example.com/application/o/userinfo/",
  "jwks_url":"https://auth.example.com/application/o/cloudfile/jwks/",
  "user_id_claim":"userId"
}
```

issuer/JWKS 等必须取实际 provider 配置并精确注册 callback；示例不替代 IdP 联验。可选 `ca_bundle` 指向可信容器内 CA 文件；RP logout 的 `end_session_url` 与 `post_logout_redirect_uri` 必须同时配置，后者固定为同 origin 的 `identity/v1/logout/return/`。SITE_ROOT 非 `/` 时 callback/return URI 必须含相同前缀。

Django app 启动先把原始配置校验为既有 `OIDCConfig`；只替换原位置的 SessionMiddleware，保留本地恢复认证 backend，追加 CloudFile backend，并要求数据库 session。legacy `ENABLE_OAUTH`、多个 session middleware、另一套 login resource owner、回调路径不符或配置不完整均拒绝，不输出秘密。启用后 session/CSRF cookie 为 Secure，session 为 HttpOnly。反向代理须按真实信任边界提供 HTTPS，不能对任意客户端信任转发头。

内建路径为 `identity/v1/begin/`、`callback/`、`pending/`、`logout/`、`logout/idp/`、`logout/return/`。URLConf 不在 preload master 创建连接；请求和会话保护通过当前 post-fork PolicyHost 获取资源。未初始化、排空或缺资源返回 503，worker 配置失败拒绝启动。`CLOUDFILE_OIDC_ENABLED` 不自动声明 `auth.oidc` capability，也不自动启动 JIT worker或安装 backchannel logout；这些须各自取得完整运行证据。

首次部署可从已预绑定账号闭环，JIT 保持关闭。升级前先显式执行现有迁移，不在请求或 app ready 自动 DDL。回退时先排空/冻结受管入口并恢复匹配配置/数据库，不得把受保护 OIDC session 改为普通 session middleware 继续提供访问。

## 旧 Authentik OAuth 配置预设

CloudFile 内建的是 Authentik 的首选 OIDC 配置，不在本容器中捆绑 Authentik 服务。必填变量：

```dotenv
CLOUDFILE_AUTHENTIK_ENABLED=true
CLOUDFILE_AUTHENTIK_URL=https://auth.example.com
CLOUDFILE_AUTHENTIK_CLIENT_ID=cloudfile
CLOUDFILE_AUTHENTIK_CLIENT_SECRET=replace-me
SEAFILE_SERVER_PROTOCOL=https
SEAFILE_SERVER_HOSTNAME=files.example.com
```

默认回调地址为 `https://<SEAFILE_SERVER_HOSTNAME>/oauth/callback/`，也可用 `CLOUDFILE_AUTHENTIK_REDIRECT_URL` 覆盖。预设将 OIDC `sub` 映射为 CE OAuth `uid`，将 `preferred_username` 映射为 CE `login_id`；`sub` 是认证绑定键，不替代业务主体 `userId`。如果业务 `userId` 不等于 `preferred_username`，必须在部署验收前完成可信 claim 的映射调整和目录对账；当前预设本身不保证两者相同。

未知用户默认不自动创建、不自动激活，SSO 用户默认禁止本地密码登录。先预绑定业务身份并验收停用/撤权；显式开启自动建号也不等于实现受控 JIT。仅本地开发可显式设置 `CLOUDFILE_AUTHENTIK_ALLOW_INSECURE=true`。

该预设复用 CE OAuth 授权码/UserInfo 回调，不应单凭 `openid` scope 声称完整 OIDC 已验收。ID Token 签名、issuer/audience/有效期/nonce、UserInfo sub 一致性与退出流程须按产品身份特性单独实现和验证。

v0.2 目标方案采用受控 JIT，而不是当前预设的无条件建号：仅可信 userId 已在目录存在且启用、无绑定冲突、provider 获准时创建新用户；已有用户复用或预绑定。持久身份沿用 CE 用户/原生绑定，动态主体只缓存 CF 专属 Redis，缓存过期刷新最新目录。详见 `eap-cloudfile/docs/features/identity-directory.md`；这些流程尚未实现，不能通过打开当前自动建号变量替代。

基础认证继续用于本地账户。WebDAV 不复用浏览器 OIDC 会话，应使用独立的 WebDAV 应用密码。CloudFile 不扩展客户端及同步功能。

产品规划与上线设计在 `eap-cloudfile` 仓库；本文件仅说明当前容器配置，不代表目录 ACL、审计、搜索、标签、锁、本地编辑或迁移 API 已实现。
