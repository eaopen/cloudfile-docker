#!/bin/bash
#
# Build the reusable CloudFile CE 14 base image on a machine with reliable
# package access. Daily application builds must use docker-build.sh instead.
#
#   ./base-build.sh
#   CF_PLATFORM=linux/arm64 ./base-build.sh
#   CF_BASE_IMAGE=registry.internal/cloudfile/build-base:ce14-v1 ./base-build.sh

set -e

here=$(cd "$(dirname "$0")" && pwd)
repo_root=$(cd "$here/../.." && pwd)
manifest=$repo_root/release.yaml
reader=$repo_root/build/cloudfile_14.0/read-manifest.py

base_image=${CF_BASE_IMAGE:-$(python3 "$reader" "$manifest" build_base_image)}
ubuntu_base=${CF_UBUNTU_BASE:-$(python3 "$reader" "$manifest" ubuntu_base_image)}
platform=${CF_PLATFORM:-linux/amd64}

if ! docker info >/dev/null 2>&1; then
    echo "Docker is unavailable." >&2
    exit 2
fi

docker buildx build \
    --platform "$platform" \
    --file "$here/Dockerfile.base" \
    --build-arg UBUNTU_BASE="$ubuntu_base" \
    --tag "$base_image" \
    --load \
    "$repo_root"

echo
echo "Built and loaded $base_image ($platform)"
