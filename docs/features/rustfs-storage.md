# RustFS 默认 S3 与多存储集成

分支：`feature/multi-storage-rustfs`。2026-10-13 从远端最新 `dev` 建立：
Server `04baa71`、Hub `7c31627`、Docker `8de2f27`。本特性独立验收后再合入 `dev`。

## 职责与默认值

CloudFile 管理文件、目录、权限、版本和 Seafile commit/FS/block 对象；RustFS
负责对象持久化。存储类通过 `backend=s3`、endpoint、bucket 和凭据解耦两者。
继续使用现有 C S3 和 Go `minio-go/v7` 客户端；客户端库名称不代表必须部署 MinIO。

`s3` Compose profile 默认启动 RustFS，参考镜像固定为 `rustfs/rustfs:1.0.1`，
可用 `RUSTFS_IMAGE` 指定经过验证的版本或 digest。MinIO 保留在 `minio` profile。
本地、RustFS、MinIO 存储类可以并存。

“默认 S3”指默认部署的 S3 服务，不改变原有资料库的默认存储类。
新安装仍保留 `legacy-default` 和 `auto-local`；已有 `RepoStorageId`、bucket、凭据
和默认类不自动变更。不得将原 MinIO 数据目录直接挂给 RustFS。

## 新安装增加 RustFS 类

先按 Compose 主文档建立 `.env`，沿用默认的 auto-library-storage overlay。
以下命令在 `deploy/compose` 执行，示例凭据仅用于本地测试：

```bash
export RUSTFS_ACCESS_KEY=rustfsadmin
export RUSTFS_SECRET_KEY=change-this-rustfs-password
export S3_KEY_ID="$RUSTFS_ACCESS_KEY" S3_SECRET_KEY="$RUSTFS_SECRET_KEY"
export S3_HOST=rustfs:9000 S3_USE_HTTPS=false
mkdir -p data/rustfs
docker compose --profile s3 run --rm --no-deps --user 0 \
  --entrypoint chown rustfs 10001:10001 /data
docker compose --profile s3 up -d rustfs
docker compose --profile s3 run --rm rustfs-init
python3 ../../tools/storage-class-config.py --fresh --output data/storage-rustfs.json
```

将 `.env` 的 `COMPOSE_FILE` 改为以下顺序，生成的 override 必须最后加载：

```dotenv
COMPOSE_FILE=docker-compose.yml:docker-compose.auto-library-storage.yml:data/storage-rustfs.json
```

执行 `docker compose up -d cloudfile`。需要后台任务时再启动相应 worker profile。
生成文件权限为 `0600`，包含凭据，放在被 Git 忽略的 `data/` 下。
工具只追加非默认 `rustfs-standard`，同时为 server/worker 设置相同的存储类；
不会覆盖已有输出文件，不输出密钥。通过现有 CloudFile 存储类 API 选择该类建库。
启动 profile 本身不会改变资料库路由。

RustFS 初始化使用同版本镜像内的 curl/SigV4 创建三个 bucket，支持重复执行，
失败后有界重试并返回非零；不依赖 MinIO 管理服务或 `mc` 下载。
使用外部对象服务时直接配置 endpoint，提前创建 bucket，无需启动本地 profile。
示例 HTTP 仅用于内部 Docker 网络；外部 TLS 端点设置 `S3_USE_HTTPS=true`。

## 已有部署与 MinIO 共存

从正在使用的 `seafile_storage_classes.json` 取得真实配置作为 `--base`。
不要对已有部署使用 `--fresh`，不要用示例数组代替现有数组。

```bash
python3 ../../tools/storage-class-config.py \
  --base data/existing-storage-classes.json --output data/storage-rustfs.json
```

工具保留全部旧类和默认值，发现重复 ID 则拒绝。既有 Compose 文件链保持原顺序，
仅追加生成的 override。原来是单一 S3 的部署，需要先把该 S3 原配置完整表示为
默认存储类，核对 C/Go/worker 读到同一配置后再启用多存储；工具不猜测原配置。

MinIO 部署继续使用原 `S3_HOST`、凭据和类 ID，启动命令改为：

```bash
docker compose --profile minio up -d minio
docker compose --profile minio run --rm minio-init
```

新建 MinIO 类时使用 `--provider minio`，并显式设置对应 `S3_*` 环境变量。
同时部署两种服务时，设置不同宿主机端口，例如 `MINIO_API_PORT=19000`、
`MINIO_CONSOLE_PORT=19001`；容器间端点仍为 `minio:9000` 与 `rustfs:9000`。
更新模板不会重写现有 `.env`。原来启用 `COMPOSE_PROFILES=s3` 的 MinIO 部署，
升级时必须改为 `minio`；仅有 profile 的切换不包含任何数据迁移。

已有库迁移必须沿用停服后的 `seaf-storage-migrate`，完成校验再切换映射。
回滚不能仅删除已有库正在引用的存储类：先反向迁移并校验，再撤去对应服务。
CloudFile 在线 bucket 不启用自动过期删除、强制 Object Lock 或对象版本保留策略，
避免与 Seafile GC 冲突。对象存储复制不代替数据库与对象的一致恢复点。

## 验证与验收边界

本分支本地验证：

- RustFS 1.0.1 和本机 MinIO 镜像：Go 三类对象读写、零字节、72 MiB 未知长度流、重复写、库隔离、
  多存储路由、未知类拒绝；C commit/FS/block 读写、删除、复制、分页枚举及错误语义。
- MinIO 回归镜像 ID：`sha256:8f08aee614800a237906bd48114d733e5ac5bfac4ccdf731f141b0e880d7a253`。
- RustFS 实际 Compose service 定义：隔离容器中初始化三个 bucket，重复初始化成功。
- 配置测试覆盖旧 MinIO/local 保留、重复 ID 拒绝、文件权限、防覆盖、特殊字符
  Compose 转义、server/worker 一致性，以及原默认本地部署回归。
- 三仓 `tools/run-checks.sh` 全部通过；Go build/vet 通过。完整 CloudFile HTTP/编辑回传/历史版本、GC/FSCK 与恢复的
  RustFS 业务 E2E 尚未完成，不将后端测试表述为生产迁移验收。

两种服务共用原有业务门禁，默认验证 RustFS：

```bash
./tools/verify-local.sh cap storage
CF_STORAGE_TEST_PROVIDER=minio ./tools/verify-local.sh cap storage
```

需要分别运行在隔离 stage；门禁会停测试服务并迁移测试库。
底层测试命令与 `CF_S3_TEST_*` 参数见 Server `README.testing.md`。

依据：[RustFS Docker 部署](https://docs.rustfs.com/en/installation/container/docker)、
[官方镜像版本](https://hub.docker.com/r/rustfs/rustfs/tags)。
