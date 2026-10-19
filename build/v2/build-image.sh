#!/usr/bin/env bash
# Reuse the existing CE14 toolchain/runtime images and persistent package caches.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$here/../.." && pwd)
source_root=$(cd "${1:?prepared V2 source directory required}" && pwd)
image=${2:-cloudfile:v2-dev}
platform=${CF_PLATFORM:-$(docker version --format '{{.Server.Os}}/{{.Server.Arch}}')}
arch=${platform##*/}
build_base=${CF_BASE_IMAGE:-${DEV_BASE:-cloudfile-build-base:ce14-v2}}
runtime_base=${CLOUDFILE_RUNTIME_BASE:-$build_base}
# Inspect once: preserve native architecture and pin already-loaded bases locally.
read -r build_id build_arch < <(docker image inspect --format '{{.Id}} {{.Architecture}}' "$build_base")
read -r runtime_id runtime_arch < <(docker image inspect --format '{{.Id}} {{.Architecture}}' "$runtime_base")
if [[ $build_arch != "$arch" || $runtime_arch != "$arch" ]]; then
    echo "Existing dependency images must match $platform" >&2
    exit 2
fi
build_pin="cloudfile/build-base:sha-${build_id#sha256:}"
runtime_pin="cloudfile/runtime-base:sha-${runtime_id#sha256:}"
docker tag "$build_id" "$build_pin"
docker tag "$runtime_id" "$runtime_pin"
legacy_cache="$(dirname "$repo")/.v0.1-local/cloudfile-docker/cloudfile_14.0/.cache"
cache=${CF_CACHE_DIR:-$legacy_cache}
if [[ -z ${CF_CACHE_DIR:-} && ! -d $cache ]]; then cache="$here/.cache"; fi
mkdir -p "$cache"/{ccache,gocache,gomodcache,npm,pip}
cache=$(cd "$cache" && pwd)
# Fetch only missing pinned library sources; never install host toolchains.
bash "$here/build-native.sh" "$source_root" unused sources
args=(--load --pull=false --platform "$platform" --progress=plain
    --file "$here/Dockerfile.dev" --build-context "cf-build=$here"
    --build-context "cf-cache=$cache" --build-arg "CF_BASE_IMAGE=$build_pin"
    --build-arg "CLOUDFILE_RUNTIME_BASE=$runtime_pin"
    --label "com.cloudfile.build-base.image=$build_id"
    --label "com.cloudfile.runtime-base.image=$runtime_id"
    --label "org.opencontainers.image.created=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    --label "org.opencontainers.image.revision=$(git -C "$repo" rev-parse HEAD 2>/dev/null || printf exported-tree)"
    --tag "$image")
for variable in GOPROXY GOSUMDB; do
    if [[ -n ${!variable:-} ]]; then args+=(--build-arg "$variable=${!variable}"); fi
done
# Docker's own layer/cache keys track manifests separately from app source.
docker buildx build "${args[@]}" "${@:3}" "$source_root"
