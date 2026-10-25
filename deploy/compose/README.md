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
- **CloudFile 新增**：目录 ACL、组织映射、审计、可替换检索、多存储、外部资料源、文件操作生命周期。功能默认值以当前 `.env.example` 和启动生成器为准；普通库 Checkout 默认 OFF，其他内置能力按实际支持开启。
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


## 库级 Checkout（OFF / OPTIONAL）

普通文件库默认 **OFF**，只使用 Seafile 原生版本与权限能力，不进入 Guard SQL；
专业库可显式设为 **OPTIONAL**，允许用户对单个文件主动 Checkout、Commit、
Checkin。本产品**不提供 REQUIRED**（强制全部签出）模式。

`CF_ENABLE_CHECKOUT=false` 是全局总开关（默认）；开启总开关后，
仍然**只**对 `CF_CHECKOUT_REPOS` 中列出的 **Repo UUID** 启用 OPTIONAL：

```env
CF_ENABLE_CHECKOUT=true
CF_CHECKOUT_REPOS=11111111-1111-4111-8111-111111111111
```

`CF_CHECKOUT_REPOS` 为空则所有库保持 OFF。每个 UUID 必须是标准小写形式，
多库用逗号隔开。配置启动时校验并同步生成 Hub 与原生 `seafile.conf`
（Go/C 使用 `checkout_repo_ids`）；变更需协调重启对应服务。
无新表、库级运行时数据库查询、文件类型自动切换或动态策略后台。

**运维变更纪律：** 将 OPTIONAL 库移出列表或关闭总开关之前，先停止新签出，
完成/取消该库所有活动 Checkout、处理 Agent 本地待确认任务，并确认不存在
未过期的 Guard 租约。不能通过关闭能力绕过尚未完成的独占编辑。
原先全局启用 Checkout 的部署升级时，必须先将仍有活动锁的库
纳入白名单，并在统一重启前完成核对。

仅 OPTIONAL 库依赖 Guard 表；Guard 失效时对应库拒绝不安全写入，
但未启用的库继续普通文件操作。与 Hub PR #50、
Agent2 #10 / #1 联动验收后再向 PROD 发布。
