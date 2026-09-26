# CloudFile v0.2 容器集成

本仓库从 `build/seafile_14.0/release.json` 锁定 CloudFile 与上游 Seafile 14.0.8 源码，避免构建时重新落到未定制的上游 Seahub。`seafile-build.sh` 可不传版本；如传入版本，必须与清单一致。

## 扩展配置

容器每次启动都会幂等更新 `seahub_settings.py` 中的 CloudFile 配置块，并保留块外的本地配置。

- `CLOUDFILE_EXTENSION_APPS`：额外 Django 应用，逗号分隔。
- `CLOUDFILE_EXTENSION_URLCONFS_JSON`：扩展名到 URLConf 模块的 JSON 对象。
- `CLOUDFILE_CAPABILITIES_JSON`：请求启用已注册实现；公开字段仅限 `enabled`、`version`、`provider`，配置不能开启缺失实现或绕过依赖。
- `CLOUDFILE_WEBDAV_ENABLED`：声明已配置启用 WebDAV，默认 `false`；它不代替 WebDAV 服务本身的启停配置。

部署 URLConf 不得占用 directory、authorization、library-policy、directory-acl、annotations、audit、search、locks、local-edit、migration、transfer 核心域。自有能力由受信 Python 启动代码注册，配置 JSON 不能注册实现。

## Authentik OIDC

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
