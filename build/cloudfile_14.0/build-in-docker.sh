#!/bin/bash
#
# 在 Ubuntu 容器里跑 cloudfile-build.sh，不在宿主机上装任何东西。
#
# cloudfile-build.sh 会 apt-get install 一整套 C/Go 工具链，只能在 Ubuntu 上跑。
# 把它放进容器，macOS / 任意发行版都能构建，且宿主机保持干净。
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

platform=${CF_PLATFORM:-}
platform_arg=()
[[ -n $platform ]] && platform_arg=(--platform "$platform")

if ! docker info >/dev/null 2>&1; then
    echo "Docker 不可用。请先启动 Docker Desktop / OrbStack / colima。" >&2
    exit 2
fi

# 把可覆盖的 ref 透传进容器，方便构建特性分支。
env_args=()
for v in CF_SERVER_REF CF_HUB_REF CF_SERVER_URL CF_HUB_URL \
         CF_SEAFOBJ_REF CF_SEAFDAV_REF CF_SEAFEVENTS_REF \
         CF_LIBSEARPC_REF CF_LIBEVHTP_REF; do
    [[ -n ${!v:-} ]] && env_args+=(-e "$v=${!v}")
done

echo "在容器内构建 CloudFile ${version}${platform:+ (${platform})}"
echo "宿主机不会被改动；产物写回 build/cloudfile_14.0/"
echo

# 挂载整个仓库：构建脚本要读 release.yaml，产物也要写回 build/cloudfile_14.0/。
# git 需要把挂载进来的目录标记为 safe，否则会因 owner 不一致拒绝操作。
docker run --rm -i \
    "${platform_arg[@]}" \
    "${env_args[@]}" \
    -v "$repo_root:/work" \
    -w /work/build/cloudfile_14.0 \
    ubuntu:24.04 \
    bash -c "
        set -e
        apt-get update -qq
        apt-get install -y -qq git python3 ca-certificates >/dev/null
        git config --global --add safe.directory '*'
        ./cloudfile-build.sh '$version'
    "

echo
echo "完成：$here/seafile-server-${version}"
echo "下一步：$repo_root/image/cloudfile_14.0/docker-build.sh $version"
