#!/bin/bash

# Assemble an isolated Docker context from the verified package and shared
# runtime assets. This avoids generated copies inside the tracked image tree.
set -euo pipefail

SCRIPT=$(readlink -f "$0")
current_dir=$(dirname "${SCRIPT}")
repo_dir=$(readlink -f "${current_dir}/../..")
manifest="${current_dir}/release.json"
manifest_reader="${current_dir}/source_manifest.py"
provenance_reader="${current_dir}/package_provenance.py"
version=$(python3 "${manifest_reader}" "${manifest}" seafile_version)
product_version=$(python3 "${manifest_reader}" "${manifest}" product_version)
server_ref=$(python3 "${manifest_reader}" "${manifest}" ref seafile-server)
hub_ref=$(python3 "${manifest_reader}" "${manifest}" ref seahub)
tag=${1:-cloudfile/cloudfile:${version}-${product_version}-local}
package="${CLOUDFILE_PACKAGE_DIR:-${current_dir}/seafile-server-${version}}"

if [[ ! -d "${package}" ]]; then
    echo "Missing verified package: ${package}" >&2
    exit 1
fi
package_digest=$(python3 "${provenance_reader}" "${package}" "${manifest}")
if ! command -v docker >/dev/null 2>&1; then
    echo "docker is required to build the local image" >&2
    exit 1
fi

context=$(mktemp -d)
trap 'rm -rf "${context}"' EXIT
cp "${repo_dir}/image/seafile_14.0/Dockerfile" "${context}/Dockerfile"
cp "${repo_dir}/image/seafile_14.0/Dockerfile.runtime-base" "${context}/Dockerfile.runtime-base"
cp -a "${repo_dir}/base_scripts" "${context}/base_scripts"
cp -a "${repo_dir}/scripts/scripts_14.0" "${context}/scripts_14.0"
cp -a "${repo_dir}/services" "${context}/services"
cp -a "${package}" "${context}/seafile-server-${version}"
# Validate the copied context too, so a changed source package cannot be labeled
# with the current pins between the original check and context assembly.
copied_digest=$(python3 "${provenance_reader}" "${context}/seafile-server-${version}" "${manifest}")
if [[ "${copied_digest}" != "${package_digest}" ]]; then
    echo "Native package changed while preparing the image context" >&2
    exit 1
fi

# Reuse v0.1's dependency/application split. BuildKit can reuse the existing
# identical CE14 APT/pip layers for this first extraction too. Refresh is explicit.
runtime_base=${CLOUDFILE_RUNTIME_BASE:-cloudfile/runtime-base:${version}-local}
if [[ "${CLOUDFILE_REFRESH_RUNTIME_BASE:-false}" == "true" ]] || \
        ! docker image inspect "${runtime_base}" >/dev/null 2>&1; then
    docker build --pull=false --file "${context}/Dockerfile.runtime-base" \
        --build-arg "server_version=${version}" \
        --label "com.cloudfile.runtime-base.version=${version}" \
        -t "${runtime_base}" "${context}"
fi
base_version=$(docker image inspect --format '{{ index .Config.Labels "com.cloudfile.runtime-base.version" }}' "${runtime_base}")
if [[ "${base_version}" != "${version}" ]]; then
    echo "Runtime base does not match CE release ${version}" >&2
    exit 1
fi
base_id=$(docker image inspect --format '{{.Id}}' "${runtime_base}")
base_pin="cloudfile/runtime-base:sha-${base_id#sha256:}"
docker tag "${base_id}" "${base_pin}"
docker build --pull=false \
    --build-arg "CLOUDFILE_RUNTIME_BASE=${base_pin}" \
    --build-arg "server_version=${version}" \
    --label "com.cloudfile.runtime-base.image=${base_id}" \
    --label "org.opencontainers.image.version=${product_version}" \
    --label "com.cloudfile.seafile.version=${version}" \
    --label "com.cloudfile.source.seafile-server=${server_ref}" \
    --label "com.cloudfile.source.seahub=${hub_ref}" \
    --label "com.cloudfile.package.sha256=${package_digest}" \
    -t "${tag}" \
    "${context}"

echo "Built ${tag}"
