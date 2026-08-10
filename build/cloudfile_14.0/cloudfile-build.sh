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

# Node 蹇呴』鏄惧紡瑁咃紝涓嶈兘鐢?apt 鐨勩€?
#
# Ubuntu 24.04 鐨?apt nodejs 鏄?18.19.1锛岃€?seahub 鍓嶇瑕?20+锛?
# css-minimizer 渚濊禆鍏ㄥ眬 crypto锛孨ode 19 鎵嶆妸瀹冨彉鎴愬叏灞€锛?8 涓婃瀯寤轰細浠?
# "ReferenceError: crypto is not defined" 澶辫触銆備笂娓?seahub 鐨?CI 涔熸槸鏄庣‘
# 鐢?setup-node@v3 node-version 20.x銆?
#
# GitHub runner 棰勮浜?Node 20+ 涓旀帓鍦?PATH 鍓嶉潰锛屾墍浠?CI 涓婄宸ц兘杩団€斺€?
# 涔熷氨鏄杩欎釜鏋勫缓鍏跺疄涓嶅彲澶嶇幇锛氫换浣曚汉鍦ㄥ共鍑€瀹瑰櫒閲屾瀯寤洪兘浼氬け璐ャ€傚浐瀹氱増鏈?
# 涔嬪悗锛孋I 涓庢湰鍦版嬁鍒扮殑鏄悓涓€涓?Node銆?
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

# 璇存槑锛歭ibsasl2-dev 涓?python3-cffi 鏄粰 build_seahub_frontend 閲岄偅娆″畬鏁翠緷璧?
# 瀹夎鐢ㄧ殑锛坧ython-ldap 缂栬瘧闇€瑕?sasl/sasl.h锛夈€備笂娓哥殑 dist workflow 瑁呯殑姝ｆ槸
# 杩欎竴缁勶紝杩欓噷淇濇寔涓€鑷淬€?

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
    local target=$ref
    echo "Checking out ${dir} at ${ref}"
    cd "${code_path}/${dir}"
    git reset --hard
    git clean -xfd
    git fetch --tags origin
    # A previously cloned directory has a local branch named "dev".  Checking
    # out that name after fetch would silently reuse its old tip instead of the
    # manifest's current remote branch.  Prefer origin/<branch>; tags and raw
    # SHAs deliberately keep their original spelling.
    if git show-ref --verify --quiet "refs/remotes/origin/${ref}"; then
        target="origin/${ref}"
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
        for d in seafile-server seahub seafobj seafdav seafevents libsearpc libevhtp; do
            echo "${d}: $(git -C "${code_path}/${d}" rev-parse HEAD)"
        done
    } > "$out"
    echo ''
    cat "$out"
}

