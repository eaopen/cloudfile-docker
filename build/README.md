<!-- generated-by: gsd-doc-writer -->
# CloudFile 14.0 构建

> **用途**：说明如何从锁定的源码版本构建 CloudFile 发行包；镜像构建见 [`../image/cloudfile_14.0/docker-build.sh`](../image/cloudfile_14.0/docker-build.sh)。
> **适用版本**：CloudFile `14.0.0-cf.0`，基于 Seafile CE 14 源码重构。
> **状态**：当前有效；构建清单以 [`../release.yaml`](../release.yaml) 为准。

## 构建边界

- **复用 Seafile CE**：`seafobj`、`seafdav`、`seafevents`、`libsearpc` 与 `libevhtp` 使用 `release.yaml` 中锁定的上游提交。
- **CloudFile 新增**：`cloudfile-server`、`cloudfile-hub` 使用清单指定的 fork/ref，并组装 CloudFile 扩展和运行脚本。
- **外部依赖**：构建过程会从清单记录的 Git 仓库拉取源码，并从 `nodejs.org` 安装 `CF_NODE_VERSION` 指定的 Node.js；离线环境需预先提供等价依赖源。

Seafile 上游未发布 CE 14 分支、CE 14 tag 或 CE 14 镜像，因此本仓不能复用完整的官方 CE 14 发行包。所有上游组件提交与 CloudFile fork ref 都从 `release.yaml` 读取，不在脚本中写死。

## 前置条件

- Linux `amd64` 或 `arm64`；推荐 Ubuntu 24.04。
- Docker，可运行 Ubuntu 24.04 构建容器。
- 可访问 `release.yaml` 中的源码仓库和 Node.js 下载地址。
- 完整构建会安装系统依赖并占用较多磁盘空间；不要在生产容器内执行。

## 构建发行包

在仓库根目录运行：

```bash
./build/cloudfile_14.0/build-in-docker.sh 14.0.0-cf.0
```

该脚本在 Ubuntu 24.04 容器内调用 `cloudfile-build.sh`。产物位于：

```text
build/cloudfile_14.0/seafile-server-14.0.0-cf.0/
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

镜像名的仓库部分取自 `release.yaml`，tag 使用命令行版本号；默认生成 `cloudfile/cloudfile:14.0.0-cf.0`。

## 快速校验

```bash
python3 build/cloudfile_14.0/read-manifest.py release.yaml forks.cloudfile_hub.ref
bash -n build/cloudfile_14.0/cloudfile-build.sh
bash -n build/cloudfile_14.0/build-in-docker.sh
bash -n image/cloudfile_14.0/docker-build.sh
```

完整的本地基线构建与整机验证入口是：

```bash
./tools/verify-local.sh
```
