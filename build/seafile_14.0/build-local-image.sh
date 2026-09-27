#!/bin/bash

# Assemble an isolated Docker context from the verified package and shared
# runtime assets. This avoids generated copies inside the tracked image tree.
set -euo pipefail

SCRIPT=$(readlink -f "$0")
current_dir=$(dirname "${SCRIPT}")
repo_dir=$(readlink -f "${current_dir}/../..")
manifest="${current_dir}/release.json"
manifest_reader="${current_dir}/source_manifest.py"
version=$(python3 "${manifest_reader}" "${manifest}" seafile_version)
product_version=$(python3 "${manifest_reader}" "${manifest}" product_version)
server_ref=$(python3 "${manifest_reader}" "${manifest}" ref seafile-server)
hub_ref=$(python3 "${manifest_reader}" "${manifest}" ref seahub)
tag=${1:-cloudfile/cloudfile:${version}-${product_version}-local}
package="${current_dir}/seafile-server-${version}"

if [[ ! -d "${package}" ]]; then
    echo "Missing verified package: ${package}" >&2
    exit 1
fi
if ! command -v docker >/dev/null 2>&1; then
    echo "docker is required to build the local image" >&2
    exit 1
fi

context=$(mktemp -d)
trap 'rm -rf "${context}"' EXIT
cp "${repo_dir}/image/seafile_14.0/Dockerfile" "${context}/Dockerfile"
cp -a "${repo_dir}/base_scripts" "${context}/base_scripts"
cp -a "${repo_dir}/scripts/scripts_14.0" "${context}/scripts_14.0"
cp -a "${repo_dir}/services" "${context}/services"
cp -a "${package}" "${context}/seafile-server-${version}"

docker build \
    --build-arg "server_version=${version}" \
    --label "org.opencontainers.image.version=${product_version}" \
    --label "com.cloudfile.seafile.version=${version}" \
    --label "com.cloudfile.source.seafile-server=${server_ref}" \
    --label "com.cloudfile.source.seahub=${hub_ref}" \
    -t "${tag}" \
    "${context}"

echo "Built ${tag}"
