# 本地 Authentik + CloudFile + Filestash 测试环境

此环境在现有 CloudFile Compose 上叠加独立 Authentik、Filestash 与只读 SFTP 服务。测试数据库、Seafile 文件、Authentik 状态、Filestash 状态、Caddy 状态和参考文件都放在 `data/local-reference/`，不会复用基础 Compose 的数据目录。参考文件只挂载到 SFTP 容器的受限用户主目录下，Filestash 不挂载该目录。所有 HTTP 入口只绑定本机回环地址，SFTP 不映射宿主机端口；仅供本机开发，不使用生产身份、凭据或数据。

## 前置条件与启动

需要 Docker Engine/Desktop 和 Compose v2。CloudFile 镜像须已构建或能从镜像仓库拉取。Authentik 固定为 `2026.5.7`；Filestash 默认使用上游 Docker Hub 的 `machines/filestash:latest`，首次拉取后建议将镜像 digest 记录在本地 env 文件，避免测试期间无意漂移。

```sh
cd deploy/compose
cp .env.example .env
cp .env.local-reference.example .env.local-reference
```

编辑 `.env.local-reference`：设置三个 CloudFile/MariaDB 密码、Authentik PostgreSQL 密码、`REFERENCE_SFTP_PASSWORD` 和至少 50 字符的随机 `AUTHENTIK_SECRET_KEY`。初始化管理员密码只在新数据目录第一次启动时生效。修改 `INIT_SEAFILE_ADMIN_EMAIL` 和密码；不要把 `.env` 或 `.env.local-reference` 提交到仓库。若填写 `AUTHENTIK_BOOTSTRAP_PASSWORD` 和 `AUTHENTIK_BOOTSTRAP_TOKEN`，Authentik worker 会在首次启动时为 `akadmin` 设置实验密码及 API token；留空则走 Web 初始设置。两个值仅保存在本机忽略文件中。

本地 URL 使用 `localtest.me` 子域名；浏览器和容器内分别通过本机回环/Docker 网络访问同一 OIDC issuer。若本机 DNS 不解析该域名，在 hosts 文件添加：

```text
127.0.0.1 cloudfile.localtest.me auth.localtest.me filestash.localtest.me
```

端口 80、9002、8334 须空闲。启动项目时使用不同 Compose project 名和独立数据路径：

```sh
docker compose -p cloudfile-local-reference \
  --env-file .env --env-file .env.local-reference \
  -f docker-compose.yml -f docker-compose.local-reference.yml \
  --profile reference-lab up -d
```

CloudFile 首次初始化需要数分钟。查看状态和日志：

```sh
docker compose -p cloudfile-local-reference \
  --env-file .env --env-file .env.local-reference \
  -f docker-compose.yml -f docker-compose.local-reference.yml \
  --profile reference-lab ps

docker compose -p cloudfile-local-reference \
  --env-file .env --env-file .env.local-reference \
  -f docker-compose.yml -f docker-compose.local-reference.yml \
  --profile reference-lab logs -f cloudfile authentik-server authentik-worker filestash
```

访问入口：

| 服务 | 地址 | 首次操作 |
| --- | --- | --- |
| Authentik | `http://auth.localtest.me:9002/` | 完成 initial setup，或使用预置 `akadmin` 测试凭据 |
| CloudFile | `http://cloudfile.localtest.me/` | 使用本地 `cfadmin` 登录并确认基础服务已就绪 |
| Filestash | `http://filestash.localtest.me:8334/` | 完成初始管理设置；在管理页检查 `/about` 中实际编译的插件 |

如 80 端口不可用，需同步更改 `HTTP_PORT`、本地 Caddyfile 监听端口、CloudFile OIDC redirect URI 及浏览器访问 URL。CloudFile 当前根据 hostname/protocol 推导回调地址，不会从 `HTTP_PORT` 推导非标准端口。

## 配置 Authentik OIDC

Authentik 管理员密码可通过初始设置流程创建，或在首次启动前设置 `AUTHENTIK_BOOTSTRAP_PASSWORD`。先创建 `cloudfile` OAuth2/OpenID Provider/Application，使用 confidential client 和 Authorization Code，并在 Provider 的 `grant_types` 中启用 `authorization_code`；实测省略该项会返回 `invalid_request`。应用只绑定测试用户或专用测试组。只有 Filestash 镜像实际包含 OpenID 插件时，再创建独立的 `filestash` Provider/Application；两个应用必须使用不同 client ID/secret。

CloudFile Provider：

- Redirect URI：`http://cloudfile.localtest.me/oauth/callback/`
- Client 类型：Confidential
- Issuer/discovery：`http://auth.localtest.me:9002/application/o/cloudfile/`
- Scope：`openid email profile`
- 保证 userinfo 返回稳定 `sub`、`email`、`name`

