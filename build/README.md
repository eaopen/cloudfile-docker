<!-- generated-by: gsd-doc-writer -->
# CloudFile 14.0 构建

> **用途**：说明如何从锁定的源码版本构建 CloudFile 发行包；镜像构建见 [`../image/cloudfile_14.0/docker-build.sh`](../image/cloudfile_14.0/docker-build.sh)。
> **适用版本**：CloudFile `14.0.0-cf.0`，基于 Seafile CE 14 源码重构。
> **状态**：当前有效；构建清单以 [`../release.yaml`](../release.yaml) 为准。

## 构建边界

- **复用 Seafile CE**：`seafobj`、`seafdav`、`seafevents`、`libsearpc` 与 `libevhtp` 使用 `release.yaml` 中锁定的上游提交。
- **CloudFile 新增**：`cloudfile-server`、`cloudfile-hub` 使用清单指定的 fork/ref，并组装 CloudFile 扩展和运行脚本。
- **基础环境**：APT、固定版本 Node 和镜像运行时 Python 包只在 `Dockerfile.base` 中安装；日常应用镜像构建不访问公网。
- **源码依赖**：发行包首次构建仍会拉取清单记录的 Git 源码以及项目级 PyPI/npm 依赖；已有 `build/cloudfile_14.0/src/` 缓存时才可复用。第二个 deps 镜像暂不引入，避免在 MVP 阶段维护两套基线。

Seafile 上游未发布 CE 14 分支、CE 14 tag 或 CE 14 镜像，因此本仓不能复用完整的官方 CE 14 发行包。所有上游组件提交与 CloudFile fork ref 都从 `release.yaml` 读取，不在脚本中写死。

## 前置条件

- Linux `amd64` 或 `arm64`；推荐 Ubuntu 24.04。
- Docker，并已加载 `release.yaml` 指定的 `build_base_image`。
- 首次构建发行包时可访问 `release.yaml` 中的源码仓库、PyPI 和 npm，或已准备完整源码与依赖缓存。
- 完整构建占用较多磁盘空间；不要在生产容器内执行。

## 准备基础镜像

只在网络正常的 Linux/CI 机器运行：

```bash
./image/cloudfile_14.0/base-build.sh
```

默认构建 `linux/amd64` 的 `cloudfile-build-base:ce14-v2`。通过文件传入目标机器：

```bash
docker save cloudfile-build-base:ce14-v2 |
  zstd -T0 -10 -o cloudfile-build-base-ce14-v2.tar.zst

zstd -dc cloudfile-build-base-ce14-v2.tar.zst |
  docker load
```

长期使用内网 Registry 时，先把基础镜像推入内网，再在构建前显式拉取并覆盖名称：

```bash
docker pull registry.internal/cloudfile/build-base:ce14-v2
CF_BASE_IMAGE=registry.internal/cloudfile/build-base:ce14-v2 \
  ./image/cloudfile_14.0/docker-build.sh 14.0.0-cf.0
```

脚本不会自动拉取缺失的基础镜像。使用独立 `docker-container` BuildKit builder 时，
`docker load` 的镜像可能不可见；离线构建使用 Docker 默认 builder，长期构建使用内网 Registry。

## 构建发行包

在仓库根目录运行：

```bash
./build/cloudfile_14.0/build-in-docker.sh 14.0.0-cf.0
```

该脚本在预制基础镜像内调用 `cloudfile-build.sh`，不再重复执行 APT 或安装 Node。产物位于：

```text
build/cloudfile_14.0/seafile-server-14.0.0-cf.0/
```

C/Go 编译并行度默认跟随机器核数（`nproc`），可用 `CF_BUILD_JOBS` 覆盖：

```bash
CF_BUILD_JOBS=8 ./build/cloudfile_14.0/build-in-docker.sh 14.0.0-cf.0
```

增量编译缓存（ccache、Go module/build cache、npm/pip cache）默认落在
`build/cloudfile_14.0/.cache/`，跨构建持久；C 代码只改一行时 ccache 让 `make`
只重编一个目标文件，Go/npm 依赖也不再重复下载。CI 用 `actions/cache` 复用同一目录。
可用 `CF_CACHE_DIR` 把缓存根目录改到别处。

前端依赖树按 package/lockfile、Node/npm ABI 和平台生成指纹。输入不变时保留
`node_modules`，避免重复执行 `npm ci`；CI 只保存约 60 MiB 的 Babel/ESLint
loader 缓存，不上传约 1 GiB 的完整依赖树。frontend 层指纹只包含 Seahub 及构建期
实际读取的 server/libsearpc Python 树，因此只改 C/Go 不会再触发 webpack。

需要单独重测某一层时，不要使用会同时重跑前端和 C/Go 的
`CF_FORCE_REBUILD=1`：

```bash
# 只重跑 webpack / collectstatic
CF_FORCE_FRONTEND_REBUILD=1 ./build/cloudfile_14.0/build-in-docker.sh 14.0.0-cf.0

# 只重跑 C/Go/打包；前端仍从产物缓存恢复
CF_FORCE_DIST_REBUILD=1 ./build/cloudfile_14.0/build-in-docker.sh 14.0.0-cf.0
```

也可在已满足依赖的 Linux 主机直接运行：

```bash
./build/cloudfile_14.0/cloudfile-build.sh 14.0.0-cf.0
```

## 本地源码覆盖

默认 ref 取自 `release.yaml`。验证尚未合并的并排 checkout 时，可覆盖仓库地址和 ref：

```bash
CF_SERVER_URL=../cloudfile-server \
CF_SERVER_REF=dev \
CF_HUB_URL=../cloudfile-hub \
CF_HUB_REF=dev \
./build/cloudfile_14.0/build-in-docker.sh 14.0.0-cf.0-local
```

其他上游组件也支持脚本中声明的 `CF_*_REF` 覆盖变量；发布构建应回到 `release.yaml` 的固定值。

## 构建镜像

发行包完成后运行：

```bash
./image/cloudfile_14.0/docker-build.sh 14.0.0-cf.0
```

镜像名的仓库部分取自 `release.yaml`，tag 使用命令行版本号；默认生成 `cloudfile/cloudfile:14.0.0-cf.0`。该步骤要求基础镜像已在本地，固定使用 `--pull=false --network=none`，不会访问 Docker Hub、APT、PyPI 或 npm。

## 快速校验

```bash
python3 build/cloudfile_14.0/read-manifest.py release.yaml forks.cloudfile_hub.ref
bash -n build/cloudfile_14.0/cloudfile-build.sh
bash -n build/cloudfile_14.0/build-in-docker.sh
bash -n image/cloudfile_14.0/base-build.sh
bash -n image/cloudfile_14.0/docker-build.sh
```

完整的本地基线构建与整机验证入口是：

```bash
./tools/verify-local.sh
```
