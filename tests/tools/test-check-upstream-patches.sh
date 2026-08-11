#!/bin/bash

set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
docker_repo=$(cd "$here/../.." && pwd)
checker=$docker_repo/tools/check-upstream-patches.sh
fixture=$(mktemp -d)
trap 'rm -rf "$fixture"' EXIT

workspace=$fixture/workspace
repo=$workspace/cloudfile-hub
lists=$fixture/lists
mkdir -p "$repo" "$lists"

git -C "$repo" init -q
git -C "$repo" config user.name CloudFile-Test
git -C "$repo" config user.email cloudfile-test@example.invalid
printf 'upstream\n' > "$repo/tracked.txt"
git -C "$repo" add tracked.txt
git -C "$repo" commit -qm baseline
base=$(git -C "$repo" rev-parse HEAD)

printf 'cloudfile change\n' >> "$repo/tracked.txt"
git -C "$repo" commit -qam cloudfile-change
: > "$lists/cloudfile-hub.txt"

set +e
output=$(CF_PATCH_WORKSPACE="$workspace" \
         CF_PATCH_LISTS="$lists" \
         CF_UPSTREAM_BASE="$base" \
         "$checker" cloudfile-hub 2>&1)
rc=$?
set -e

if [[ $rc -ne 0 ]]; then
    echo "未登记上游改动应只警告，实际退出码为 $rc"
    echo "$output"
    exit 1
fi

grep -Fq '⚠ 新增了未登记的上游改动（仅警告）' <<< "$output"
grep -Fq 'tracked.txt' <<< "$output"
echo '未登记上游改动仅产生警告'
