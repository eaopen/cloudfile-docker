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

# 浠撳簱鍚嶅彇鑷?manifest锛屾爣绛?*蹇呴』**鐢ㄤ紶鍏ョ殑鐗堟湰鍙枫€?
#
# 鏃╁厛鐩存帴鎷?manifest 鐨?image 鏁翠覆褰撴爣绛撅紝浜庢槸鏋勫缓 14.0.0-cf.0-local 涔熶細鎵撴垚
# 14.0.0-cf.0鈥斺€斾换浣曠壒鎬у垎鏀垨鏈湴鏋勫缓閮戒細鎮勬倓瑕嗙洊姝ｅ紡鍙戝竷鏍囩銆傞粯璁よ矾寰勪笂
# 涓や釜鐗堟湰鍙锋伆濂界浉鍚岋紝鎵€浠ヨ繖涓?bug 涓€鐩寸湅涓嶅嚭鏉ャ€?
manifest_image=$(python3 "$repo_root/build/cloudfile_14.0/read-manifest.py" \
    "$repo_root/release.yaml" image)
image="${manifest_image%%:*}:${version}"

pull_args=()
if [[ ${CF_DOCKER_PULL:-true} == true ]]; then
    pull_args=(--pull)
fi

docker build "${pull_args[@]}" \
    --build-arg server_version="${version}" \
    -t "${image}" \
    "$staging"

echo ''
echo "Built ${image}"
