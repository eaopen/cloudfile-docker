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
        libsasl2-dev \
        python3-cffi \
        xz-utils
}

# Node 必须显式装，不能用 apt 的。
#
# Ubuntu 24.04 的 apt nodejs 是 18.19.1，而 seahub 前端要 20+：
# css-minimizer 依赖全局 crypto，Node 19 才把它变成全局，18 上构建会以
# "ReferenceError: crypto is not defined" 失败。上游 seahub 的 CI 也是明确
# 用 setup-node@v3 node-version 20.x。
#
# GitHub runner 预装了 Node 20+ 且排在 PATH 前面，所以 CI 上碰巧能过——
# 也就是说这个构建其实不可复现：任何人在干净容器里构建都会失败。固定版本
# 之后，CI 与本地拿到的是同一个 Node。
NODE_VERSION=${CF_NODE_VERSION:-20.20.2}

function install_nodejs() {
    local arch
    case "$(uname -m)" in
        x86_64)        arch=x64 ;;
        aarch64|arm64) arch=arm64 ;;
        *) echo "unsupported architecture: $(uname -m)" >&2; exit 1 ;;
    esac

    local name=node-v${NODE_VERSION}-linux-${arch}
    local prefix=/usr/local/lib/nodejs

    echo "Installing Node ${NODE_VERSION} (${arch})"
    mkdir -p "$prefix"
    curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/${name}.tar.xz" \
        | tar -xJ -C "$prefix"

    export PATH="${prefix}/${name}/bin:${PATH}"
    node --version
    npm --version
}

# 说明：libsasl2-dev 与 python3-cffi 是给 build_seahub_frontend 里那次完整依赖
# 安装用的（python-ldap 编译需要 sasl/sasl.h）。上游的 dist workflow 装的正是
# 这一组，这里保持一致。

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

    apply_patches seafdav
}

# apply_patches <component>
#
# Apply patches/<component>/*.patch to the checked-out source.
#
# Used for upstream components CloudFile does not fork. seafdav needs one --
# its read paths never consulted check_permission_by_path, so a folder the
# directory ACL made invisible was still listed over WebDAV. Forking it for a
# fifty-line change would mean a fourth repository to keep synced forever;
# a patch that must apply cleanly is the cheaper contract.
#
# Failure to apply is fatal on purpose. Skipping a security patch because
# upstream moved a line is how a fixed hole silently reopens -- and the whole
# point of pinning these components by SHA is that this cannot happen without
# someone bumping the pin, at which point they are the right person to rebase
# the patch.
function apply_patches() {
    local component=$1
    local dir="${repo_root}/patches/${component}"
    [[ -d $dir ]] || return 0

    local patch
    for patch in "$dir"/*.patch; do
        [[ -e $patch ]] || continue
        echo "Applying $(basename "$patch") to ${component}"
        if ! git -C "${code_path}/${component}" apply "$patch"; then
            echo "failed to apply $(basename "$patch") to ${component}" >&2
            echo "the pinned ref may have moved -- rebase the patch against" >&2
            echo "the new ref. Do not skip it: this one closes a hole in" >&2
            echo "WebDAV read-side permission enforcement." >&2
            exit 1
        fi
    done
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

    echo "Generating seahub static assets"

    # compilejsi18n 与 collectstatic 都会 import seahub.settings，而它
    # `from seaserv import FILE_SERVER_PORT`。所以 seafile-server 与 libsearpc
    # 的 python 绑定必须先可导入——它们是纯 Python，不必等 C 编译完成。
    #
    # 不需要 ccnet-server：seaserv 自带 ccnet_api，seahub 从不 import ccnet 模块
    # 本身（上游 dist 脚本带上它属于防御性冗余）。
    local pypath=${code_path}/site-packages
    rm -rf "$pypath"
    mkdir -p "$pypath"
    cp -r "${code_path}/seafile-server/python/seafile" "$pypath/"
    cp -r "${code_path}/seafile-server/python/seaserv" "$pypath/"
    cp -r "${code_path}/libsearpc/pysearpc" "$pypath/"

    # collectstatic 会加载全部 INSTALLED_APPS，所以 seahub 的依赖必须都能 import。
    # thirdpartdir 里是**不够**的：install_python_dependencies 刻意注释掉了
    # captcha、djangosaml2、pillow 等——它们改由 Dockerfile 直接 pip 安装进镜像，
    # 以便拿到平台相关的 wheel。构建期没有镜像，于是 `No module named 'captcha'`。
    #
    # 装一份完整依赖到只在构建期使用的目录，不污染最终会打包进发行版的
    # thirdpartdir。PYTHONPATH 里放在 thirdpartdir 之后，发行版里的版本优先。
    local builddeps=${code_path}/build-only-deps
    if [[ ! -d $builddeps ]]; then
        pip3 install -r "${seahub}/requirements.txt" -t "$builddeps"
    fi

    # seaserv 在 import 期读取这两个配置目录，没有就会报错。内容只要能解析，
    # 这里不会真的连数据库。
    local confdir=${code_path}/build-conf
    mkdir -p "$confdir" "${code_path}/build-seafile-data"
    cat > "$confdir/ccnet.conf" <<'CONF'
[General]
SERVICE_URL = http://127.0.0.1:8000
[Database]
CREATE_TABLES=true
CONF
    cat > "$confdir/seafile.conf" <<'CONF'
[fileserver]
port=8082
[database]
create_tables=true
CONF
    export SEAFILE_CENTRAL_CONF_DIR=$confdir
    export SEAFILE_DATA_DIR=${code_path}/build-seafile-data
    export PYTHONPATH="${pypath}:${code_path}/thirdpartdir:${seahub}/thirdpart:${builddeps}:${PYTHONPATH:-}"

    cd "${seahub}"

    # 刻意不用 `make dist`：它的 locale 目标调 django-admin 这个 console
    # script，而 pip install -t 把脚本装进 thirdpartdir/bin，不在 PATH 上，
    # 于是 "django-admin: No such file or directory"。用 `python3 -m django`
    # 调同一个命令，既不依赖 PATH，也不必修改上游 Makefile。
    python3 -m django compilemessages
    python3 manage.py compilejsi18n
    python3 manage.py collectstatic --noinput -i admin -i termsandconditions

    if [[ ! -d ${seahub}/media/assets ]]; then
        echo "ERROR: media/assets 没有生成，镜像将没有 Web 界面" >&2
        exit 1
    fi
    if [[ ! -d ${seahub}/frontend/build ]]; then
        echo "ERROR: frontend/build 没有生成，前端未被打包" >&2
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
install_nodejs
clone_code
fetch
install_python_dependencies
build_seahub_frontend
build
write_build_info

echo ''
echo "Info: Successfully built cloudfile-server-${version}"
echo ''
