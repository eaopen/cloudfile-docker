<!-- generated-by: gsd-doc-writer -->
# CloudFile Compose 部署

> **用途**：部署和维护 CloudFile 单机 Compose 栈，并说明各可选组件的启用边界。
> **适用版本**：CloudFile `14.0.0-cf.0`，基于 Seafile CE 14 源码重构。
> **状态**：当前有效；核心栈和能力门禁已有自动化配置检查，AI 容器仍待真实端到端验证。

## 组件边界

- **复用 Seafile CE**：CloudFile 主服务沿用 Seafile 的资料库、同步、WebDAV、分享、预览及 CE 内已有的 LDAP、SAML、Shibboleth、角色、2FA、OnlyOffice、metadata/AI 接口。
- **CloudFile 新增**：统一环境变量写入、目录 ACL、组织映射、审计、可替换检索、多存储、外部资料源、文件操作生命周期和相应门禁；所有 `CF_ENABLE_*` 默认关闭。
- **外部组件**：MariaDB、Redis、Caddy、SeaSearch、Meilisearch、Metadata Server、seafile-ai、OnlyOffice、SeaDoc 和 MinIO 均为独立容器，不由 CloudFile 业务代码实现；其许可证、容量与升级策略需单独评估。

## WebDAV 与目录 ACL（上线门禁，必读）

seafdav 的目录列举（PROPFIND/GET）不经过 `check_permission_by_path`，因此
`invisible` 等 ACL 语义在 **WebDAV 读路径上不生效**（写路径生效）。在 WebDAV 读
闭环补齐之前（决策 `eap-cloudfile/docs/review/cloudfile_decision_20260827.md`
上线门禁第 7 条）：

1. 本 compose 栈默认**不部署 seafdav**（`docker-compose.yml` 无该服务）。如需
   WebDAV，必须自行添加 seafdav 服务，并确认**没有任何库启用目录 ACL**；
2. 只要 `CF_ENABLE_DIR_ACL=true`，就不得对任何入口暴露 WebDAV——不能只在前端
   UI 隐藏入口（改过的客户端可以直接连 seafdav 端口）；
3. 桌面同步/SeaDrive 不受此缺口影响：`is_repo_syncable` / `is_dir_downloadable`
   RPC 桩在 Server 侧对同步与打包下载做了 fail-closed 检查；
4. WebDAV 读闭环的工程位置：seafdav 目录列举/GET 接 `check_permission_by_path`
   RPC（见 `docs/acl-semantics.md` §6「已知缺口」）。

## 快速开始

1. 复制配置并修改主机名、管理员密码和两个数据库密码：

   ```bash
   cd deploy/compose
   cp .env.example .env
   ```

2. 检查解析后的配置：

   ```bash
   docker compose config --quiet
   ```

3. 启动核心栈：

   ```bash
   docker compose up -d
   docker compose logs -f cloudfile
   ```

首次启动会初始化数据库、Seafile 配置和管理员账号。`INIT_SEAFILE_ADMIN_*` 只在首次初始化时使用。

## Profile

| Profile | 新增服务 | 用途与状态 |
|---|---|---|
| 默认 | `cloudfile`、`db`、`cache`、`proxy` | 核心栈 |
| `worker` | `cf-worker` | 组织同步、Meilisearch 索引和外部资料源扫描等周期任务 |
| `search` | `seasearch`、`meilisearch` | 同时提供默认 SeaSearch 与可选 Meilisearch；由 `CF_PROVIDER_SEARCH` 选择查询路径 |
| `metadata` | `cloudfile-metadata` | 官方 Metadata Server；当前默认镜像是兼容验证用 `14.0.3-testing`，生产必须固定已验版本 |
| `ai` | `seafile-ai` | 官方按需 AI 组件；需自备 LLM 配置，真实端到端仍待验证 |
| `office` | `onlyoffice` | OnlyOffice Document Server |
| `convert` | `seadoc` | SeaDoc 转换与导出 |
| `s3` | `minio`、`minio-init` | 仅用于本地 S3/多存储验证，不是生产对象存储方案 |
| `full` | `worker`、`search`、`metadata`、`ai`、`office`、`convert` 的服务 | 启动应用扩展组件；**不包含**仅属于 `s3` profile 的 MinIO |

