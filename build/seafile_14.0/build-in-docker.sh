#!/bin/bash
# Reuse v0.1's prebuilt toolchain, native architecture and persistent caches.
# Only clean, pinned local CloudFile commits are mounted; no source worktree edits.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "${here}/../.." && pwd)
workspace=$(dirname "${repo}")
if [[ $# -gt 1 ]]; then
    echo 'Usage: build-in-docker.sh [seafile-version]' >&2
    exit 2
fi
version=$(python3 "${here}/source_manifest.py" "${here}/release.json" seafile_version)
if [[ $# -eq 1 && "$1" != "${version}" ]]; then
    echo 'Version must match release.json' >&2
    exit 2
fi
case "$(uname -m)" in arm64|aarch64) native_arch=arm64 ;; x86_64|amd64) native_arch=amd64 ;;
    *) echo 'Unsupported host architecture' >&2; exit 2 ;; esac
platform=${CF_PLATFORM:-linux/${native_arch}}
case "${platform}" in linux/arm64|linux/amd64) ;; *) echo 'Use linux/arm64 or linux/amd64' >&2; exit 2 ;; esac
base=${CF_BASE_IMAGE:-cloudfile-build-base:ce14-v2}
base_arch=$(docker image inspect --format '{{.Architecture}}' "${base}")
base_id=$(docker image inspect --format '{{.Id}}' "${base}")
if [[ "${base_arch}" != "${platform#linux/}" ]]; then
    echo 'Build base architecture differs from requested platform' >&2
    exit 2
fi
if [[ "${platform#linux/}" != "${native_arch}" ]]; then
    echo 'Explicit cross-architecture build uses emulation; prefer a native builder.' >&2
fi
jobs=${CF_BUILD_JOBS:-4}
if [[ ! "${jobs}" =~ ^[1-9][0-9]*$ ]]; then
    echo 'CF_BUILD_JOBS must be a positive integer' >&2
    exit 2
fi
legacy_cache="${workspace}/.v0.1-local/cloudfile-docker/cloudfile_14.0/.cache"
if [[ -n "${CF_CACHE_DIR:-}" ]]; then
    cache=${CF_CACHE_DIR}
elif [[ -d "${legacy_cache}" ]]; then
    cache=${legacy_cache}
    echo 'Reuse existing v0.1 compiler/module/package download caches.'
else
    cache=${here}/.cache
fi
mkdir -p "${cache}/ccache" "${cache}/gocache" "${cache}/gomodcache" "${cache}/pip"
cache=$(cd "${cache}" && pwd)
sources=()
for item in 'seafile-server:cloudfile-server:CLOUDFILE_SERVER_SOURCE' 'seahub:cloudfile-hub:CLOUDFILE_HUB_SOURCE'; do
    source_name=${item%%:*}
    remaining=${item#*:}
    checkout_name=${remaining%%:*}
    variable=${remaining#*:}
    source=${!variable:-${workspace}/${checkout_name}}
    pin=$(python3 "${here}/source_manifest.py" "${here}/release.json" ref "${source_name}")
    validated=$(python3 "${here}/source_override.py" "${source}" "${pin}")
    sources+=(-v "${validated}:/sources/${checkout_name}:ro" -e "${variable}=/sources/${checkout_name}")
done
docker run --rm -i --pull=never --platform "${platform}" \
    -v "${repo}:/work" -v "${cache}:/cache" "${sources[@]}" \
    -w /work/build/seafile_14.0 \
    -e 'PATH=/usr/lib/ccache:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin' \
    -e CCACHE_DIR=/cache/ccache -e CCACHE_COMPRESS=true -e CCACHE_MAXSIZE=5G \
    -e GOCACHE=/cache/gocache -e GOMODCACHE=/cache/gomodcache -e PIP_CACHE_DIR=/cache/pip \
    -e "CLOUDFILE_BUILD_BASE_ID=${base_id}" -e "CF_BUILD_JOBS=${jobs}" \
    -e "CF_FORCE_THIRDPART_REFRESH=${CF_FORCE_THIRDPART_REFRESH:-false}" \
    "${base_id}" bash -c 'set -e; test "${CLOUDFILE_BUILD_BASE:-}" = true; git config --global --add safe.directory /sources/cloudfile-server; git config --global --add safe.directory /sources/cloudfile-hub; git config --global --add safe.directory /work/build/seafile_14.0/src/libevhtp; for source in libsearpc seafile-server seafobj seafdav seafevents seahub; do git config --global --add safe.directory "/work/build/seafile_14.0/src/$source"; done; ./seafile-build.sh'
