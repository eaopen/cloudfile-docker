#!/bin/bash

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
        if [[ ! -e "${source}" ]]; then
            git clone "${source_url}" "${source}" || exit 1
        elif [[ -d "${source}/.git" ]]; then
            git -C "${source}" remote set-url origin "${source_url}" || exit 1
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
        cd "${code_path}/${source}" || exit 1
        git reset --hard || exit 1
        git clean -xffd || exit 1
        git fetch --force origin "${source_ref}" || exit 1
        git checkout --detach FETCH_HEAD || exit 1
        cd "${code_path}" || exit 1
    done
}

function build() {
    cd ${current_dir}
    python3 ./seafile-build.py --version=${version} --builddir=${current_dir} --srcdir=${code_path} --thirdpartdir=${code_path}/thirdpartdir --mysql_config=/usr/bin/mariadb_config
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
