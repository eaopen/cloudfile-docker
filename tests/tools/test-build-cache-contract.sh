#!/bin/bash

set -eu

here=$(cd "$(dirname "$0")" && pwd)
repo_root=$(cd "$here/../.." && pwd)
build_script=$repo_root/build/cloudfile_14.0/cloudfile-build.sh
container_script=$repo_root/build/cloudfile_14.0/build-in-docker.sh

require_text() {
    local file=$1 text=$2
    if ! grep -Fq -- "$text" "$file"; then
        echo "missing build-cache contract in $(basename "$file"): $text" >&2
        exit 1
    fi
}

require_text "$build_script" 'git clean -xfd -e frontend/node_modules/'
require_text "$build_script" 'frontend-node-modules.sha256'
require_text "$build_script" 'node-modules-abi='
require_text "$build_script" 'HEAD:python'
require_text "$build_script" 'HEAD:pysearpc'
require_text "$build_script" 'CF_FORCE_FRONTEND_REBUILD'
require_text "$build_script" 'CF_FORCE_DIST_REBUILD'
require_text "$container_script" 'CF_FRONTEND_TOOL_CACHE_DIR=/cache/frontend-tools'
require_text "$container_script" 'CF_FORCE_FRONTEND_REBUILD CF_FORCE_DIST_REBUILD'

fingerprint_body=$(sed -n \
    '/^function frontend_fingerprint()/,/^}/p' "$build_script")
if grep -Eq '^[[:space:]]*source_fingerprint[[:space:]]*$' <<<"$fingerprint_body"; then
    echo 'frontend fingerprint must not depend on unrelated C/Go repositories' >&2
    exit 1
fi
