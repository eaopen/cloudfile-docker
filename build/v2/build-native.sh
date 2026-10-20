#!/usr/bin/env bash
# Build only the prepared native source. Invoke inside the CE14 build image.
set -euo pipefail
source_root=${1:?prepared source directory required}
prefix=${2:?dedicated install prefix required}
target=${3:-all}
case "$target" in all|sources|dependencies|server) ;; *) exit 2 ;; esac
jobs=${CF_V2_BUILD_JOBS:-4}
[[ $jobs =~ ^[1-9][0-9]*$ ]] || exit 2
if [[ $target != dependencies ]]; then
    python3 "$(dirname "$0")/check-native-source.py" "$source_root/seafile-server"
    # The host validates the full source receipt before Docker packaging.
    # This server-only stage intentionally does not COPY the combined receipt:
    # a Hub-only SHA update must not recompile native C/Go.
    test -f "$source_root/seafile-server/scripts/sql/mysql/cloudfile-v2.sql"
    test -f "$source_root/seafile-server/common/cf-v2-storage.c"
    test ! -d "$source_root/seahub/cloudfile_extensions"
    test ! -f "$source_root/seafile-server/common/cf-ext.c"
fi

fetch_dependency() {
    local project=$1 revision=$2
    local target="$source_root/$project"
    if [[ ! -d $target/.git ]]; then
        git init -q "$target"
        git -C "$target" remote add origin "https://github.com/haiwen/$project.git"
        git -C "$target" fetch --depth=1 origin "$revision"
        git -C "$target" checkout --detach FETCH_HEAD
    fi
    [[ $(git -C "$target" rev-parse HEAD) == "$revision" ]] || exit 2
}

if [[ $target != server ]]; then
fetch_dependency libsearpc 23d5df62815fb3b7825bf4e1a28b29af701e8cb2
fetch_dependency libevhtp 91071e2f20749cd469b87ac2ef1c158dc2a6806f
fi
[[ $target != sources ]] || exit 0

mkdir -p "$prefix"
export PATH="$prefix/bin:$PATH"
export PKG_CONFIG_PATH="$prefix/lib/pkgconfig:${PKG_CONFIG_PATH:-}"
export LD_LIBRARY_PATH="$prefix/lib:${LD_LIBRARY_PATH:-}"
export CFLAGS="-O2 -I$prefix/include"
export LDFLAGS="-L$prefix/lib"

# Dependency-only layers survive changes to application C/Go source.
if [[ $target != server ]]; then
(
    cd "$source_root/libsearpc"
    ./autogen.sh
    ./configure --prefix="$prefix"
    make -j"$jobs"
    make install
)
cmake -S "$source_root/libevhtp" -B "$source_root/libevhtp/build-v2" \
    -DEVHTP_DISABLE_SSL=ON -DEVHTP_BUILD_SHARED=OFF -DCMAKE_INSTALL_PREFIX="$prefix"
cmake --build "$source_root/libevhtp/build-v2" -j"$jobs"
cmake --install "$source_root/libevhtp/build-v2"
fi
[[ $target != dependencies ]] || exit 0
(
    cd "$source_root/seafile-server"
    ./autogen.sh
    ./configure --prefix="$prefix" --with-mysql=/usr/bin/mariadb_config
    make -j"$jobs"
    make install
    cd fileserver
    go build -o "$prefix/bin/fileserver" .
)
# Upstream's -v/-h deliberately exit 1 without output; those are not probes.
test -x "$prefix/bin/seaf-server"
test -x "$prefix/bin/fileserver"
printf 'Prepared native CE14 C and Go binaries built successfully\n'
