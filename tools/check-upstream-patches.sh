#!/bin/bash
#
# 检查三个 fork 修改的上游文件是否仍与登记清单一致。
#
# 这是 CloudFile 唯一真正的 fork 维护成本指标：新增文件几乎不产生同步冲突，
# 修改上游文件则每次跟随上游都要再付一次。清单一旦悄悄变长，同步的工作量就
# 会不知不觉上升，而且没人会注意到——所以用脚本卡住，而不是靠自觉。
#
#   ./tools/check-upstream-patches.sh              # 检查全部三个仓库
#   ./tools/check-upstream-patches.sh cloudfile-hub
#   ./tools/check-upstream-patches.sh --update     # 把当前状态写回清单
#
# 需要三个仓库并排 checkout，且各自配好 upstream remote：
#   git remote add upstream https://github.com/haiwen/<repo>.git
#
# 退出码：0 = 一致；1 = 清单变长（拒绝）；2 = 环境问题。

set -u

here=$(cd "$(dirname "$0")" && pwd)
docker_repo=$(cd "$here/.." && pwd)
workspace=$(dirname "$docker_repo")
lists=$docker_repo/docs/upstream-patches

ALL_REPOS=(cloudfile-server cloudfile-hub cloudfile-docker)

update=0
repos=()
for arg in "$@"; do
    case "$arg" in
        --update) update=1 ;;
        -*) echo "unknown option: $arg" >&2; exit 2 ;;
        *)  repos+=("$arg") ;;
    esac
done
[[ ${#repos[@]} -eq 0 ]] && repos=("${ALL_REPOS[@]}")

status=0

# 列出相对 upstream/master 被修改的上游文件。
#
# 只算 upstream 里已存在的文件：新增文件不参与合并冲突，把它们混进来会让这个
# 指标失去意义。
list_patched() {
    local repo_dir=$1
    git -C "$repo_dir" diff --name-only upstream/master...HEAD | while read -r f; do
        [[ -z $f ]] && continue
        if git -C "$repo_dir" cat-file -e "upstream/master:$f" 2>/dev/null; then
            echo "$f"
        fi
    done | sort
}

for repo in "${repos[@]}"; do
    repo_dir=$workspace/$repo
    list=$lists/$repo.txt

    echo "=== $repo ==="

    if [[ ! -d $repo_dir/.git ]]; then
        echo "  跳过：$repo_dir 不是 git 仓库" >&2
        status=2
        continue
    fi
    if [[ ! -f $list ]]; then
        echo "  跳过：清单 $list 不存在" >&2
        status=2
        continue
    fi
    if ! git -C "$repo_dir" rev-parse --verify -q upstream/master >/dev/null; then
        echo "  跳过：没有 upstream/master，先执行" >&2
        echo "    git -C $repo_dir fetch upstream master" >&2
        status=2
        continue
    fi

    actual=$(list_patched "$repo_dir")

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
        echo "  ✗ 新增了未登记的上游改动："
        echo "$added" | sed 's/^/      /'
        echo "    每一个都会在跟随上游时反复产生冲突。先确认无法改成新增文件，"
        echo "    再更新 docs/upstream-patches/$repo.txt 与 BRANCHING.md。"
        status=1
    fi

    if [[ -n $removed ]]; then
        echo "  ! 清单里有已不再修改的文件（清单过期，无害）："
        echo "$removed" | sed 's/^/      /'
    fi

    if [[ -z $added && -z $removed ]]; then
        echo "  ✓ $(echo "$expected" | grep -c .) 个上游文件，与清单一致"
    fi
done

exit $status
