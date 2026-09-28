#!/bin/bash
#
# Build the CloudFile image.
#
# The Dockerfile uses the repository root for small runtime assets and passes
# the selected distribution as a named BuildKit context. This avoids copying
# it to a staging directory or scanning unrelated historical distributions.
#
# Run build/cloudfile_14.0/cloudfile-build.sh <version> before this.
#
# The base image must already exist in the Docker image store. This command
# never pulls it and gives build steps no network access.
#
# Usage: ./docker-build.sh <version>            e.g. 14.0.0-cf.0

set -e

if [[ $# != 1 ]]; then
    echo ''
    echo 'Usage: ./docker-build.sh $version'
    echo ''
    exit 1
fi

version=$1

here=$(cd "$(dirname "$0")" && pwd)
repo_root=$(cd "$here/../.." && pwd)
source "$repo_root/tools/build-platform.sh"

dist=$repo_root/build/cloudfile_14.0/seafile-server-${version}
if [[ ! -d $dist ]]; then
    echo "built distribution not found: $dist" >&2
    echo "run build/cloudfile_14.0/cloudfile-build.sh ${version} first" >&2
    exit 1
fi

# 仓库名取自 manifest，标签**必须**用传入的版本号。
#
# 早先直接拿 manifest 的 image 整串当标签，于是构建 14.0.0-cf.0-local 也会打成
# 14.0.0-cf.0——任何特性分支或本地构建都会悄悄覆盖正式发布标签。默认路径上
# 两个版本号恰好相同，所以这个 bug 一直看不出来。
manifest_image=$(python3 "$repo_root/build/cloudfile_14.0/read-manifest.py" \
    "$repo_root/release.yaml" image)
image="${manifest_image%%:*}:${version}"
base_image=${CF_BASE_IMAGE:-$(python3 \
    "$repo_root/build/cloudfile_14.0/read-manifest.py" \
    "$repo_root/release.yaml" build_base_image)}

if ! docker image inspect "$base_image" >/dev/null 2>&1; then
    echo "build base image is not loaded: $base_image" >&2
    echo "build it on a networked machine with image/cloudfile_14.0/base-build.sh," >&2
    echo "then docker save/load it or pull it from the internal registry first." >&2
    exit 2
fi

# The base image is single-arch. Without an explicit --platform, Docker targets
# the host architecture, so an amd64 base on Apple Silicon (or the reverse)
# fails to resolve with a confusing "pull access denied". Mirror
# build-in-docker.sh: default to the host arch, allow CF_PLATFORM to override,
# and fail fast when the loaded base image does not match.
if [[ -z ${CF_PLATFORM:-} ]]; then
    platform=$(cf_host_platform) || exit 2
else
    platform=$(cf_normalize_platform "$CF_PLATFORM") || exit 2
fi

image_arch=$(docker image inspect --format '{{.Architecture}}' "$base_image" 2>/dev/null || true)
want_arch=$(cf_platform_arch "$platform") || exit 2
if [[ -n $image_arch && $image_arch != "$want_arch" ]]; then
    echo "base image architecture mismatch: ${base_image} is ${image_arch}, requested ${platform}" >&2
    echo "load a matching base image, or set CF_PLATFORM=linux/${image_arch}" >&2
    exit 2
fi

DOCKER_BUILDKIT=${DOCKER_BUILDKIT:-1} docker build --pull=false --network=none \
    --platform "$platform" \
    -f "$here/Dockerfile" \
    --build-context cloudfile_dist="$dist" \
    --build-arg CLOUDFILE_BASE="$base_image" \
    --build-arg server_version="${version}" \
    -t "${image}" \
    "$repo_root"

echo ''
echo "Built ${image}"
