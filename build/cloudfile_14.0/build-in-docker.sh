#!/bin/bash
#
# 在预制构建基础镜像里跑 cloudfile-build.sh，不在宿主机上装任何东西。
#
# 基础镜像已经包含 C/Go/Python/Node 工具链，因此日常源码构建不再执行 APT
# 或下载 Node。Git、PyPI 和 npm 是否联网仍取决于源码与项目依赖缓存是否齐全。
#
#   ./build-in-docker.sh 14.0.0-cf.0
#   CF_HUB_REF=feature/x ./build-in-docker.sh 14.0.0-cf.0-dev
#   CF_PLATFORM=linux/amd64 ./build-in-docker.sh 14.0.0-cf.0
#
# 产物落在 build/cloudfile_14.0/seafile-server-<version>/，接着可以：
#   ../../image/cloudfile_14.0/docker-build.sh <version>
#
# 架构说明：默认跟随宿主机。Apple Silicon 上原生构建 arm64 很快；要出 amd64
# 镜像就设 CF_PLATFORM=linux/amd64，走 QEMU 模拟，慢很多但可用。上游的 arm
# 与 x86 Dockerfile 完全相同，所以镜像层面不需要区分。

set -e

if [[ $# != 1 ]]; then
    echo ''
    echo 'Usage: ./build-in-docker.sh $version'
    echo ''
    exit 1
fi

version=$1
here=$(cd "$(dirname "$0")" && pwd)
repo_root=$(cd "$here/../.." && pwd)
base_image=${CF_BASE_IMAGE:-$(python3 "$here/read-manifest.py" \
    "$repo_root/release.yaml" build_base_image)}

# 必须显式指定平台。不指定的话 Docker 会沿用本地基础镜像的架构——如果那是
# amd64 而宿主是 Apple Silicon，构建就会静默地跑在 QEMU 模拟下，
# 慢一个数量级却没有任何提示。默认跟随宿主机。
if [[ -z ${CF_PLATFORM:-} ]]; then
    case "$(uname -m)" in
        arm64|aarch64) CF_PLATFORM=linux/arm64 ;;
        x86_64)        CF_PLATFORM=linux/amd64 ;;
        *) echo "无法识别的宿主架构：$(uname -m)，请显式设置 CF_PLATFORM" >&2; exit 2 ;;
    esac
fi
platform=$CF_PLATFORM
platform_arg=(--platform "$platform")

if ! docker info >/dev/null 2>&1; then
    echo "Docker 不可用。请先启动 Docker Desktop / OrbStack / colima。" >&2
    exit 2
fi

if ! docker image inspect "$base_image" >/dev/null 2>&1; then
    echo "构建基础镜像未加载：$base_image" >&2
    echo "请先在网络正常的机器运行 image/cloudfile_14.0/base-build.sh，" >&2
    echo "再通过 docker save/load 或内网 Registry 导入。" >&2
    exit 2
fi

# 基础镜像架构必须与请求的 platform 一致。Apple Silicon 上若加载的是 amd64
# 基础镜像，默认跟随宿主机的 arm64 会在真正跑起来时被 docker 拒掉（platform
# does not match）。这里用一次秒级的 inspect 提前拦截，别让一个 QEMU 构建
# 跑了几十分钟才在别处暴露错配。
image_arch=$(docker image inspect --format '{{.Architecture}}' "$base_image" 2>/dev/null || true)
case "$platform" in
    linux/amd64) want_arch=amd64 ;;
    linux/arm64) want_arch=arm64 ;;
    *)           want_arch= ;;
esac
if [[ -n $want_arch && -n $image_arch && $image_arch != "$want_arch" ]]; then
    echo "基础镜像架构不匹配：${base_image} 是 ${image_arch}，但请求 ${platform}" >&2
    echo "修复方法二选一：" >&2
    echo "  1. 用匹配的基础镜像：在 ${want_arch} 机器上跑 base-build.sh 后 docker save/load；" >&2
    echo "  2. 或匹配现有镜像：CF_PLATFORM=linux/${image_arch} ./build-in-docker.sh ..." >&2
    if [[ $image_arch == amd64 ]]; then
        echo "     （amd64 在 arm64 上走 QEMU 模拟，慢一个数量级）" >&2
    fi
    exit 2
fi

# 把可覆盖的 ref 透传进容器，方便构建特性分支；CF_FORCE_REBUILD=1
# 强制全量重建、忽略 cloudfile-build.sh 的分层缓存。
env_args=()
for v in CF_SERVER_REF CF_HUB_REF CF_SERVER_URL CF_HUB_URL \
         CF_SEAFOBJ_REF CF_SEAFDAV_REF CF_SEAFEVENTS_REF \
         CF_LIBSEARPC_REF CF_LIBEVHTP_REF CF_FORCE_REBUILD; do
    [[ -n ${!v:-} ]] && env_args+=(-e "$v=${!v}")
done

# 本地源码目录：把它挂进容器，否则容器里只有 cloudfile-docker。
#
# 没有这一段的话，**尚未 push 的分支根本无法在本地验证**——构建只会去
# GitHub 上找那个不存在的分支。而"先在本地跑一遍完整门禁，别拿 CI 当调试器"
# 正是 verify-local.sh 存在的全部理由，所以这个缺口必须补上。
#
#   CF_SERVER_URL=../../cloudfile-server CF_HUB_URL=../../cloudfile-hub \
#     ./build-in-docker.sh 14.0.0-cf.0-local
#
# 用 file:// 而不是裸路径：git clone 对本地路径默认走硬链接，而源目录是只读
# 挂载，跨挂载边界建硬链接会失败。file:// 强制走正常的对象拷贝。
#
# 副作用是**只有已提交的代码会进构建**——工作区里没 commit 的改动不参与。
# 这是好事：构建结果与某个 commit 一一对应，否则"这个镜像是哪来的"无法回答。
mount_args=()
for v in CF_SERVER_URL CF_HUB_URL; do
    src=${!v:-}
    [[ -n $src && -d $src ]] || continue
    abs=$(cd "$src" && pwd)
    name=$(basename "$abs")
    mount_args+=(-v "$abs:/src/$name:ro")
    # 覆盖前面那一轮塞进去的宿主机路径
    env_args+=(-e "$v=file:///src/$name")
    echo "本地源码：$v = ${abs}（容器内 /src/${name}，只读）"
done

echo "在容器内构建 CloudFile ${version}${platform:+ (${platform})}"
echo "宿主机不会被改动；产物写回 build/cloudfile_14.0/"
echo

# 挂载整个仓库：构建脚本要读 release.yaml，产物也要写回 build/cloudfile_14.0/。
# git 需要把挂载进来的目录标记为 safe，否则会因 owner 不一致拒绝操作。
docker run --rm -i --pull=never \
    "${platform_arg[@]}" \
    "${env_args[@]}" \
    "${mount_args[@]+"${mount_args[@]}"}" \
    -v "$repo_root:/work" \
    -w /work/build/cloudfile_14.0 \
    "$base_image" \
    bash -c "
        set -e
        export TZ=Etc/UTC
        git config --global --add safe.directory '*'
        ./cloudfile-build.sh '$version'
    "

echo
echo "完成：$here/seafile-server-${version}"
echo "下一步：$repo_root/image/cloudfile_14.0/docker-build.sh $version"
