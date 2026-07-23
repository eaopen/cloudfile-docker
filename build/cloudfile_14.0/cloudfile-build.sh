#!/bin/bash
#
# Build a CloudFile server distribution.
#
# Derived from build/seafile_14.0/seafile-build.sh with two changes:
#
#  1. seafile-server and seahub come from the CloudFile forks.
#  2. Every component is pinned by ref read from release.yaml instead of by a
#     "v<version>-server" tag. Upstream 14.0 has no CE tags at all -- only
#     "-pro" ones -- so there is nothing to pin to, and a fork would need its
#     own refs regardless.
#
# Usage: ./cloudfile-build.sh <version>          e.g. 14.0.0-cf.0
#
# Override any pin from the environment for a local build:
#   CF_SERVER_REF=feature/my-branch ./cloudfile-build.sh 14.0.0-cf.0

set -e

if [[ $# != 1 ]]; then
    echo ''
    echo 'Usage: ./cloudfile-build.sh $version'
    echo ''
    exit 1
fi

version=$1

SCRIPT=$(readlink -f "$0")
current_dir=$(dirname "${SCRIPT}")
repo_root=$(cd "${current_dir}/../.." && pwd)
code_path=$current_dir/src
mkdir -p "${code_path}"

manifest=${CF_RELEASE_MANIFEST:-$repo_root/release.yaml}

if [[ ! -f $manifest ]]; then
    echo "release manifest not found: $manifest" >&2
    exit 1
fi

# Read a dotted key out of release.yaml, failing loudly if it is missing --
# a silently empty ref would check out whatever HEAD happened to be.
function manifest_get() {
    local key=$1
    local value
    if ! value=$(python3 "${current_dir}/read-manifest.py" "$manifest" "$key"); then
        echo "release manifest $manifest has no key '$key'" >&2
        exit 1
    fi
    echo "$value"
}

cloudfile_server_url=${CF_SERVER_URL:-$(manifest_get 'forks.cloudfile_server.url')}
cloudfile_hub_url=${CF_HUB_URL:-$(manifest_get 'forks.cloudfile_hub.url')}
cloudfile_server_ref=${CF_SERVER_REF:-$(manifest_get 'forks.cloudfile_server.ref')}
cloudfile_hub_ref=${CF_HUB_REF:-$(manifest_get 'forks.cloudfile_hub.ref')}

seafobj_ref=${CF_SEAFOBJ_REF:-$(manifest_get 'upstream.seafobj')}
seafdav_ref=${CF_SEAFDAV_REF:-$(manifest_get 'upstream.seafdav')}
seafevents_ref=${CF_SEAFEVENTS_REF:-$(manifest_get 'upstream.seafevents')}
libsearpc_ref=${CF_LIBSEARPC_REF:-$(manifest_get 'upstream.libsearpc')}
libevhtp_ref=${CF_LIBEVHTP_REF:-$(manifest_get 'upstream.libevhtp')}

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
        libargon2-dev \
        gettext \
        make \
        nodejs \
        npm
}

function install_python_dependencies() {
    cat "${code_path}/seafevents/requirements.txt" \
        "${code_path}/seafdav/requirements.txt" \
        "${code_path}/seahub/requirements.txt" \
        > "${code_path}/requirements-thirdpart.txt"
    cd "${code_path}"

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

    pip3 install -r requirements-thirdpart.txt -t "${code_path}/thirdpartdir"
}

# clone_or_update <directory> <url>
function clone_or_update() {
    local dir=$1 url=$2
    cd "${code_path}"
    if [[ ! -e $dir ]]; then
        git clone "$url" "$dir"
    else
        # The remote may have moved between a stock and a fork build.
        git -C "$dir" remote set-url origin "$url"
    fi
}

# checkout_ref <directory> <ref>
#
# Accepts a branch, a tag or a raw commit SHA -- the manifest pins upstream
# components by SHA and the forks by branch.
function checkout_ref() {
    local dir=$1 ref=$2
    echo "Checking out ${dir} at ${ref}"
    cd "${code_path}/${dir}"
    git reset --hard
    git clean -xfd
    git fetch --tags origin
    if ! git checkout --detach "$ref" 2>/dev/null; then
        # A SHA that predates the shallow fetch, or a branch not yet local.
        git fetch origin "$ref"
        git checkout --detach FETCH_HEAD
    fi
    cd "${code_path}"
}

function clone_code() {
    clone_or_update libevhtp        https://github.com/haiwen/libevhtp.git
    clone_or_update libsearpc       https://github.com/haiwen/libsearpc.git
    clone_or_update seafobj         https://github.com/haiwen/seafobj.git
    clone_or_update seafdav         https://github.com/haiwen/seafdav.git
    clone_or_update seafevents      https://github.com/haiwen/seafevents.git
    # The build tree keeps upstream's directory names: seafile-build.py and
    # the release layout both expect "seafile-server" and "seahub".
    clone_or_update seafile-server  "$cloudfile_server_url"
    clone_or_update seahub          "$cloudfile_hub_url"
}

function fetch() {
    checkout_ref libevhtp       "$libevhtp_ref"
    checkout_ref libsearpc      "$libsearpc_ref"
    checkout_ref seafobj        "$seafobj_ref"
    checkout_ref seafdav        "$seafdav_ref"
    checkout_ref seafevents     "$seafevents_ref"
    checkout_ref seafile-server "$cloudfile_server_ref"
    checkout_ref seahub         "$cloudfile_hub_ref"
}

# Record what actually went into this build. Reproducing a report against
# "main" is impossible without it, since the forks are pinned by branch.
function write_build_info() {
    local out="${current_dir}/seafile-server-${version}/cloudfile-build-info.txt"
    {
        echo "product: ${version}"
        for d in seafile-server seahub seafobj seafdav seafevents libsearpc libevhtp; do
            echo "${d}: $(git -C "${code_path}/${d}" rev-parse HEAD)"
        done
    } > "$out"
    echo ''
    cat "$out"
}

# 构建 seahub 的前端与静态资源。
#
# 这一步不能省：cloudfile-build.py 的 Seahub 阶段 build_commands 是空的，它只
# 复制源码树。上游之所以看不出问题，是因为官方发行包取自 dist 分支——那里的
# media/assets 是 CI 预先构建好并提交进去的。我们直接从源码分支构建，所以必须
# 自己产出这些资源，否则镜像里根本没有 Web 界面。
#
# @seafile/* 都是公开 npm 包，不需要 NPM_TOKEN。
function build_seahub_frontend() {
    local seahub=${code_path}/seahub

    echo "Building seahub frontend"
    cd "${seahub}/frontend"
    npm ci --no-audit --no-fund 2>/dev/null || npm install --no-audit --no-fund
    CI=false npm run build

    echo "Making seahub dist files"
    cd "${seahub}"
    # make dist = compilemessages + compilejsi18n + collectstatic，
    # 三步都要 django 和 seahub 的依赖在 PYTHONPATH 上。
    PYTHONPATH="${code_path}/thirdpartdir:${seahub}/thirdpart:${PYTHONPATH:-}" \
        make dist

    if [[ ! -d ${seahub}/media/assets ]]; then
        echo "ERROR: media/assets 没有生成，镜像将没有 Web 界面" >&2
        exit 1
    fi

    cd "${code_path}"
}

function build() {
    cd "${current_dir}"
    python3 ./cloudfile-build.py \
        --version="${version}" \
        --builddir="${current_dir}" \
        --srcdir="${code_path}" \
        --thirdpartdir="${code_path}/thirdpartdir" \
        --mysql_config=/usr/bin/mariadb_config
}

echo ''
echo "Info: CloudFile version [ ${version} ]"
echo "      cloudfile-server ${cloudfile_server_url} @ ${cloudfile_server_ref}"
echo "      cloudfile-hub    ${cloudfile_hub_url} @ ${cloudfile_hub_ref}"
echo ''

install_dependencies
clone_code
fetch
install_python_dependencies
build_seahub_frontend
build
write_build_info

echo ''
echo "Info: Successfully built cloudfile-server-${version}"
echo ''
