#!/bin/bash
#
# Build the reusable CloudFile CE 14 base image on a machine with reliable
# package access. Daily application builds must use docker-build.sh instead.
#
#   ./base-build.sh
#   CF_PLATFORM=linux/arm64 ./base-build.sh   # override the auto-detected host arch
#   CF_BASE_IMAGE=registry.internal/cloudfile/build-base:ce14-v2 ./base-build.sh

set -e

here=$(cd "$(dirname "$0")" && pwd)
repo_root=$(cd "$here/../.." && pwd)
manifest=$repo_root/release.yaml
reader=$repo_root/build/cloudfile_14.0/read-manifest.py
source "$repo_root/tools/build-platform.sh"

base_image=${CF_BASE_IMAGE:-$(python3 "$reader" "$manifest" build_base_image)}
ubuntu_base=${CF_UBUNTU_BASE:-$(python3 "$reader" "$manifest" ubuntu_base_image)}
platform=$(cf_normalize_platform "${CF_PLATFORM:-$(cf_host_platform)}") || exit 2

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

if docker buildx version >/dev/null 2>&1; then
    docker buildx build \
        --platform "$platform" \
        --file "$here/Dockerfile.base" \
        --build-arg UBUNTU_BASE="$ubuntu_base" \
        --tag "$base_image" \
        --load \
        "${cache_args[@]}" \
        "$repo_root"
else
    host_platform=$(cf_host_platform) || exit 2
    if [[ $platform != "$host_platform" ]]; then
        echo "Docker without buildx can only build for $host_platform" >&2
        exit 2
    fi
    # Classic Docker does not understand BuildKit cache mounts. Keep the same
    # commands while dropping only the cache directives in a temporary file.
    context=$(mktemp -d "$repo_root/build/cloudfile_14.0/.base-context.XXXXXX")
    trap 'rm -rf "$context"' EXIT
    cp -a "$repo_root/base_scripts" "$context/base_scripts"
    awk '
        /^RUN --mount=type=cache/ { sub(/^RUN --mount=[^ ]+ /, "RUN "); print; next }
        /^[[:space:]]+--mount=type=cache/ { next }
        { print }
    ' "$here/Dockerfile.base" > "$context/Dockerfile"
    docker build --pull=false \
        --build-arg UBUNTU_BASE="$ubuntu_base" \
        --tag "$base_image" "$context"
fi

echo
echo "Built and loaded $base_image ($platform)"
