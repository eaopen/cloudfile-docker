#!/bin/bash
#
# 妫€鏌ヤ笁涓?fork 淇敼鐨勪笂娓告枃浠舵槸鍚︿粛涓庣櫥璁版竻鍗曚竴鑷淬€?
#
# 杩欐槸 CloudFile 鍞竴鐪熸鐨?fork 缁存姢鎴愭湰鎸囨爣锛氭柊澧炴枃浠跺嚑涔庝笉浜х敓鍚屾鍐茬獊锛?
# 淇敼涓婃父鏂囦欢鍒欐瘡娆¤窡闅忎笂娓搁兘瑕佸啀浠樹竴娆°€傛竻鍗曚竴鏃︽倓鎮勫彉闀匡紝鍚屾鐨勫伐浣滈噺灏?
# 浼氫笉鐭ヤ笉瑙変笂鍗囷紝鑰屼笖娌′汉浼氭敞鎰忓埌鈥斺€旀墍浠ョ敤鑴氭湰鍗′綇锛岃€屼笉鏄潬鑷銆?
#
#   ./tools/check-upstream-patches.sh              # 妫€鏌ュ叏閮ㄤ笁涓粨搴?
#   ./tools/check-upstream-patches.sh cloudfile-hub
#   ./tools/check-upstream-patches.sh --worktree   # 棰濆妫€鏌ユ湭鎻愪氦淇敼
#   ./tools/check-upstream-patches.sh --update     # 鎶婂綋鍓嶇姸鎬佸啓鍥炴竻鍗?
#
# 闇€瑕佷笁涓粨搴撳苟鎺?checkout锛屼笖鍚勮嚜閰嶅ソ upstream remote锛?
#   git remote add upstream https://github.com/haiwen/<repo>.git
#
# 閫€鍑虹爜锛? = 涓€鑷达紱1 = 娓呭崟鍙橀暱锛堟嫆缁濓級锛? = 鐜闂銆?

set -u

here=$(cd "$(dirname "$0")" && pwd)
docker_repo=$(cd "$here/.." && pwd)
workspace=$(dirname "$docker_repo")
lists=$docker_repo/docs/upstream-patches

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

status=0

# 瑙ｆ瀽姣旇緝鍩虹嚎锛屾寜鍙潬鎬ф帓搴忥細
#
#   1. $CF_UPSTREAM_BASE      鈥斺€?鏄惧紡鎸囧畾
#   2. upstream/master        鈥斺€?鏈湴寮€鍙戠殑甯告€侊紱鐢ㄤ笁鐐?diff锛屽悎骞跺熀鐐逛細闅?
#                                sync 鑷姩鍓嶇Щ锛屼笉闇€瑕佷汉宸ョ淮鎶?
#   3. release.yaml 閲岀殑閿氱偣 SHA 鈥斺€?CI 鐢ㄣ€傚彧瑕?fetch 涓€涓?commit锛屼笉蹇呮媺鏁翠釜
#                                涓婃父鍘嗗彶锛坰eahub 寰堝ぇ锛夈€傜敤涓ょ偣 diff锛屽洜涓?
#                                娴呭厠闅嗕笅娌℃湁鍚堝苟鍩虹偣鍙畻
#
# 杈撳嚭 "<baseref> <two|three>"銆?
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

# 鍒楀嚭鐩稿鍩虹嚎琚慨鏀圭殑涓婃父鏂囦欢銆?
#
# 鍙畻鍩虹嚎閲屽凡瀛樺湪鐨勬枃浠讹細鏂板鏂囦欢涓嶅弬涓庡悎骞跺啿绐侊紝鎶婂畠浠贩杩涙潵浼氳杩欎釜鎸囨爣
# 澶卞幓鎰忎箟銆?
list_patched() {
    local repo_dir=$1 base=$2 mode=$3
    local range
    [[ $mode == three ]] && range="$base...HEAD" || range="$base HEAD"

    # shellcheck disable=SC2086
    {
        git -C "$repo_dir" diff --name-only $range
        # CI 鍙害鏉熷凡鎻愪氦宸紓锛岄伩鍏嶅墠缃瀯寤虹敓鎴愮殑 tracked 鏂囦欢閫犳垚璇姤銆?
        # 鏈湴鎻愪氦鍓嶉渶瑕佹鏌?staged/unstaged 淇敼鏃舵樉寮忎紶 --worktree銆?
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
        echo "  璺宠繃锛?repo_dir 涓嶆槸 git 浠撳簱" >&2
        status=2
        continue
    fi
    if [[ ! -f $list ]]; then
        echo "  璺宠繃锛氭竻鍗?$list 涓嶅瓨鍦? >&2
        status=2
        continue
    fi
    if ! read -r base mode < <(resolve_base "$repo_dir" "$repo"); then
        echo "  璺宠繃锛氭棤娉曠‘瀹氭瘮杈冨熀绾裤€備换閫夊叾涓€锛? >&2
        echo "    git -C $repo_dir remote add upstream https://github.com/haiwen/<repo>.git" >&2
        echo "    git -C $repo_dir fetch upstream master" >&2
        echo "  鎴?fetch release.yaml 閲岃褰曠殑閿氱偣 SHA锛屾垨璁剧疆 CF_UPSTREAM_BASE銆? >&2
        status=2
        continue
    fi

    actual=$(list_patched "$repo_dir" "$base" "$mode")

    if [[ $update -eq 1 ]]; then
        # 淇濈暀娓呭崟寮€澶寸殑娉ㄩ噴鍧楋紝鍙浛鎹㈡枃浠跺垪琛ㄣ€?
        {
            grep -E '^\s*(#|$)' "$list" | sed -e :a -e '/^\n*$/{$d;N;ba' -e '}'
            echo "$actual"
        } > "$list.tmp" && mv "$list.tmp" "$list"
        echo "  宸叉洿鏂版竻鍗曪細$(echo "$actual" | grep -c . ) 涓枃浠?
        continue
    fi

    expected=$(grep -vE '^\s*(#|$)' "$list" | sort)

    added=$(comm -23 <(echo "$actual") <(echo "$expected"))
    removed=$(comm -13 <(echo "$actual") <(echo "$expected"))

    if [[ -n $added ]]; then
        echo "  鉁?鏂板浜嗘湭鐧昏鐨勪笂娓告敼鍔細"
        echo "$added" | sed 's/^/      /'
        echo "    姣忎竴涓兘浼氬湪璺熼殢涓婃父鏃跺弽澶嶄骇鐢熷啿绐併€傚厛纭鏃犳硶鏀规垚鏂板鏂囦欢锛?
        echo "    鍐嶆洿鏂?docs/upstream-patches/$repo.txt 涓?BRANCHING.md銆?
        status=1
    fi

    if [[ -n $removed ]]; then
        echo "  ! 娓呭崟閲屾湁宸蹭笉鍐嶄慨鏀圭殑鏂囦欢锛堟竻鍗曡繃鏈燂紝鏃犲锛夛細"
        echo "$removed" | sed 's/^/      /'
    fi

    if [[ -z $added && -z $removed ]]; then
        echo "  鉁?$(echo "$expected" | grep -c .) 涓笂娓告枃浠讹紝涓庢竻鍗曚竴鑷?
    fi
done

exit $status
