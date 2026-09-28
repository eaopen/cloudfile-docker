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
if [[ $# -gt 1 ]]; then
    echo 'Usage: build-local-image.sh [image-tag]' >&2
    exit 2
fi
platform=$(python3 "${current_dir}/image_platform.py" resolve "${CF_PLATFORM:-native}")
arch=${platform#linux/}
if [[ -z "${CF_PLATFORM:-}" || "${CF_PLATFORM}" == "native" ]]; then
    default_tag="cloudfile/cloudfile:${version}-${product_version}-local"
else
    default_tag="cloudfile/cloudfile:${version}-${product_version}-${arch}-local"
fi
tag=${1:-${default_tag}}
legacy_package="${current_dir}/seafile-server-${version}"
arch_package="${current_dir}/seafile-server-${version}-${arch}"
if [[ -z "${CF_PLATFORM:-}" || "${CF_PLATFORM}" == "native" ]]; then
    default_package="${legacy_package}"
    [[ -d "${default_package}" ]] || default_package="${arch_package}"
else
    default_package="${arch_package}"
    [[ -d "${default_package}" ]] || default_package="${legacy_package}"
fi
package="${CLOUDFILE_PACKAGE_DIR:-${default_package}}"

if [[ ! -d "${package}" ]]; then
    echo "Missing verified package: ${package}" >&2
    exit 1
fi
package_digest=$(python3 "${provenance_reader}" "${package}" "${manifest}")
python3 "${current_dir}/image_platform.py" verify "${platform}" "${package}" >/dev/null
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
legacy_base="cloudfile/runtime-base:${version}-local"
if [[ -z "${CF_PLATFORM:-}" || "${CF_PLATFORM}" == "native" ]]; then
    default_base="${legacy_base}"
else
    default_base="cloudfile/runtime-base:${version}-${arch}-local"
fi
runtime_base=${CLOUDFILE_RUNTIME_BASE:-${default_base}}
if [[ "${runtime_base}" != "${legacy_base}" && -z "${CLOUDFILE_RUNTIME_BASE:-}" ]] && \
        ! docker image inspect "${runtime_base}" >/dev/null 2>&1 && \
        docker image inspect "${legacy_base}" >/dev/null 2>&1 && \
        [[ "$(docker image inspect --format '{{.Architecture}}' "${legacy_base}")" == "${arch}" ]]; then
    docker tag "${legacy_base}" "${runtime_base}"
fi
if [[ "${CLOUDFILE_REFRESH_RUNTIME_BASE:-false}" == "true" ]] || \
        ! docker image inspect "${runtime_base}" >/dev/null 2>&1; then
    docker build --platform "${platform}" --pull=false --file "${context}/Dockerfile.runtime-base" \
        --build-arg "server_version=${version}" \
        --label "com.cloudfile.runtime-base.version=${version}" \
        -t "${runtime_base}" "${context}"
fi
base_version=$(docker image inspect --format '{{ index .Config.Labels "com.cloudfile.runtime-base.version" }}' "${runtime_base}")
if [[ "${base_version}" != "${version}" ]]; then
    echo "Runtime base does not match CE release ${version}" >&2
    exit 1
fi
base_arch=$(docker image inspect --format '{{.Architecture}}' "${runtime_base}")
if [[ "${base_arch}" != "${arch}" ]]; then
    echo "Runtime base architecture ${base_arch} does not match ${platform}" >&2
    exit 1
fi
base_id=$(docker image inspect --format '{{.Id}}' "${runtime_base}")
base_pin="cloudfile/runtime-base:${arch}-sha-${base_id#sha256:}"
docker tag "${base_id}" "${base_pin}"
docker build --platform "${platform}" --pull=false \
    --build-arg "CLOUDFILE_RUNTIME_BASE=${base_pin}" \
    --build-arg "server_version=${version}" \
    --label "com.cloudfile.runtime-base.image=${base_id}" \
    --label "org.opencontainers.image.version=${product_version}" \
    --label "com.cloudfile.seafile.version=${version}" \
    --label "com.cloudfile.source.seafile-server=${server_ref}" \
    --label "com.cloudfile.source.seahub=${hub_ref}" \
    --label "com.cloudfile.package.sha256=${package_digest}" \
    --label "com.cloudfile.image.platform=${platform}" \
    -t "${tag}" \
    "${context}"

echo "Built ${tag}"