填入 CloudFile Provider 的 client ID/secret 到 `.env.local-reference` 的 `CF_SSO_OAUTH_CLIENT_ID` 与 `CF_SSO_OAUTH_CLIENT_SECRET`，再重启 CloudFile：

```sh
docker compose -p cloudfile-local-reference \
  --env-file .env --env-file .env.local-reference \
  -f docker-compose.yml -f docker-compose.local-reference.yml \
  --profile reference-lab up -d cloudfile
```

CloudFile 回调后以 Authentik 的 `sub` 绑定身份。保留 `cfadmin` 本地账号作为身份服务故障时的恢复入口。此 overlay 设置 `CF_SSO_OAUTH_INSECURE=true` 仅为本机 HTTP 联调；不要将它用于共享测试网或生产。

Filestash Provider：

- Redirect URI：`http://filestash.localtest.me:8334/api/session/auth/`
- OpenID Config URL：`http://auth.localtest.me:9002/application/o/filestash/.well-known/openid-configuration`
- Client 类型：Confidential；scope 至少 `openid email profile`
- 在 Filestash 管理 UI 的 Authentication / OpenID 中配置 discovery URL、client ID 和 secret；然后检查其实际 Host/base URL 和 `/about` 插件清单。

Filestash 官网将 OpenID 列为认证插件，同时把 OIDC/企业 SSO 归入特定发行能力；该服务不会假设所有社区镜像都含此插件。若本地镜像没有 OpenID 插件，可继续验证容器、挂载和只读边界，但 Authentik → Filestash 的 SSO 联调须使用具有对应插件授权的版本。参考：[Filestash 插件目录](https://www.filestash.app/docs/plugin/)、[Filestash OIDC 配置](https://www.filestash.app/setup-oidc.html)。

本次验证使用的社区镜像 `Filestash/v0.6.20260929` 不含 OpenID 插件。实际结果见 [本地验证记录](LOCAL-REFERENCE-VERIFICATION.md)。

## 配置只读参考资料

将一份非敏感测试文件放在 `data/local-reference/reference/`。该主机目录只读挂载到 `reference-sftp` 的 `/home/reference/reference`；SFTP 用户被 chroot 到 `/home/reference`。Filestash 存储连接选择 SFTP，地址 `reference-sftp:22`、用户 `reference`，密码使用本机 `.env.local-reference` 中的 `REFERENCE_SFTP_PASSWORD`。禁止将 Filestash 的 `local` 后端用于该参考库：其 `path` 可由登录请求指定，实测可读取 Filestash 容器的 `/etc`。确认：

1. SFTP 登录后只能看到 chroot 下的 `reference/` 和其中内容；Filestash 不直接挂载参考文件。
2. UI 中上传、创建目录、重命名、删除等操作不可用或失败。
3. 直接调用 Filestash 写入接口仍失败，且 SFTP 容器内参考目录的 mount 是只读。
4. 修改文件需由宿主机操作；该样例只用于验证只读参考库，不代表已支持 SMB/NFS/WebDAV 插件或目录级用户 ACL。

只读依赖 SFTP 用户的 chroot 与底层 bind mount，而不是隐藏 UI 操作。若后续接入 SMB/NFS，应给 Filestash 单独配置只读存储凭据/挂载，并复验相同写入拒绝场景。

## 测试边界与清理

该环境用于验证 CloudFile OIDC、Authentik 用户绑定、Filestash 容器启动、SFTP 目录隔离、参考目录读路径与底层只读。它不自动配置 Filestash 插件/授权，也不代表组到库映射、iframe Cookie/过期回跳和按库深链均已通过 v0.4 验收。尤其需把 Filestash 发行许可、OIDC 插件可用性和多库授权纳入单独的 v0.4 验证记录。

停止但保留测试数据：

```sh
docker compose -p cloudfile-local-reference \
  --env-file .env --env-file .env.local-reference \
  -f docker-compose.yml -f docker-compose.local-reference.yml \
  --profile reference-lab down
```

只有确认本地测试资料不再需要时，才手工删除 `data/local-reference/`；其中包含数据库、用户数据和 IdP 状态。基础部署的 `data/` 不受此测试项目影响。

## 版本依据

- Authentik Compose 固定版服务结构参考官方 `2026.5` Compose 配方，移除了无需本地 Outpost 管理的 Docker socket 挂载：[官方 Compose 安装说明](https://docs.goauthentik.io/install-config/install/docker-compose)。
- Filestash 安装使用官方文档的 Docker Hub 镜像名；标签 `latest` 可变：[安装说明](https://www.filestash.app/docs/install-and-upgrade/)。
