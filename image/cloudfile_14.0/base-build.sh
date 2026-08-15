#!/bin/bash
#
# Build the reusable CloudFile CE 14 base image on a machine with reliable
# package access. Daily application builds must use docker-build.sh instead.
#
#   ./base-build.sh
#   CF_PLATFORM=linux/arm64 ./base-build.sh
#   CF_BASE_IMAGE=registry.internal/cloudfile/build-base:ce14-v2 ./base-build.sh

set -e

here=$(cd "$(dirname "$0")" && pwd)
repo_root=$(cd "$here/../.." && pwd)
manifest=$repo_root/release.yaml
reader=$repo_root/build/cloudfile_14.0/read-manifest.py
source "$repo_root/tools/build-platform.sh"

base_image=${CF_BASE_IMAGE:-$(python3 "$reader" "$manifest" build_base_image)}
ubuntu_base=${CF_UBUNTU_BASE:-$(python3 "$reader" "$manifest" ubuntu_base_image)}
platform=$(cf_normalize_platform "${CF_PLATFORM:-linux/amd64}") || exit 2

if ! docker info >/dev/null 2>&1; then
    echo "Docker is unavailable." >&2
    exit 2
fi

# On GitHub Actions, reuse the BuildKit layers via the Actions cache backend so
# the toolchain image is rebuilt only when Dockerfile.base or base_scripts
# actually changes. Locally the flags are omitted and a plain build runs.
cache_args=()
if [[ ${GITHUB_ACTIONS:-false} == true ]]; then
    cache_args=(
        --cache-from "type=gha,scope=cloudfile-build-base"
        --cache-to "type=gha,mode=max,scope=cloudfile-build-base"
    )
fi

docker buildx build \
    --platform "$platform" \
    --file "$here/Dockerfile.base" \
    --build-arg UBUNTU_BASE="$ubuntu_base" \
    --tag "$base_image" \
    --load \
    "${cache_args[@]}" \
    "$repo_root"

echo
echo "Built and loaded $base_image ($platform)"
