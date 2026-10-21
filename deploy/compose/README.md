# CloudFile Compose 部署

> **用途**：本仓的 Compose 部署入口说明（自包含）。
> **适用版本**：CloudFile `14.0.0-cf.0`，基于 Seafile CE 14。
> **状态**：当前有效。

本目录是部署实现本体：`docker-compose.yml`、可选 profile 覆盖文件、`Caddyfile` 与
`.env.example`。产品与规划文档不在本仓维护。

## 快速开始

```bash
cd deploy/compose
cp .env.example .env          # 修改主机名、管理员邮箱/密码、两个数据库密码
docker compose config --quiet # 检查解析后的配置
docker compose up -d
docker compose logs -f cloudfile
```

首次启动会初始化数据库、Seafile 配置和管理员账号；`INIT_SEAFILE_ADMIN_*` 只在首次初始化时使用。

## 组件边界

- **复用 Seafile CE**：资料库、同步、WebDAV、分享、预览，以及 CE 已有的 LDAP/SAML/角色/2FA。
- **CloudFile 新增**：目录 ACL、组织映射、审计、可替换检索、多存储、外部资料源、文件操作生命周期。所有 `CF_ENABLE_*` 默认关闭。
- **外部组件**：MariaDB、Redis、Caddy、SeaSearch、Meilisearch、Metadata Server、seafile-ai、OnlyOffice、SeaDoc、MinIO 均为独立容器，许可与升级策略单独评估。

## 上线前必读

- 开启 `CF_ENABLE_DIR_ACL=true` 时，不得对外暴露**未应用** `patches/seafdav/*` 的 WebDAV 入口；只在前端隐藏入口不够，改过的客户端可以直连端口。
- 桌面同步/SeaDrive 不受影响：Server 侧对同步与打包下载做 fail-closed 整库/整树预检。
- WebDAV 读侧回归断言见 `tests/e2e/full/acl_matrix.py`；全部通过 = 补丁随镜像生效。
- 变量清单与逐项说明见本目录 `.env.example`（带注释，是唯一变量权威）。

## 构建与镜像

镜像与发行包由 `build/cloudfile_14.0/build-in-docker.sh` + `image/cloudfile_14.0/docker-build.sh`
生成，来源 SHA 由根目录 `release.yaml` 解析后写入 `build-receipt.json`。
入口说明见根目录 `README.md`、`CLOUDFILE.md`、`AGENTS.md`。