启动示例：

```bash
docker compose --profile worker up -d
docker compose --profile search up -d
docker compose --profile metadata up -d
docker compose --profile full up -d
```

profile 只决定容器是否启动，能力开关仍需在 `.env` 中显式设置。不要在 Compose 文件中给 profile 专属变量加 `:?`：Compose 会在 profile 未启用时仍解析整份文件。

## 功能开关与配置刷新

所有 `CF_ENABLE_*` 在 [`.env.example`](.env.example) 中默认为 `false`。全部关闭时应走原生 CE 路径；该性质由 `tests/e2e/smoke.py` 与 `tests/e2e/baseline.py` 分别验证原生行为和扩展框架已加载但未启用。

修改 `.env` 后运行：

```bash
docker compose up -d
```

`scripts/scripts_14.0/start.py` 每次启动都会调用配置写入逻辑，将带 `CF_BEGIN`/`CF_END` 标记的区块幂等写入 Seafile 配置，区块外的人工配置不应被覆盖。

## 常用能力

### 目录 ACL

```bash
CF_ENABLE_DIR_ACL=true docker compose up -d
```

Seahub 负责界面和 API，seaf-server 是权限终判层。规则、入口覆盖和限制见 [`../../docs/acl-semantics.md`](../../docs/acl-semantics.md)。

```bash
curl -X POST -H "Authorization: Token $TOKEN" \
  -F path=/受限 -F subject_type=user -F subject=b@example.com \
  -F permission=r \
  "https://cloudfile.example.com/api/v2.1/cloudfile/repos/$REPO_ID/dir-acl/"
```

### SSO 与组织映射

CloudFile 默认以 Authentik 作为企业身份入口，当前稳定参考版本为 `2026.5.6`；实现复用 Seafile CE 的通用 OAuth2/OIDC Authorization Code，并没有 Authentik 专用协议或 preset。`CF_ENABLE_SSO=true` 后，CloudFile 新增的目录 provider 可将外部组织结构同步到本地组；当前只实现 `static` 与 `external-service`，不是直连 Authentik 的组织目录。启用周期同步时同时启动 `worker` profile。端点、字段映射、登录/登出、首次用户和恢复方式见 [`../../docs/features/sso-authentik.md`](../../docs/features/sso-authentik.md)。

LDAP、ADFS/SAML、Shibboleth 是 CE 兼容路径，不是 CloudFile 的默认企业入口；角色和 2FA 也是 CE 已有设置。CloudFile 只将它们暴露为可重建的 `.env` 配置：

- LDAP：设置 `CF_LDAP_ENABLED=true` 并填写连接、Base DN、管理员 DN、密码与登录属性。
- ADFS/SAML：设置 `CF_ADFS_ENABLED=true`，配置元数据 URL 和属性映射，并将 `sp.key`、`sp.crt` 放入 `data/seafile/seahub-data/certs/`。
- Shibboleth：默认 Caddy 不提供 Shibboleth SP；必须使用可信认证代理清理客户端身份头后再注入远程用户头。
- 2FA：设置 `CF_TWO_FACTOR_ENABLED=true`；角色权限使用对应 JSON 变量增量配置。

### 检索

默认 SeaSearch：

```bash
docker compose --profile search up -d
```

在 `.env` 中设置 `CF_ENABLE_SEARCH=true`、SeaSearch 首次管理员凭据，并令 `CF_SEASEARCH_TOKEN` 为 `用户名:密码` 的 Base64。若改用 Meilisearch，另设 `CF_PROVIDER_SEARCH=meilisearch`、`MEILI_MASTER_KEY` 和同值的 `CF_MEILISEARCH_API_KEY`，并启动 `worker` profile。限制见 [`../../docs/features/search.md`](../../docs/features/search.md)。

