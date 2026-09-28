#!/bin/bash
#
# 检查三个 fork 修改的上游文件是否仍与登记清单一致。
#
# 这是 CloudFile 唯一真正的 fork 维护成本指标：新增文件几乎不产生同步冲突，
# 修改上游文件则每次跟随上游都要再付一次。清单一旦悄悄变长，同步的工作量就
# 会不知不觉上升，而且没人会注意到。脚本保留详细警告和可更新清单，
# 但不再阻断快速检查或 CI。
#
#   ./tools/check-upstream-patches.sh              # 检查全部三个仓库
#   ./tools/check-upstream-patches.sh cloudfile-hub
#   ./tools/check-upstream-patches.sh --worktree   # 额外检查未提交修改
#   ./tools/check-upstream-patches.sh --update     # 把当前状态写回清单
#
# 需要三个仓库并排 checkout，且各自配好 upstream remote：
#   git remote add upstream https://github.com/haiwen/<repo>.git
#
# 退出码：0 = 检查完成（包括发现清单差异或环境缺失）；2 = 命令行参数错误。

set -u

here=$(cd "$(dirname "$0")" && pwd)
docker_repo=$(cd "$here/.." && pwd)
workspace=${CF_PATCH_WORKSPACE:-$(dirname "$docker_repo")}
lists=${CF_PATCH_LISTS:-$docker_repo/docs/upstream-patches}

ALL_REPOS=(cloudfile-server cloudfile-hub cloudfile-docker)

update=0
include_worktree=0
repos=()
for arg in "$@"; do
    case "$arg" in
        --update) update=1 ;;
        --worktree) include_worktree=1 ;;
        -*) echo "unknown option: $arg" >&2; exit 2 ;;
        *)  repos+=("$arg") ;;
    esac
done
[[ ${#repos[@]} -eq 0 ]] && repos=("${ALL_REPOS[@]}")

# 解析比较基线，按可靠性排序：
#
#   1. $CF_UPSTREAM_BASE      —— 显式指定
#   2. upstream/master        —— 本地开发的常态；用三点 diff，合并基点会随
#                                sync 自动前移，不需要人工维护
#   3. release.yaml 里的锚点 SHA —— CI 用。只要 fetch 一个 commit，不必拉整个
#                                上游历史（seahub 很大）。用两点 diff，因为
#                                浅克隆下没有合并基点可算
#
# 输出 "<baseref> <two|three>"。
resolve_base() {
    local repo_dir=$1 repo=$2

    if [[ -n ${CF_UPSTREAM_BASE:-} ]]; then
        echo "$CF_UPSTREAM_BASE two"; return 0
    fi

    if git -C "$repo_dir" rev-parse --verify -q upstream/master >/dev/null; then
        echo "upstream/master three"; return 0
    fi

    local key
    case "$repo" in
        cloudfile-server) key=upstream.seafile_server ;;
        cloudfile-hub)    key=upstream.seahub ;;
        cloudfile-docker) key=upstream.seafile_docker ;;
        *) return 1 ;;
    esac

    local sha
    sha=$(python3 "$docker_repo/build/cloudfile_14.0/read-manifest.py" \
          "$docker_repo/release.yaml" "$key" 2>/dev/null) || return 1

    git -C "$repo_dir" cat-file -e "$sha^{commit}" 2>/dev/null || return 1
    echo "$sha two"
}

# 列出相对基线被修改的上游文件。
#
# 只算基线里已存在的文件：新增文件不参与合并冲突，把它们混进来会让这个指标
# 失去意义。
list_patched() {
    local repo_dir=$1 base=$2 mode=$3
    local range
    [[ $mode == three ]] && range="$base...HEAD" || range="$base HEAD"

    # shellcheck disable=SC2086
    {
        git -C "$repo_dir" diff --name-only $range
        # CI 只约束已提交差异，避免前置构建生成的 tracked 文件造成误报。
        # 本地提交前需要检查 staged/unstaged 修改时显式传 --worktree。
        if [[ $include_worktree -eq 1 ]]; then
            git -C "$repo_dir" diff --name-only HEAD
        fi
    } | sort -u | while read -r f; do
        [[ -z $f ]] && continue
        if git -C "$repo_dir" cat-file -e "$base:$f" 2>/dev/null; then
            echo "$f"
        fi
    done | sort
}

for repo in "${repos[@]}"; do
    repo_dir=$workspace/$repo
    list=$lists/$repo.txt

    echo "=== $repo ==="

    if [[ ! -d $repo_dir/.git ]]; then
        echo "  ⚠ 跳过：$repo_dir 不是 git 仓库（仅警告）" >&2
        continue
    fi
    if [[ ! -f $list ]]; then
        echo "  ⚠ 跳过：清单 $list 不存在（仅警告）" >&2
        continue
    fi
    if ! read -r base mode < <(resolve_base "$repo_dir" "$repo"); then
        echo "  ⚠ 跳过：无法确定比较基线（仅警告）。任选其一：" >&2
        echo "    git -C $repo_dir remote add upstream https://github.com/haiwen/<repo>.git" >&2
        echo "    git -C $repo_dir fetch upstream master" >&2
        echo "  或 fetch release.yaml 里记录的锚点 SHA，或设置 CF_UPSTREAM_BASE。" >&2
        continue
    fi

    actual=$(list_patched "$repo_dir" "$base" "$mode")

    if [[ $update -eq 1 ]]; then
        # 保留清单开头的注释块，只替换文件列表。
        {
            grep -E '^\s*(#|$)' "$list" | sed -e :a -e '/^\n*$/{$d;N;ba' -e '}'
            echo "$actual"
        } > "$list.tmp" && mv "$list.tmp" "$list"
        echo "  已更新清单：$(echo "$actual" | grep -c . ) 个文件"
        continue
    fi

    expected=$(grep -vE '^\s*(#|$)' "$list" | sort)

    added=$(comm -23 <(echo "$actual") <(echo "$expected"))
    removed=$(comm -13 <(echo "$actual") <(echo "$expected"))

    if [[ -n $added ]]; then
        echo "  ⚠ 新增了未登记的上游改动（仅警告）："
        echo "$added" | sed 's/^/      /'
        echo "    每一个都会在跟随上游时反复产生冲突。先确认无法改成新增文件，"
        echo "    再更新 docs/upstream-patches/$repo.txt 与 BRANCHING.md。"
    fi

    if [[ -n $removed ]]; then
        echo "  ! 清单里有已不再修改的文件（清单过期，无害）："
        echo "$removed" | sed 's/^/      /'
    fi

    if [[ -z $added && -z $removed ]]; then
        echo "  ✓ $(echo "$expected" | grep -c .) 个上游文件，与清单一致"
    fi
done

exit 0
