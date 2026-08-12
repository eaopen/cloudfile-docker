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

DOCKER_BUILDKIT=${DOCKER_BUILDKIT:-1} docker build --pull=false --network=none \
    -f "$here/Dockerfile" \
    --build-context cloudfile_dist="$dist" \
    --build-arg CLOUDFILE_BASE="$base_image" \
    --build-arg server_version="${version}" \
    -t "${image}" \
    "$repo_root"

echo ''
echo "Built ${image}"
