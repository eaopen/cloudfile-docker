# 部署

> 用途：部署和维护当前 CloudFile Compose 栈
> 适用版本：Seafile CE 14 参考基线，镜像版本以 `release.yaml` 为准
> 当前状态：有效；生产启用可选能力前须核对功能矩阵

## 前提

- Linux 主机与 Docker Compose v2；镜像架构必须与主机一致。
- **双架构约定：生产 amd64，本地（Apple Silicon）测试 arm64。** 构建脚本按宿主
  自动选架构（见下），生产 amd64 镜像在 CI（amd64 原生）出，本地 mac 只出 arm64。
- 可解析的 `SEAFILE_SERVER_HOSTNAME`，以及持久化目录的备份策略。
- 生产环境不得沿用 `.env.example` 中的示例密码、MinIO 凭据或 API key。

## 架构自动检测

`tools/build-platform.sh` 是三个构建脚本（base-build、build-in-docker、
docker-build）共享的架构唯一来源。默认跟随宿主、原生优先：

| 宿主 | 自动平台 | 说明 |
|---|---|---|
| macOS Apple Silicon | `linux/arm64` | 原生快；Rosetta 2 终端也正确判回 arm64 |
| macOS Intel / Linux x86_64 | `linux/amd64` | 原生 |
| Linux aarch64 | `linux/arm64` | 原生 |
| Windows（Docker Desktop） | `linux/amd64` | Linux VM 是 amd64 |

`CF_PLATFORM` 在任何脚本上覆盖自动检测（只收 `linux/amd64`/`linux/arm64`）。
跨架构构建（mac 上出 amd64）走 QEMU 模拟，C 编译慢 5~10 倍，仅用于验证，不用于发布。

## 启动核心栈

```bash
cd deploy/compose
cp .env.example .env
```

编辑 `.env`，至少设置站点主机名、管理员账号以及数据库、Redis、Caddy 所需密钥，
然后验证并启动：

```bash
docker compose config --quiet
docker compose up -d
docker compose ps
docker compose logs -f cloudfile
```

核心栈包括 `cloudfile`、`db`、`cache` 和 `proxy`。首次启动会初始化数据库与 Seafile
配置；`scripts/scripts_14.0/start.py` 在每次启动时重写带 `CF_BEGIN`/`CF_END` 标记的
CloudFile 配置块，并幂等应用 `cloudfile.sql`。

## 可选 profile

| profile | 服务 | 使用条件 |
|---|---|---|
| `s3` | `minio`、`minio-init` | 仅本地 MinIO 集成验证；生产通常连接外部 S3 |
| `search` | `seasearch`、`meilisearch` | 需设置检索开关并选择实际 provider |
| `metadata` | `cloudfile-metadata` | 需 `CF_ENABLE_METADATA=true`；镜像 tag 必须单独验收 |
| `office` | `onlyoffice` | 需启用对应协作能力和稳定 JWT 密钥 |
| `convert` | `seadoc` | 需启用转换/导出并配置 JWT |
| `worker` | `cf-worker` | 组织同步、Meilisearch 索引等周期任务 |
| `ai` | `seafile-ai` | 复用官方 Seafile AI 并外接 LLM；当前为验证中，不代表全链路已验收 |
| `full` | 多个可选服务 | 只启动服务；不会自动把所有功能标记为已验证 |

示例：

```bash
docker compose --profile worker up -d
```

`docker compose --profile <name> up` 只启动容器。能力是否生效还取决于 `.env` 中的
`CF_ENABLE_*`、provider、凭据和依赖配置；以[配置参考](configuration.md)为准。

## TLS

`CADDY_TLS=internal` 使用内部 CA，适合隔离环境；客户端必须显式信任该 CA。使用公开
证书时，主机名需正确解析，且 ACME 所需端口可达。不要在生产中通过关闭证书验证掩盖
配置错误。

## 升级

1. 备份数据库、`deploy/compose/data/seafile/` 和所有外部对象存储配置。
2. 阅读 `release.yaml` 的版本与 schema 变化，并确认三个 fork 的提交一致。
3. 拉取或构建新镜像，先运行 `docker compose config --quiet`。
4. 在维护窗口更新栈，观察 `cloudfile`、`cf-worker` 和可选服务日志。
5. 执行 CE 冒烟和本次启用能力的 E2E；失败时保留旧镜像与源对象，不执行不可逆清理。

`cloudfile.sql` 使用 `IF NOT EXISTS` 只能创建当前缺失对象，不等于完整 schema 迁移框架。
`release.yaml` 中 `database_schema` 变化时必须按对应发布说明处理；当前文档不推断未来迁移步骤。

## 备份与恢复

业务恢复至少同时覆盖：

- MariaDB 中的 `ccnet_db`、`seafile_db`、`seahub_db`；
- `data/seafile/` 中的配置、密钥、日志和本地对象；
- S3/MinIO 的 commit、FS、block 三类 bucket；
- 可选组件自己的数据目录和密钥。

> **警告：** 只复制 `data/db/` 与 `data/seafile/` 不能覆盖外部 S3、MinIO、
> metadata-server、Meilisearch 或 OnlyOffice 的数据。文件级复制前应停写或使用各组件支持的
> 一致性快照；未经恢复演练的备份不能视为可恢复。

## 验证

轻量检查：

```bash
./tools/run-checks.sh
```

完整构建和容器 E2E 需要 Linux 与足够磁盘空间：

```bash
./image/cloudfile_14.0/base-build.sh  # 仅在网络正常机器或基础镜像版本变化时
./build/cloudfile_14.0/cloudfile-build.sh 14.0.0-cf.0
./image/cloudfile_14.0/docker-build.sh 14.0.0-cf.0
./tools/verify-local.sh
```

能力门禁使用 `./tools/verify-local.sh cap <能力>`。门禁文件存在不等于已在当前提交运行；
[功能矩阵](feature-matrix.md)会区分代码、自动化门禁和已知验证记录。
