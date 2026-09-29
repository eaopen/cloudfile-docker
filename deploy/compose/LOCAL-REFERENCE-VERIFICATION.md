# 本地混合资料环境验证记录

日期：2026-09-29。环境：macOS arm64、Docker Compose 项目 `cloudfile-local-reference`。本次使用隔离目录 `data/local-reference/` 和本机随机生成的忽略文件 `.env.local-reference`；没有使用生产数据或凭据。

| 验证项 | 实际结果 |
| --- | --- |
| Compose 配置 | `docker compose ... config --quiet` 成功；11 个服务运行，MariaDB、Redis、CloudFile、Authentik PostgreSQL/server/worker 均为 healthy。 |
| 本机入口 | CloudFile `127.0.0.1:80`、Authentik `127.0.0.1:9002`、Filestash `127.0.0.1:8334`；SFTP 仅在 Compose 网络暴露 22 端口。Caddy 重新创建后只绑定 `127.0.0.1:80`。 |
| CloudFile 基线 | `/api2/ping/` 返回 200、`pong`；登录页返回 200。 |
| Authentik | `/-/health/ready/` 返回 200；bootstrap API token 可读取 `akadmin` 用户；CloudFile 应用的 OIDC discovery 返回 200。 |
| CloudFile OIDC | `/oauth/login/` 302 到 Authentik；使用本地测试 `akadmin` 账号完成认证，授权响应带 code，CloudFile callback 302 到首页；随后 `/api2/account/info/` 返回 200 且为已登录用户。使用两个独立会话复测，账号 email 与 contact email 一致。首次建 Provider 漏填 `grant_types` 时 Authentik 返回 `invalid_request`，补上 `authorization_code` 后通过。 |
| Filestash 参考库 | 使用 SFTP 连接 `reference-sftp:22` 登录返回 200；根目录只显示 `reference`，`/reference/` 只显示 `sample.txt`，读取文件返回 200；访问 `/etc/` 返回 404。 |
| Filestash 只读 | 向 `/reference/should-fail.txt` POST 上传返回 403；宿主目录没有生成该文件。SFTP 容器参考目录是只读 bind mount。旧的 `local` 后端登录请求现返回 403。 |
| Filestash OIDC | **未通过/待具备插件的镜像**。当前社区镜像的 `/about` 显示 `Filestash/v0.6.20260929`、41 个插件，没有 `plg_authenticate_openid`；无法配置 Authentik → Filestash OIDC。不能据此认定 v0.4 的统一登录、iframe 或多库授权已经验收。 |

## 修复过的边界问题

最初直接把参考目录以只读方式挂给 Filestash `local` 后端。实测 `/api/session` 的 `path=/etc` 可登录并列出容器系统目录，说明只读挂载不提供读取范围隔离。现改为独立 SFTP 容器：SFTP 用户被 chroot 到自己的主目录，参考目录以只读方式挂在其中；Filestash 不再直接挂载参考目录，公开的连接配置只列 SFTP。复测 `local` 请求返回 403，SFTP 访问 `/etc/` 返回 404。后续更换存储协议时必须重新验证目录边界。

## 镜像与限制

- CloudFile：`cloudfile/cloudfile:14.0.8-cf.0-current`（本机已有镜像）。
- Authentik：`ghcr.io/goauthentik/server:2026.5.7`，digest `sha256:76bf433fd434c067cb25dc3e197cee793998441cda912441ea275293e76cc32c`。
- Filestash：`machines/filestash:latest`，本次 digest `sha256:c7c5916ecf3547ab08626c130b7b57f79332d6bc93ef98c069be0414943e6f06`。
- SFTP：`atmoz/sftp:latest`，本次 digest `sha256:0960390462a4441dbb63698d7c185b76a41ffcee7b78ff4adf275f3e66f9c475`；镜像为 amd64，在本机 arm64 上由 Docker 模拟运行。
- 本机 `localtest.me` 的 DNS/代理行为不稳定。HTTP/OIDC 的程序化验证将三个域名指向 `127.0.0.1`，保持 Host、redirect URI 和 cookie 域不变；浏览器使用前需确认本机解析或添加 hosts 记录。

Filestash 上传接口的用法依据 [官方 API 文档](https://www.filestash.app/docs/api/)；SFTP 用户 chroot 行为依据 [atmoz/sftp 官方镜像说明](https://hub.docker.com/r/atmoz/sftp)；Filestash OIDC 能力限制参见 [官方版本比较](https://www.filestash.app/pricing/)。
