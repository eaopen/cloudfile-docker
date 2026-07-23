#!/bin/bash
#
# CloudFile 快速检查。不需要构建镜像，几分钟内出结果。
#
# 三个仓库的 CI 都调用这一份，避免检查逻辑复制三遍后各自漂移。本地也可以直接跑：
#
#   ./tools/run-checks.sh
#
# 需要三仓并排 checkout。缺少某个可选工具（go / cc / docker）时跳过对应检查
# 并说明原因，而不是假装通过——静默跳过的检查比没有检查更危险。

set -uo pipefail

here=$(cd "$(dirname "$0")" && pwd)
docker_repo=$(cd "$here/.." && pwd)
workspace=$(dirname "$docker_repo")

hub=$workspace/cloudfile-hub
server=$workspace/cloudfile-server

failed=()
skipped=()

run() {
    local name=$1; shift
    echo
    echo "──────── $name ────────"
    if "$@"; then
        echo "✓ $name"
    else
        echo "✗ $name"
        failed+=("$name")
    fi
}

skip() {
    echo
    echo "──────── $1 ────────"
    echo "⊘ 跳过：$2"
    skipped+=("$1（$2）")
}

# 1. 上游改动登记 —— fork 维护成本的硬约束
run "上游改动登记" "$docker_repo/tools/check-upstream-patches.sh"

# 2. Hub 侧扩展测试（能力分支上还包括与 C 端共用用例集的求解器测试）
if [[ -d $hub ]]; then
    # pytest 收集不到用例时退出码是 5。基线上确实一个能力测试都没有，那是
    # 正常状态，不该判为失败——但真正的失败（退出码 1）仍然要红。
    run "Hub 扩展测试 (Python)" bash -c \
        "cd '$hub' && python3 -m pytest cloudfile_ext/ -q; rc=\$?; [ \$rc -eq 0 ] || [ \$rc -eq 5 ]"
else
    skip "Hub 扩展测试" "找不到 $hub"
fi

# 3. Server 侧能力测试（只需要 glib，不需要完整构建）
#
# 用发现而不是写死：基线上一个能力都没有，能力分支上则各有各的
# tests/cf-<能力>/run.sh。写死某个能力的路径会让基线永远报"缺失"。
server_cap_tests=()
if [[ -d $server/tests ]]; then
    while IFS= read -r t; do server_cap_tests+=("$t"); done \
        < <(find "$server/tests" -mindepth 2 -maxdepth 2 -name run.sh 2>/dev/null | sort)
fi

if [[ ! -d $server ]]; then
    skip "Server 能力测试" "找不到 $server"
elif [[ ${#server_cap_tests[@]} -eq 0 ]]; then
    skip "Server 能力测试" "基线无能力实现，无测试可跑"
elif ! command -v cc >/dev/null; then
    skip "Server 能力测试" "没有 C 编译器"
elif ! pkg-config --exists glib-2.0 2>/dev/null; then
    skip "Server 能力测试" "没有 glib-2.0（apt install libglib2.0-dev）"
else
    for t in "${server_cap_tests[@]}"; do
        run "Server 能力测试 $(basename "$(dirname "$t")")" "$t"
    done
fi

# 4. Go fileserver
if [[ ! -d $server/fileserver ]]; then
    skip "Go fileserver" "找不到 $server/fileserver"
elif ! command -v go >/dev/null; then
    skip "Go fileserver" "没有安装 go"
else
    run "Go fileserver" bash -c \
        "cd '$server/fileserver' && go build ./... && go vet ./..."
fi

# 5. Compose 配置与 profile
if ! command -v docker >/dev/null || ! docker compose version >/dev/null 2>&1; then
    skip "Compose 配置" "没有 docker compose"
else
    run "Compose 配置" bash -c "
        cd '$docker_repo/deploy/compose'
        trap 'rm -f .env' EXIT
        cp .env.example .env
        docker compose config --quiet
        for p in search office worker full; do
            docker compose --profile \$p config --services >/dev/null
        done
    "
fi

# 6. Shell 与 Python 语法
#
# 只扫 CloudFile 自己的文件。build/seafile_*/ 是上游原样保留的，它们的
# SyntaxWarning 不归我们管，混进来只会淹没真正的问题。
run "脚本语法" bash -c "
    set -e
    for f in \$(find '$docker_repo/tools' '$docker_repo/build/cloudfile_14.0' \
                     '$docker_repo/image/cloudfile_14.0' -name '*.sh'); do
        bash -n \"\$f\"
    done
    for f in '$docker_repo/build/cloudfile_14.0/read-manifest.py' \
             \$(find '$docker_repo/tests' -name '*.py' 2>/dev/null); do
        python3 -m py_compile \"\$f\"
    done
    for f in \$(find '$docker_repo/docs' -name '*.json'); do
        python3 -c \"import json,sys; json.load(open(sys.argv[1]))\" \"\$f\"
    done
"

# 7. 构建脚本副本与上游的偏离没有变大
#
# build/cloudfile_14.0/cloudfile-build.py 是上游 seafile-build.py 的副本，只改
# 了一处（放宽版本号校验以接受 14.0.0-cf.0）。上游更新那个文件时，我们的副本
# 会**静默变旧**——和上游改动登记一样的问题，所以同样用脚本卡住。
run "构建脚本副本偏离" bash -c "
    upstream='$docker_repo/build/seafile_14.0/seafile-build.py'
    ours='$docker_repo/build/cloudfile_14.0/cloudfile-build.py'
    hunks=\$(diff -u \"\$upstream\" \"\$ours\" | grep -c '^@@' || true)
    if [ \"\$hunks\" != '1' ]; then
        echo \"副本与上游相差 \$hunks 处，预期 1 处（版本号校验）。\"
        echo \"上游可能更新了 seafile-build.py：先 diff 确认，再决定是同步副本\"
        echo \"还是接受新的偏离并更新这个检查。\"
        diff -u \"\$upstream\" \"\$ours\" | head -40
        exit 1
    fi
    echo '仅 1 处预期偏离'
"

# 8. release.yaml 可解析且关键键齐全
run "发布清单" bash -c "
    set -e
    for k in product image forks.cloudfile_server.ref forks.cloudfile_hub.ref \
             upstream.seahub upstream.seafile_server database_schema; do
        python3 '$docker_repo/build/cloudfile_14.0/read-manifest.py' \
            '$docker_repo/release.yaml' \"\$k\" >/dev/null
    done
"

echo
echo "════════ 结果 ════════"
for s in "${skipped[@]:-}"; do [[ -n $s ]] && echo "⊘ $s"; done
if [[ ${#failed[@]} -gt 0 ]]; then
    for f in "${failed[@]}"; do echo "✗ $f"; done
    echo
    echo "${#failed[@]} 项失败"
    exit 1
fi
echo "全部通过"
