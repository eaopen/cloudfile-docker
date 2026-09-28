# CE14 Docker 构建方案

## 日常开发

```sh
build/seafile_14.0/build-in-docker.sh
build/seafile_14.0/build-local-image.sh
```

默认取开发机架构（macOS ARM 为 `linux/arm64`，x86 为 `linux/amd64`），仍生成原路径 `seafile-server-14.0.8`、原运行依赖标签 `cloudfile/runtime-base:14.0.8-local` 和原应用标签 `cloudfile/cloudfile:14.0.8-v0.2-local`。预制编译工具链、ccache/Go/pip 下载缓存、`thirdpartdir` 和运行依赖镜像继续共用。首次构建运行依赖镜像，后续只构建脚本与应用包两层。自定义 `CLOUDFILE_RUNTIME_BASE` 须与目标版本、架构一致。

重新构建同名镜像不会改变已运行容器。构建脚本只创建镜像，不重建容器或修改 Compose 服务；现有部署 Compose 默认仍指向 RC 镜像。显式指定平台时自动使用带架构的本地标签，使两种架构的镜像可以并存；也可传入自定义标签。开发验证可使用 `python3 tests/verify.py docker --image cloudfile/cloudfile:14.0.8-v0.2-local`。若部署配置显式使用 `-local` 标签，后续重新部署前应核对其镜像 ID 和平台。

## 指定目标架构

```sh
CF_PLATFORM=linux/amd64 CF_BASE_IMAGE=your-amd64-build-base:tag \
  build/seafile_14.0/build-in-docker.sh
CF_PLATFORM=linux/amd64 build/seafile_14.0/build-local-image.sh
```

`CF_PLATFORM` 只接受 `native`、`linux/arm64`、`linux/amd64`。不设置或设为 `native` 保持旧包路径、依赖标签和应用标签；显式指定平台时三者均使用架构后缀，例如应用镜像 `cloudfile/cloudfile:14.0.8-v0.2-amd64-local`。编译阶段要求预制工具链镜像与目标架构相同；跨架构在本地运行会走模拟，通常比目标架构原生构建慢。镜像组装阶段明确传入 `--platform`，并检查包内 C/Go ELF 架构与运行依赖镜像架构；不匹配立即失败。旧的无架构后缀发行包仍可作为输入，但只有架构校验通过才会使用。要从 Mac 交付 Linux AMD64，优先在 AMD64 builder 上编译并将校验过的包传给组装阶段，或用已准备的 AMD64 工具链进行模拟编译。

显式指定平台的编译包按架构分别存放，避免一次 AMD64 构建覆盖默认包；运行依赖镜像相应使用 `cloudfile/runtime-base:14.0.8-<架构>-local`，防止交替构建时错用。依赖不按开发/生产拆分。`CF_CACHE_DIR` 可继续指向已有持久缓存；ccache、Go cache 按编译输入区分，Python 已安装依赖的复用键包含需求清单、解释器、架构和编译工具链镜像 ID。更新依赖时显式设置 `CLOUDFILE_REFRESH_RUNTIME_BASE=true`，正常开发无需刷新。

## 多架构发布

如果部署端需要一个同时支持 ARM64/AMD64 的标签，先分别在对应架构上生成并验证发行包和应用镜像，再把两个单架构镜像推送到仓库，最后用 `docker buildx imagetools create -t <发布标签> <arm64-镜像> <amd64-镜像>` 创建清单。单个本地发行包不能直接生成多架构镜像；清单必须指向两个分别编译的镜像。部署端拉取清单时 Docker 会按 Linux 主机架构选择对应镜像。发布前逐架构运行 runtime 验证，并检查 `docker buildx imagetools inspect <发布标签>` 的平台列表。