### 属性与标签

```bash
docker compose --profile metadata up -d
```

在 `.env` 中设置 `CF_ENABLE_METADATA=true`；标签还需 `CF_ENABLE_TAGS=true`。前端、REST API 与 seafevents 投喂链路复用 CE，`cloudfile-metadata` 提供外部存储/查询服务。生产环境必须将 `CF_METADATA_IMAGE` 固定到已验证镜像。

### S3 与多存储

设置 `CF_ENABLE_S3_STORAGE=true` 后，按 [`.env.example`](.env.example) 提供三类 bucket 和凭据；多存储还需 `SEAF_SERVER_STORAGE_TYPE=multiple` 与 `CF_STORAGE_CLASSES_JSON`。本地验证可启动 MinIO：

```bash
docker compose --profile s3 up -d
```

MinIO 的示例凭据只能用于本地测试。对象布局、迁移、GC/FSCK 约束见 [`../../docs/features/storage-backends.md`](../../docs/features/storage-backends.md)。

### 外部资料源

CloudFile 不负责挂载 SMB/NFS。运维先在宿主机挂载，再只读 bind mount 到 `CF_EXTERNAL_SOURCES_ROOTS` 允许的容器路径；CloudFile 负责登记、授权、浏览与下载。具体边界见 [`../../docs/features/external-sources.md`](../../docs/features/external-sources.md)。

### 文件锁、关注、转换与导出

```bash
CF_ENABLE_FILE_LOCK=true CF_ENABLE_WATCH=true docker compose up -d
```

SeaDoc 转换/导出需先生成并持久化 `JWT_PRIVATE_KEY`，再启用开关与 profile：

```bash
openssl rand -hex 32
docker compose --profile convert up -d
```

OnlyOffice 另需 `ONLYOFFICE_JWT_SECRET`、`CF_ENABLE_ONLYOFFICE=true` 与 `office` profile。如 Document Server 无法访问公网文件地址，可用 `ONLYOFFICE_FILE_SERVER_ROOT` 指定它可达的内部 fileserver 根地址（例如 `http://cloudfile/seafhttp`）。完整锁与写回限制见 [`../../docs/features/file-collaboration.md`](../../docs/features/file-collaboration.md)。

## TLS

`CADDY_TLS=internal` 使用 Caddy 内部 CA，适合本地或内网验证。将其设为邮箱地址会请求公开证书，要求 `SEAFILE_SERVER_HOSTNAME` 的 DNS 和公网 80/443 连通。实际域名、证书与 DNS 由部署环境负责，仓库无法验证。

## 持久化与备份

所有本地卷位于 `data/`：

```text
data/
├── db/             MariaDB
├── redis/          Redis
├── seafile/        资料库、配置和日志
├── caddy/          Caddy 证书与状态
├── seadoc/         SeaDoc 数据
├── seasearch/      SeaSearch 索引
├── meilisearch/    Meilisearch 索引
├── minio/          本地测试对象
└── onlyoffice/     OnlyOffice 数据与日志
```

核心业务备份至少覆盖 `data/db/` 与 `data/seafile/`。启用外部状态组件后，还需按恢复目标备份对应目录或确认其可重建；生产 S3/SMB/NFS 数据不在本地 `data/` 内。执行一致性备份前停止写入，并验证数据库与对象存储的恢复流程。

## 验证

静态检查：

```bash
cp .env.example .env
docker compose config --quiet
for p in search office convert worker metadata ai s3 full; do
  docker compose --profile "$p" config --services
done
```

本地整机门禁：

```bash
../../tools/verify-local.sh preflight
../../tools/verify-local.sh
../../tools/verify-local.sh cap acl
```

能力名与门禁映射以 [`../../tools/verify-local.sh`](../../tools/verify-local.sh) 的 `CAPABILITIES` 表为准。AI 当前没有登记在该表中，因此不能标记为已整机验证。
