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
#   CF_BUILD_JOBS=8 ./cloudfile-build.sh 14.0.0-cf.0   (parallel C/Go jobs)

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

# ============================================================================
# 分层构建（layered build）
#
# 把原来的一次性长流程拆成 5 层，每层：
#   1. 打印明确的层横幅与耗时，长时间执行时能看到进度和每层结果；
#   2. 用「输入指纹」做产物缓存——输入未变化时跳过该层，避免每次都
#      从头重跑最耗时的 npm 构建与 C/Go 编译。
#
# 缓存键以「源码指纹」为基础：各组件按 commit 检出，提交 SHA 完整决定
# 源码内容（build-in-docker.sh 也保证只有已提交的代码进构建）。因此任何
# 组件 ref 变化都会使相关层的指纹失效、触发重建，不会误用陈旧产物。
#
# 逃生阀：CF_FORCE_REBUILD=1 忽略前端/发行包的产物层缓存，强制重新执行构建；
# ccache、Go、npm、pip 等低层缓存仍保留，这正是测量增量编译收益时需要的语义。
# 只测某一层时使用 CF_FORCE_FRONTEND_REBUILD=1 或 CF_FORCE_DIST_REBUILD=1，
# 避免为了测 C 编译而重复跑数分钟且输入完全未变的 webpack。
# ============================================================================
CF_FORCE_REBUILD=${CF_FORCE_REBUILD:-0}
CF_FORCE_FRONTEND_REBUILD=${CF_FORCE_FRONTEND_REBUILD:-0}
CF_FORCE_DIST_REBUILD=${CF_FORCE_DIST_REBUILD:-0}
CF_BUILD_JOBS=${CF_BUILD_JOBS:-$(nproc)}
if [[ ! $CF_BUILD_JOBS =~ ^[1-9][0-9]*$ ]]; then
    echo "CF_BUILD_JOBS must be a positive integer, got: ${CF_BUILD_JOBS}" >&2
    exit 2
fi
for flag in CF_FORCE_REBUILD CF_FORCE_FRONTEND_REBUILD CF_FORCE_DIST_REBUILD; do
    if [[ ${!flag} != 0 && ${!flag} != 1 ]]; then
        echo "${flag} must be 0 or 1, got: ${!flag}" >&2
        exit 2
    fi
done

layer_state_dir=${code_path}/.cf-layers
mkdir -p "$layer_state_dir"

# 七个组件联合 HEAD 的指纹。任何 ref 变化都会改变它。
function source_fingerprint() {
    {
        for d in seafile-server seahub seafobj seafdav seafevents libsearpc libevhtp; do
            printf '%s %s\n' "$d" "$(git -C "${code_path}/$d" rev-parse HEAD 2>/dev/null || echo no-repo)"
        done
    } | sha256sum | cut -d' ' -f1
}

function layer_hit() {
    local name=$1 fp=$2
    [[ -f ${layer_state_dir}/${name}.fp && $(<"${layer_state_dir}/${name}.fp") == "$fp" ]]
}

function layer_mark() {
    local name=$1 fp=$2
    echo "$fp" > "${layer_state_dir}/${name}.fp"
}

# 层进度横幅与耗时。
_layer_total=5
_layer_started_at=0

function layer_start() {
    local idx=$1 name=$2 desc=$3
    _layer_started_at=$(date +%s)
    printf '\n============================================================\n'
    printf '[%d/%d] %s\n      %s\n' "$idx" "$_layer_total" "$name" "$desc"
    printf '============================================================\n'
}

function layer_done() {
    local name=$1
    printf '[done] %s (%ds)\n' "$name" "$(( $(date +%s) - _layer_started_at ))"
}

function install_dependencies() {
    if [[ ${CLOUDFILE_BUILD_BASE:-false} == true ]]; then
        echo "Using system dependencies from the CloudFile build base"
        return
    fi

    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        build-essential \
        tzdata \
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

    if [[ -x ${prefix}/${name}/bin/node ]]; then
        export PATH="${prefix}/${name}/bin:${PATH}"
        echo "Using cached Node ${NODE_VERSION} (${arch})"
        node --version
        npm --version
        return
    fi

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

    local cache_dir=${code_path}/.cache
    local target=${code_path}/thirdpartdir
    local stamp=${cache_dir}/requirements-thirdpart.sha256
    local digest
    mkdir -p "$cache_dir"
    # Include the Python ABI as well as the CPU architecture: thirdpartdir
    # contains compiled extensions, so neither an amd64 cache nor a cache from
    # another Python minor version is safe to reuse.
    digest=$(python_requirements_digest requirements-thirdpart.txt)
    if [[ -d $target && -f $stamp && $(<"$stamp") == "$digest" ]]; then
        echo "Using cached Python runtime dependencies"
        return
    fi

    # Remove the old stamp first. If pip is interrupted after creating target,
    # the next run must not accept that partial directory as a cache hit.
    rm -f "$stamp"
    rm -rf "$target"
    mkdir -p "$target"
    pip3 install -r requirements-thirdpart.txt -t "$target"
    printf '%s\n' "$digest" > "${stamp}.tmp"
    mv "${stamp}.tmp" "$stamp"
}

