# 部署

> 用途：部署和维护当前 CloudFile Compose 栈
> 适用版本：Seafile CE 14 参考基线，镜像版本以 `release.yaml` 为准
> 当前状态：有效；生产启用可选能力前须核对功能矩阵

## 前提

- Linux 主机与 Docker Compose v2；镜像架构必须与主机一致。
- 构建默认跟随宿主架构；部署与镜像架构须一致。跨架构构建需单独验证，不能将 Apple Silicon 本地测试视为 amd64 实机验收。
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
| Windows（Docker Desktop） | 以 Docker Linux VM 架构为准 | 核对目标架构后构建 |

`CF_PLATFORM` 在任何脚本上覆盖自动检测（只收 `linux/amd64`/`linux/arm64`）。
跨架构构建可能使用 QEMU 模拟；耗时取决于环境。正式发行应在目标架构验证。

## 构建与镜像仓库

通用构建步骤见 [构建说明](../build/README.md)。按 `release.yaml` 固定来源与目标架构，验证产物后再推送自己的镜像仓库；使用不可变版本或 digest，不以 `latest` 作为升级依据。

`tools/release-dev162.sh` 是带历史环境默认值的发布辅助脚本。若复用它，必须显式设置 `CF_NEXUS_REGISTRY`、核对基础镜像和依赖源，不能直接使用默认目标。它可能拉取源码、编译和推送；不是只读验证命令。具体环境地址、凭据与发布记录在私有运维资料维护。

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

默认栈包括 `cloudfile`、`db`、`cache`、`proxy`、`cf-worker` 和 `cloudfile-metadata`。首次启动会初始化数据库与 Seafile
配置；`scripts/scripts_14.0/start.py` 在每次启动时重写带 `CF_BEGIN`/`CF_END` 标记的
CloudFile 配置块，并幂等应用 `cloudfile.sql`。

## 可选 profile

| profile | 服务 | 使用条件 |
|---|---|---|
| `s3` | `rustfs`、`rustfs-init` | 当前 RustFS 特性分支的可选服务；完整业务 E2E 待验收 |
| `minio` | `minio`、`minio-init` | 兼容 MinIO；旧部署升级须核对 profile 名称 |
| `search` | `seasearch`、`meilisearch` | 需设置检索开关并选择实际 provider |
| 默认服务，无独立 profile | `cloudfile-metadata` | 按配置选择镜像；核对 metadata 与 Hub 的 JWT 及版本兼容 |
| `office` | `onlyoffice` | 需启用对应协作能力和稳定 JWT 密钥 |
| `convert` | `seadoc` | 需启用转换/导出并配置 JWT |
| 默认服务，无独立 profile | `cf-worker` | 运行已配置的目录、组织、索引等周期任务 |
| `ai` | `seafile-ai` | 复用官方 Seafile AI 并外接 LLM；当前为验证中，不代表全链路已验收 |
| `migration` | `cf-migration` | 按迁移说明提供来源、目标和受限凭据 |
| `full` | search、office、convert、ai 对应服务 | 不含 s3/minio/migration；不会自动证明能力可用 |

示例：

```bash
docker compose up -d      # 核心栈，已含 cf-worker 与 cloudfile-metadata
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
- 所选 S3 后端的 commit、FS、block 三类 bucket；
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
