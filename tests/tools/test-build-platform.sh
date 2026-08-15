#!/bin/bash

set -eu

here=$(cd "$(dirname "$0")" && pwd)
repo_root=$(cd "$here/../.." && pwd)
source "$repo_root/tools/build-platform.sh"

assert_eq() {
    local expected=$1 actual=$2
    if [[ $actual != "$expected" ]]; then
        echo "expected '$expected', got '$actual'" >&2
        exit 1
    fi
}

for value in linux/amd64 amd64 x86_64; do
    assert_eq linux/amd64 "$(cf_normalize_platform "$value")"
done
for value in linux/arm64 linux/arm64/v8 arm64 aarch64; do
    assert_eq linux/arm64 "$(cf_normalize_platform "$value")"
done

assert_eq amd64 "$(cf_platform_arch linux/amd64)"
assert_eq arm64 "$(cf_platform_arch linux/arm64)"

if cf_normalize_platform linux/s390x >/dev/null 2>&1; then
    echo 'unsupported platform was accepted' >&2
    exit 1
fi
