#!/bin/bash
#
# Build the CloudFile image.
#
# The Dockerfile COPYs base_scripts/, scripts_14.0/, services/ and the built
# seafile-server-<version>/ tree, all of which live outside this directory, so
# the build context is the repo root and the assets are staged here first.
#
# Run build/cloudfile_14.0/cloudfile-build.sh <version> before this.
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

staging=$(mktemp -d "${TMPDIR:-/tmp}/cloudfile-image.XXXXXX")
trap 'rm -rf "$staging"' EXIT

cp "$here/Dockerfile" "$staging/"
cp -r "$repo_root/base_scripts" "$staging/base_scripts"
cp -r "$repo_root/scripts/scripts_14.0" "$staging/scripts_14.0"
cp -r "$repo_root/services" "$staging/services"
cp -r "$dist" "$staging/seafile-server-${version}"

# 仓库名取自 manifest，标签**必须**用传入的版本号。
#
# 早先直接拿 manifest 的 image 整串当标签，于是构建 14.0.0-cf.0-local 也会打成
# 14.0.0-cf.0——任何特性分支或本地构建都会悄悄覆盖正式发布标签。默认路径上
# 两个版本号恰好相同，所以这个 bug 一直看不出来。
manifest_image=$(python3 "$repo_root/build/cloudfile_14.0/read-manifest.py" \
    "$repo_root/release.yaml" image)
image="${manifest_image%%:*}:${version}"

docker build --pull \
    --build-arg server_version="${version}" \
    -t "${image}" \
    "$staging"

echo ''
echo "Built ${image}"