function python_requirements_digest() {
    local requirements=$1
    {
        echo 'python-cache-v2'
        echo "arch=$(uname -m)"
        python3 -c 'import sysconfig; print("soabi=" + str(sysconfig.get_config_var("SOABI")))'
        sha256sum "$requirements"
    } | sha256sum | cut -d' ' -f1
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
    local target=$ref
    echo "Checking out ${dir} at ${ref}"
    cd "${code_path}/${dir}"
    git reset --hard
    if [[ $dir == seahub ]]; then
        # node_modules is a 1 GiB derived tree. Its own lock/ABI stamp below
        # decides whether it is reusable; deleting it here guarantees every
        # build pays npm ci even when package inputs are byte-for-byte equal.
        git clean -xfd -e frontend/node_modules/
    else
        git clean -xfd
    fi

    # Five upstream components are immutable full SHAs. Once their objects are
    # present, fetching the same repositories on every build only adds network
    # latency. Fork refs are branches, so they still fetch on every run and can
    # never silently reuse a stale local branch.
    if [[ $ref =~ ^[0-9a-fA-F]{40}$ ]] && git cat-file -e "${ref}^{commit}" 2>/dev/null; then
        echo "Using locally cached commit ${ref}"
    elif git fetch --no-tags origin "$ref"; then
        target=FETCH_HEAD
    else
        # Compatibility fallback for servers that reject fetching a raw SHA or
        # require tags to be advertised before the ref can be resolved.
        git fetch --tags origin
        if git show-ref --verify --quiet "refs/remotes/origin/${ref}"; then
            target="origin/${ref}"
        fi
    fi
    if ! git checkout --detach "$target" 2>/dev/null; then
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
        echo "architecture: $(uname -m)"
        echo "jobs: ${CF_BUILD_JOBS}"
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
    local started

    echo "Building seahub frontend"
    cd "${seahub}/frontend"
    # install_frontend_dependencies runs in the deps layer, in parallel with
    # pip, so this layer only does webpack + static assets.
    started=$(date +%s)
    CI=false npm run build
    echo "[frontend] webpack ($(( $(date +%s) - started ))s)"
    started=$(date +%s)
    save_frontend_tool_cache "$seahub"
    echo "[frontend] loader cache save ($(( $(date +%s) - started ))s)"

    echo "Generating seahub static assets"
    started=$(date +%s)

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

    # collectstatic loads every INSTALLED_APPS, so captcha/mysqlclient/Pillow/
    # djangosaml2 must be importable. install_python_dependencies comments those
    # out of thirdpartdir (they ship via the runtime image for platform wheels),
    # but the CloudFile build base image already pip-installs the same pins
    # system-wide. With no build-time dependency tree, Python falls through to
    # those system site-packages -- no separate recompile on every cold build.

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
    export PYTHONPATH="${pypath}:${code_path}/thirdpartdir:${seahub}/thirdpart:${PYTHONPATH:-}"

    cd "${seahub}"

    # 刻意不用 `make dist`：它的 locale 目标调 django-admin 这个 console
    # script，而 pip install -t 把脚本装进 thirdpartdir/bin，不在 PATH 上，
    # 于是 "django-admin: No such file or directory"。用 `python3 -m django`
    # 调同一个命令，既不依赖 PATH，也不必修改上游 Makefile。
    python3 -m django compilemessages
    python3 manage.py compilejsi18n
    python3 manage.py collectstatic --noinput -i admin -i termsandconditions
    echo "[frontend] Django static assets ($(( $(date +%s) - started ))s)"

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

function frontend_dependencies_digest() {
    local frontend=$1
    {
        echo 'frontend-dependencies-v1'
        echo "platform=$(uname -s)-$(uname -m)"
        echo "node=$(node --version)"
        echo "node-modules-abi=$(node -p 'process.versions.modules')"
        echo "npm=$(npm --version)"
        sha256sum "${frontend}/package.json" "${frontend}/package-lock.json"
    } | sha256sum | cut -d' ' -f1
}

function install_frontend_dependencies() {
    local seahub=$1
    local frontend=${seahub}/frontend
    local stamp=${code_path}/.cache/frontend-node-modules.sha256
    local digest
    digest=$(frontend_dependencies_digest "$frontend")

    # npm runs in the package directory; make this callable from a parallel
    # deps step whose cwd is not the frontend tree.
    cd "${frontend}"

    if [[ -d ${frontend}/node_modules &&
          -f ${frontend}/node_modules/.package-lock.json &&
          -f $stamp && $(<"$stamp") == "$digest" ]]; then
        echo "Using cached frontend node_modules"
    else
        # npm ci removes node_modules before installing. Remove the stamp first
        # so an interrupted install can never make a partial tree look valid.
        rm -f "$stamp"
        npm ci --prefer-offline --no-audit --no-fund
        printf '%s\n' "$digest" > "${stamp}.tmp"
        mv "${stamp}.tmp" "$stamp"
    fi

    # npm ci necessarily deletes loader caches with node_modules. Restore only
    # the small derived caches; caching the full 1 GiB dependency tree in CI is
    # slower to upload/download than reinstalling it from npm's package cache.
    local tool_cache=${CF_FRONTEND_TOOL_CACHE_DIR:-${code_path}/.cache/frontend-tools}
    if [[ -d $tool_cache ]]; then
        mkdir -p "${frontend}/node_modules/.cache"
        cp -a "${tool_cache}/." "${frontend}/node_modules/.cache/"
    fi
}

function save_frontend_tool_cache() {
    local seahub=$1
    local source=${seahub}/frontend/node_modules/.cache
    local target=${CF_FRONTEND_TOOL_CACHE_DIR:-${code_path}/.cache/frontend-tools}
    [[ -d $source ]] || return

    local temporary=${target}.tmp.$$
    rm -rf "$temporary"
    mkdir -p "$temporary"
    cp -a "${source}/." "$temporary/"
    rm -rf "$target"
    mv "$temporary" "$target"
}

function frontend_fingerprint() {
    {
        # Only inputs that can affect webpack/collectstatic belong here. Using
        # source_fingerprint made a one-line C or Go change invalidate the full
        # frontend layer even though none of its inputs had changed.
        echo "seahub: $(git -C "${code_path}/seahub" rev-parse HEAD)"
        echo "server-python: $(git -C "${code_path}/seafile-server" rev-parse HEAD:python)"
        echo "libsearpc-python: $(git -C "${code_path}/libsearpc" rev-parse HEAD:pysearpc)"
        echo "dependencies: $(frontend_dependencies_digest "${code_path}/seahub/frontend")"
        declare -f build_seahub_frontend frontend_dependencies_digest \
            install_frontend_dependencies save_frontend_tool_cache \
            frontend_fingerprint layer_frontend
    } | sha256sum | cut -d' ' -f1
}

# 前端产物（frontend/build、media/assets）落在 seahub 源码树内，会被 fetch
# 的 `git clean -xfd` 清掉。所以命中时从缓存目录恢复产物，而不是跳过整层
# —— 否则下一轮 fetch 之后产物就没了。恢复只花复制时间，远快于
# npm ci + build + compilemessages + collectstatic 一整趟。
function layer_frontend() {
    local seahub=${code_path}/seahub
    local cache=${code_path}/.cache/frontend-build
    local fp
    fp=$(frontend_fingerprint)

    if [[ ${CF_FORCE_REBUILD} != 1 && ${CF_FORCE_FRONTEND_REBUILD} != 1 ]] \
        && layer_hit frontend "$fp" \
        && [[ -d ${cache}/build && -d ${cache}/media-assets ]]; then
        echo "[cache] 前端产物命中，跳过 npm build / collectstatic，从缓存恢复"
        rm -rf "${seahub}/frontend/build" "${seahub}/media/assets"
        mkdir -p "${seahub}/frontend" "${seahub}/media"
        cp -a "${cache}/build" "${seahub}/frontend/build"
        cp -a "${cache}/media-assets" "${seahub}/media/assets"
        layer_mark frontend "$fp"
        return
    fi

    build_seahub_frontend

    rm -rf "$cache"
    mkdir -p "$cache"
    cp -a "${seahub}/frontend/build" "$cache/build"
    cp -a "${seahub}/media/assets" "$cache/media-assets"
    layer_mark frontend "$fp"
}

function build_compile() {
    cd "${current_dir}"
    # cloudfile-build.py compiles into builddir/seafile-server/ and only the
    # package step renames it to seafile-server-<version>. Remove both names so
    # a stale tree can never leak into a fresh compile, then compile C/Go.
    # Parallelism only affects wall time, never the artifact, so it is
    # deliberately left out of dist_fingerprint and can be overridden freely.
    rm -rf "${current_dir}/seafile-server" "${current_dir}/seafile-server-${version}"
    python3 ./cloudfile-build.py --compile-only \
        --version="${version}" \
        --builddir="${current_dir}" \
        --srcdir="${code_path}" \
        --thirdpartdir="${code_path}/thirdpartdir" \
        --jobs="$CF_BUILD_JOBS" \
        --mysql_config=/usr/bin/mariadb_config
}

function build_package() {
    cd "${current_dir}"
    # Reuses the seafile-server/ tree left by build_compile; do not remove it.
    python3 ./cloudfile-build.py --package-only \
        --version="${version}" \
        --builddir="${current_dir}" \
        --srcdir="${code_path}" \
        --thirdpartdir="${code_path}/thirdpartdir" \
        --jobs="$CF_BUILD_JOBS" \
        --mysql_config=/usr/bin/mariadb_config
}

function dist_fingerprint() {
    {
        source_fingerprint
        echo "version: ${version}"
        echo "arch: $(uname -m)"
        echo "script: $(sha256sum "${current_dir}/cloudfile-build.sh" | cut -d' ' -f1)"
        echo "builder: $(sha256sum "${current_dir}/cloudfile-build.py" | cut -d' ' -f1)"
    } | sha256sum | cut -d' ' -f1
}

# 发行包（seafile-server-<version>/）是 C/Go 编译 + 打包的最终产物。编译已在
# 第 3 层与 pip/npm 并行完成（build_compile），这里只做打包：把前端产物、thirdpart
# 与编译出的二进制组装进 seafile-server-<version>/ 并 strip。命中时直接复用已有
# 发行包；write_build_info 仍然每次重写，保证产物里的构建信息与源码一致。
function layer_dist() {
    local fp
    fp=$(dist_fingerprint)

    if [[ ${CF_FORCE_REBUILD} != 1 && ${CF_FORCE_DIST_REBUILD} != 1 ]] \
        && layer_hit dist "$fp" \
        && [[ -d "${current_dir}/seafile-server-${version}" ]]; then
        echo "[cache] 发行包命中，跳过打包"
        write_build_info
        layer_mark dist "$fp"
        return
    fi

    build_package
    write_build_info
    layer_mark dist "$fp"
}

echo ''
echo "Info: CloudFile version [ ${version} ]"
echo "      cloudfile-server ${cloudfile_server_url} @ ${cloudfile_server_ref}"
echo "      cloudfile-hub    ${cloudfile_hub_url} @ ${cloudfile_hub_ref}"
echo ''

layer_start 1 deps "系统依赖与 Node 工具链"
install_dependencies
install_nodejs
layer_done deps

layer_start 2 source "克隆并检出七个组件（commit 锁定）"
clone_code
fetch
layer_done source

layer_start 3 deps-compile "Python 依赖 / npm / C-Go 编译（并行）"

# The frontend and dist layers rebuild only when their inputs changed. Decide
# both up front so the three independent long steps -- pip, npm and the C/Go
# compile -- run concurrently. Packaging is deliberately NOT parallel: it
# copies the seahub tree including the frontend's webpack/collectstatic output,
# so it runs in layer 5 after layer 4.
if [[ ${CF_FORCE_REBUILD} != 1 && ${CF_FORCE_FRONTEND_REBUILD} != 1 ]] \
    && layer_hit frontend "$(frontend_fingerprint)" \
    && [[ -d ${code_path}/.cache/frontend-build/build \
        && -d ${code_path}/.cache/frontend-build/media-assets ]]; then
    need_npm=0
else
    need_npm=1
fi

if [[ ${CF_FORCE_REBUILD} != 1 && ${CF_FORCE_DIST_REBUILD} != 1 ]] \
    && layer_hit dist "$(dist_fingerprint)" \
    && [[ -d "${current_dir}/seafile-server-${version}" ]]; then
    need_dist=0
else
    need_dist=1
fi

install_python_dependencies &
pip_pid=$!
if [[ $need_npm == 1 ]]; then
    install_frontend_dependencies "${code_path}/seahub" &
    npm_pid=$!
fi
if [[ $need_dist == 1 ]]; then
    build_compile &
    dist_pid=$!
fi

wait "$pip_pid" || exit 1
if [[ $need_npm == 1 ]]; then wait "$npm_pid" || exit 1; fi
if [[ $need_dist == 1 ]]; then wait "$dist_pid" || exit 1; fi
layer_done deps-compile

layer_start 4 frontend "Seahub 前端与静态资源"
layer_frontend
layer_done frontend

layer_start 5 dist "发行包组装（打包 + strip）"
layer_dist
layer_done dist

echo ''
echo "Info: Successfully built cloudfile-server-${version}"
echo ''
