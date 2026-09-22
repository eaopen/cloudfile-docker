#!/bin/bash
#
# 断言 CloudFile 的基线覆盖了上游 CE 14 正式发布的源码。
#
# CloudFile 跟的是 upstream/master（同步频繁、冲突小），但产品自称 CE 14，就必须
# 至少包含上游 CE 14 正式发布的那次源码改动。release.yaml 的 ce_anchor 记录该发布
# 的源码提交，这里逐个断言它是被验证 ref 的祖先。
#
# 为什么记"源码提交"而不是 tag 指向的提交：seahub 的 v14.0.8-server 打在
# "[dist][CI SKIP] ... CI build" 的产物提交上，那个提交不是 master 的祖先，
# 直接断言它会永远为假。
#
# 本地没有该提交时按 tag 取一次（tag 的父提交会一并带入），先试 upstream 再退回
# origin——CI 用 actions/checkout 检出，只配 origin，没有 upstream。
#
# 断言的是"正在验证的那个 ref"：在 dev 上跑就是发布前的门禁，在 sync/* 上跑就是
# 候选分支的门禁。发布切自 dev，所以真正决定发布的是 dev 上那次（CI 的 dev 任务
# HEAD 就是 dev）。要显式指定用 CF_CE_ANCHOR_REF。
#
#   ./tools/check-ce-anchor.sh
#   CF_CE_ANCHOR_REF=dev ./tools/check-ce-anchor.sh
#   CF_CE_ANCHOR_WORKSPACE=... ./tools/check-ce-anchor.sh
#
# 退出码：0 = 全部锚点验证过且满足；1 = 至少一项验证过且不满足；2 = 没能验证
# （缺仓库/缺提交）。**2 必须被调用方报成"跳过"而不是"通过"**——否则取不到提交
# 时会在不变式真的被违反的场合静默放行，那比没有这条检查更糟。run-checks.sh 已按
# 这个约定分派。

set -uo pipefail

here=$(cd "$(dirname "$0")" && pwd)
docker_repo=$(cd "$here/.." && pwd)
workspace=${CF_CE_ANCHOR_WORKSPACE:-$(dirname "$docker_repo")}
ref=${CF_CE_ANCHOR_REF:-HEAD}
reader=$docker_repo/build/cloudfile_14.0/read-manifest.py
manifest=$docker_repo/release.yaml

manifest_get() {
    python3 "$reader" "$manifest" "$1" 2>/dev/null
}

version=$(manifest_get ce_anchor.version)
if [[ -z ${version} ]]; then
    echo "release.yaml 里没有 ce_anchor.version" >&2
    exit 1
fi

checked=0
failed=0
skipped=0

check_one() {
    local repo=$1 key=$2
    local dir=$workspace/$repo
    local sha

    echo "=== ${repo} ==="
    sha=$(manifest_get "ce_anchor.${key}")

    if [[ -z ${sha} ]]; then
        echo "  ⊘ 跳过：release.yaml 未记录 ce_anchor.${key}"
        skipped=$((skipped + 1))
        return 0
    fi
    if [[ ! -d ${dir}/.git ]]; then
        echo "  ⊘ 跳过：${dir} 不是 git 仓库"
        skipped=$((skipped + 1))
        return 0
    fi
    if ! git -C "$dir" rev-parse --verify -q "$ref" >/dev/null; then
        echo "  ⊘ 跳过：${repo} 里没有 ${ref}"
        skipped=$((skipped + 1))
        return 0
    fi

    # 本地没有就先按 tag 取一次。CI 里没有 upstream remote（checkout 只配
    # origin），所以再退回 origin 试一次——取不到时不能当通过，见文件末尾的
    # 退出码约定。
    if ! git -C "$dir" cat-file -e "${sha}^{commit}" 2>/dev/null; then
        git -C "$dir" fetch --quiet upstream \
            "refs/tags/${version}:refs/tags/${version}" >/dev/null 2>&1
    fi
    if ! git -C "$dir" cat-file -e "${sha}^{commit}" 2>/dev/null; then
        git -C "$dir" fetch --quiet origin \
            "refs/tags/${version}:refs/tags/${version}" >/dev/null 2>&1
    fi
    if ! git -C "$dir" cat-file -e "${sha}^{commit}" 2>/dev/null; then
        if git -C "$dir" merge-base --is-ancestor "origin/$ref" "$ref" 2>/dev/null; then
            echo "  ⊘ 跳过：本地没有 ${sha}，且取不到 ${version}（离线或未配 upstream remote）"
        else
            # ref 落后于 origin/ref，且取不到锚点提交——很可能确实落后，但这里
            # 无法证明，仍然只跳过，不伪造失败。
            echo "  ⊘ 跳过：本地没有 ${sha}，且取不到 ${version}；${ref} 落后于 origin/${ref}，请联网复跑"
        fi
        skipped=$((skipped + 1))
        return 0
    fi

    checked=$((checked + 1))
    if git -C "$dir" merge-base --is-ancestor "${sha}^{commit}" "$ref" 2>/dev/null; then
        echo "  ✓ ${version} 的源码提交已在 ${ref}（${sha:0:8}）"
    else
        echo "  ✗ ${ref} 落后于 ${version}：${sha:0:8} 不是 ${ref} 的祖先"
        echo "    先按 BRANCHING.md「跟随上游」同步，再发布。"
        # 记成 tag 指向的 [dist] 产物提交是最容易犯的错：那种提交永远不是
        # master 的祖先，判据会一直失败。看到这个签名就直接提示。
        if git -C "$dir" log -1 --format=%s "${sha}^{commit}" 2>/dev/null | grep -q '\[dist\]'; then
            echo "    注意：${sha:0:8} 看起来是 \"[dist] ... CI build\" 产物提交，"
            echo "    ce_anchor 要记它基于的源码提交（见 release.yaml 里的说明）。"
        fi
        failed=$((failed + 1))
    fi
    return 0
}

check_one cloudfile-server seafile_server
check_one cloudfile-hub seahub

echo
# 退出码约定（run-checks.sh 依赖它把"跳过"和"通过"分开）：
#   0 = 全部锚点都验证过且满足
#   1 = 至少一项验证过且**不满足**（1 优先于 2）
#   2 = 没能验证（缺仓库/缺提交）——必须显式报成跳过，不能当通过
if [[ ${failed} -gt 0 ]]; then
    echo "${failed} 项失败：基线未覆盖 ${version}"
    exit 1
fi
if [[ ${skipped} -gt 0 || ${checked} -eq 0 ]]; then
    echo "⊘ 未完成：${checked} 项验证通过，${skipped} 项无法验证（判据这次没完全生效）"
    exit 2
fi
echo "CE 14 兼容锚点满足（${version}）"
