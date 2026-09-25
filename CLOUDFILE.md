# CloudFile v0.2 容器集成

本仓库从 `build/seafile_14.0/release.json` 锁定 CloudFile 与上游 Seafile 14.0.8 源码，避免构建时重新落到未定制的上游 Seahub。`seafile-build.sh` 可不传版本；如传入版本，必须与清单一致。

## 扩展配置

容器每次启动都会幂等更新 `seahub_settings.py` 中的 CloudFile 配置块，并保留块外的本地配置。

- `CLOUDFILE_EXTENSION_APPS`：额外 Django 应用，逗号分隔。
- `CLOUDFILE_EXTENSION_URLCONFS_JSON`：扩展名到 URLConf 模块的 JSON 对象。
- `CLOUDFILE_CAPABILITIES_JSON`：部署能力声明；公开字段仅限 `enabled`、`version`、`provider`。
- `CLOUDFILE_WEBDAV_ENABLED`：声明 WebDAV 是否可用，默认 `true`；它不代替 WebDAV 服务本身的启停配置。

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

默认回调地址为 `https://<SEAFILE_SERVER_HOSTNAME>/oauth/callback/`，也可用 `CLOUDFILE_AUTHENTIK_REDIRECT_URL` 覆盖。用户稳定标识采用 OIDC `sub`；新用户默认自动创建并激活，SSO 用户默认禁止本地密码登录。仅本地开发可显式设置 `CLOUDFILE_AUTHENTIK_ALLOW_INSECURE=true`。

基础认证继续用于本地账户。WebDAV 不复用浏览器 OIDC 会话，应使用独立的 WebDAV 应用密码。CloudFile 不扩展客户端及同步功能。
