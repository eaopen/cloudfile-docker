#!/bin/bash

# A partial native package is unusable; stop on the first failed clone,
# dependency install, compile, or packaging command instead of printing success.
set -euo pipefail

if [[ $# -gt 1 ]]; then
    echo ''
    echo 'Usage: ./seafile-build.sh [seafile-version]'
    echo ''
    exit 2
fi

SCRIPT=$(readlink -f "$0")
current_dir=$(dirname "${SCRIPT}")
code_path=$current_dir/src
manifest=$current_dir/release.json
manifest_reader=$current_dir/source_manifest.py
override_validator=$current_dir/source_override.py
version=$(python3 "${manifest_reader}" "${manifest}" seafile_version) || exit 1
product_version=$(python3 "${manifest_reader}" "${manifest}" product_version) || exit 1
if [[ $# -eq 1 && "$1" != "${version}" ]]; then
    echo "Requested Seafile version $1 does not match release manifest ${version}" >&2
    exit 2
fi
mkdir -p "${code_path}"

function manifest_value() {
    python3 "${manifest_reader}" "${manifest}" "$2" "$1"
}

function source_override() {
    # Local overrides are intentionally limited to CloudFile-owned repositories.
    # This lets an operator build exact local commits before a human pushes them.
    case "$1" in
        seafile-server)
            echo "${CLOUDFILE_SERVER_SOURCE:-}"
            ;;
        seahub)
            echo "${CLOUDFILE_HUB_SOURCE:-}"
            ;;
        *)
            echo ""
            ;;
    esac
}

function install_dependencies() {
    apt-get update && apt-get upgrade -y
    apt-get install -y build-essential
    export DEBIAN_FRONTEND=noninteractive && apt-get install -y tzdata
    apt-get install -y \
        ca-certificates \
        cargo \
        cmake \
        git \
        golang-go \
        intltool \
        libarchive-dev \
        libcurl4-openssl-dev \
        libevent-dev \
        libffi-dev \
        libfuse-dev \
        libglib2.0-dev \
        libjansson-dev \
        libjpeg-dev \
        libjwt-dev \
        libldap2-dev \
        libmariadbclient-dev-compat \
        libonig-dev \
        libpq-dev \
        libsqlite3-dev \
        libssl-dev \
        libtool \
        libxml2-dev \
        libxslt-dev \
        python3 \
        python3-distro \
        python3-lxml \
        python3-ldap \
        python3-pip \
        python3-setuptools \
        python3-wheel \
        uuid-dev \
        valac \
        wget \
        curl \
        libunwind-dev \
        libhiredis-dev \
        google-perftools \
        libgoogle-perftools-dev \
        libargon2-dev
}

function install_python_dependencies() {
    cat ${code_path}/seafevents/requirements.txt ${code_path}/seafdav/requirements.txt ${code_path}/seahub/requirements.txt >${code_path}/requirements-thirdpart.txt
    cd ${code_path}

    # seafevents ignore
    sed -i 's/SQLAlchemy/# SQLAlchemy/' requirements-thirdpart.txt
    sed -i 's/mock/# mock/' requirements-thirdpart.txt
    sed -i 's/pytest/# pytest/' requirements-thirdpart.txt
    sed -i 's/gevent/# gevent/' requirements-thirdpart.txt
    sed -i 's/numpy/# numpy/' requirements-thirdpart.txt
    sed -i 's/scikit-learn/# scikit-learn/' requirements-thirdpart.txt

    # seafdav ignore
    sed -i 's/Jinja2/# Jinja2/' requirements-thirdpart.txt
    sed -i 's/sqlalchemy/# sqlalchemy/' requirements-thirdpart.txt

    # seahub ignore
    sed -i 's/django_simple_captcha/# django_simple_captcha/' requirements-thirdpart.txt
    sed -i 's/^captcha/# captcha/' requirements-thirdpart.txt
    sed -i 's/mysqlclient/# mysqlclient/' requirements-thirdpart.txt
    sed -i 's/pillow/# pillow/' requirements-thirdpart.txt
    sed -i 's/pycryptodome/# pycryptodome/' requirements-thirdpart.txt
    sed -i 's/djangosaml2/# djangosaml2/' requirements-thirdpart.txt
    sed -i 's/pysaml2/# pysaml2/' requirements-thirdpart.txt
    sed -i 's/cffi/# cffi/' requirements-thirdpart.txt
    sed -i 's/python-ldap/# python-ldap/' requirements-thirdpart.txt
    sed -i 's/PyMuPDF/# PyMuPDF/' requirements-thirdpart.txt
    sed -i 's/cairosvg/# cairosvg/' requirements-thirdpart.txt

    # pymysql for scripts
    sed -i '$a\pymysql' requirements-thirdpart.txt
    # install
    pip3 install -r requirements-thirdpart.txt -t ${code_path}/thirdpartdir
}

function clone_code() {
    cd "${code_path}" || exit 1

    for source in libevhtp libsearpc seafile-server seafobj seafdav seafevents seahub; do
        source_url=$(manifest_value "${source}" url) || exit 1
        source_ref=$(manifest_value "${source}" ref) || exit 1
        override=$(source_override "${source}")
        if [[ ! -e "${source}" ]]; then
            if [[ -n "${override}" ]]; then
                validated_override=$(python3 "${override_validator}" "${override}" "${source_ref}") || exit 1
                git clone --no-hardlinks "${validated_override}" "${source}" || exit 1
            else
                git clone "${source_url}" "${source}" || exit 1
            fi
        elif [[ -d "${source}/.git" ]]; then
            if [[ -n "${override}" ]]; then
                validated_override=$(python3 "${override_validator}" "${override}" "${source_ref}") || exit 1
                git -C "${source}" remote set-url origin "${validated_override}" || exit 1
            else
                git -C "${source}" remote set-url origin "${source_url}" || exit 1
            fi
        else
            echo "Existing source path is not a Git repository: ${code_path}/${source}" >&2
            exit 1
        fi
    done
}

function fetch() {
    cd "${code_path}" || exit 1

    echo "Start fetch"
    echo ''

    for source in libevhtp libsearpc seafile-server seafobj seafdav seafevents seahub; do
        echo "Fetch ${source}"
        source_ref=$(manifest_value "${source}" ref) || exit 1
        override=$(source_override "${source}")
        cd "${code_path}/${source}" || exit 1
        git reset --hard || exit 1
        git clean -xffd || exit 1
        if [[ -n "${override}" ]]; then
            validated_override=$(python3 "${override_validator}" "${override}" "${source_ref}") || exit 1
            git remote set-url origin "${validated_override}" || exit 1
        fi
        git fetch --force origin "${source_ref}" || exit 1
        git checkout --detach FETCH_HEAD || exit 1
        cd "${code_path}" || exit 1
    done
}

function build() {
    cd "${current_dir}"
    # Never overlay an old completed package or a previous partial build.
    # Failed output stays isolated for diagnosis; the last package stays intact.
    build_output=$(mktemp -d "${current_dir}/build-output.XXXXXX")
    python3 ./seafile-build.py --version="${version}" --builddir="${build_output}" \
        --srcdir="${code_path}" --thirdpartdir="${code_path}/thirdpartdir" \
        --mysql_config=/usr/bin/mariadb_config
    python3 ./package_provenance.py "${build_output}/seafile-server-${version}" "${manifest}"
    package="${current_dir}/seafile-server-${version}"
    if [[ -e "${package}" || -L "${package}" ]]; then
        previous=$(mktemp -d "${current_dir}/seafile-server-${version}.previous.XXXXXX")
        mv "${package}" "${previous}/package"
    fi
    if ! mv "${build_output}/seafile-server-${version}" "${package}"; then
        if [[ -n "${previous:-}" ]]; then
            mv "${previous}/package" "${package}"
        fi
        exit 1
    fi
    rmdir "${build_output}"
}

echo ''
echo "Info: CloudFile ${product_version}, Seafile ${version}"
echo ''

install_dependencies
wait

clone_code
wait

fetch
wait

install_python_dependencies
wait

build

echo ''
echo "Info: Successfully built seafile-server-${version}"
echo ''