# 鏋勫缓 seahub 鐨勫墠绔笌闈欐€佽祫婧愩€?
#
# 杩欎竴姝ヤ笉鑳界渷锛歝loudfile-build.py 鐨?Seahub 闃舵 build_commands 鏄┖鐨勶紝瀹冨彧
# 澶嶅埗婧愮爜鏍戙€備笂娓镐箣鎵€浠ョ湅涓嶅嚭闂锛屾槸鍥犱负瀹樻柟鍙戣鍖呭彇鑷?dist 鍒嗘敮鈥斺€旈偅閲岀殑
# media/assets 鏄?CI 棰勫厛鏋勫缓濂藉苟鎻愪氦杩涘幓鐨勩€傛垜浠洿鎺ヤ粠婧愮爜鍒嗘敮鏋勫缓锛屾墍浠ュ繀椤?
# 鑷繁浜у嚭杩欎簺璧勬簮锛屽惁鍒欓暅鍍忛噷鏍规湰娌℃湁 Web 鐣岄潰銆?
#
# @seafile/* 閮芥槸鍏紑 npm 鍖咃紝涓嶉渶瑕?NPM_TOKEN銆?
function build_seahub_frontend() {
    local seahub=${code_path}/seahub

    echo "Building seahub frontend"
    cd "${seahub}/frontend"
    npm ci --no-audit --no-fund 2>/dev/null || npm install --no-audit --no-fund
    CI=false npm run build

    echo "Generating seahub static assets"

    # compilejsi18n 涓?collectstatic 閮戒細 import seahub.settings锛岃€屽畠
    # `from seaserv import FILE_SERVER_PORT`銆傛墍浠?seafile-server 涓?libsearpc
    # 鐨?python 缁戝畾蹇呴』鍏堝彲瀵煎叆鈥斺€斿畠浠槸绾?Python锛屼笉蹇呯瓑 C 缂栬瘧瀹屾垚銆?
    #
    # 涓嶉渶瑕?ccnet-server锛歴easerv 鑷甫 ccnet_api锛宻eahub 浠庝笉 import ccnet 妯″潡
    # 鏈韩锛堜笂娓?dist 鑴氭湰甯︿笂瀹冨睘浜庨槻寰℃€у啑浣欙級銆?
    local pypath=${code_path}/site-packages
    rm -rf "$pypath"
    mkdir -p "$pypath"
    cp -r "${code_path}/seafile-server/python/seafile" "$pypath/"
    cp -r "${code_path}/seafile-server/python/seaserv" "$pypath/"
    cp -r "${code_path}/libsearpc/pysearpc" "$pypath/"

    # collectstatic 浼氬姞杞藉叏閮?INSTALLED_APPS锛屾墍浠?seahub 鐨勪緷璧栧繀椤婚兘鑳?import銆?
    # thirdpartdir 閲屾槸**涓嶅**鐨勶細install_python_dependencies 鍒绘剰娉ㄩ噴鎺変簡
    # captcha銆乨jangosaml2銆乸illow 绛夆€斺€斿畠浠敼鐢?Dockerfile 鐩存帴 pip 瀹夎杩涢暅鍍忥紝
    # 浠ヤ究鎷垮埌骞冲彴鐩稿叧鐨?wheel銆傛瀯寤烘湡娌℃湁闀滃儚锛屼簬鏄?`No module named 'captcha'`銆?
    #
    # 瑁呬竴浠藉畬鏁翠緷璧栧埌鍙湪鏋勫缓鏈熶娇鐢ㄧ殑鐩綍锛屼笉姹℃煋鏈€缁堜細鎵撳寘杩涘彂琛岀増鐨?
    # thirdpartdir銆侾YTHONPATH 閲屾斁鍦?thirdpartdir 涔嬪悗锛屽彂琛岀増閲岀殑鐗堟湰浼樺厛銆?
    local builddeps=${code_path}/build-only-deps
    if [[ ! -d $builddeps ]]; then
        pip3 install -r "${seahub}/requirements.txt" -t "$builddeps"
    fi

    # seaserv 鍦?import 鏈熻鍙栬繖涓や釜閰嶇疆鐩綍锛屾病鏈夊氨浼氭姤閿欍€傚唴瀹瑰彧瑕佽兘瑙ｆ瀽锛?
    # 杩欓噷涓嶄細鐪熺殑杩炴暟鎹簱銆?
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

    # 鍒绘剰涓嶇敤 `make dist`锛氬畠鐨?locale 鐩爣璋?django-admin 杩欎釜 console
    # script锛岃€?pip install -t 鎶婅剼鏈杩?thirdpartdir/bin锛屼笉鍦?PATH 涓婏紝
    # 浜庢槸 "django-admin: No such file or directory"銆傜敤 `python3 -m django`
    # 璋冨悓涓€涓懡浠わ紝鏃笉渚濊禆 PATH锛屼篃涓嶅繀淇敼涓婃父 Makefile銆?
    python3 -m django compilemessages
    python3 manage.py compilejsi18n
    python3 manage.py collectstatic --noinput -i admin -i termsandconditions

    if [[ ! -d ${seahub}/media/assets ]]; then
        echo "ERROR: media/assets 娌℃湁鐢熸垚锛岄暅鍍忓皢娌℃湁 Web 鐣岄潰" >&2
        exit 1
    fi
    if [[ ! -d ${seahub}/frontend/build ]]; then
        echo "ERROR: frontend/build 娌℃湁鐢熸垚锛屽墠绔湭琚墦鍖? >&2
        exit 1
    fi

    cd "${code_path}"
}

function build() {
    cd "${current_dir}"
    # cloudfile-build.py uses shutil.move("seafile-server", versioned_dir).
    # If the versioned directory from a prior build still exists, shutil moves
    # the fresh result *inside* it; Docker then copies the stale outer tree.
    # This directory is exclusively generated build output, so remove it
    # before every build to keep the image and recorded commit in sync.
    rm -rf "${current_dir}/seafile-server-${version}"
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
