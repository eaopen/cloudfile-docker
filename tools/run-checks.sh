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

# 2. Hub 侧 ACL 求解器（与 C 端共用同一份用例集）
if [[ -d $hub ]]; then
    run "Hub ACL 求解器 (Python)" bash -c \
        "cd '$hub' && python3 -m pytest cloudfile_ext/ -q"
else
    skip "Hub ACL 求解器" "找不到 $hub"
fi

# 3. Server 侧 ACL 求解器（只需要 glib，不需要完整构建）
if [[ ! -d $server ]]; then
    skip "Server ACL 求解器" "找不到 $server"
elif ! command -v cc >/dev/null; then
    skip "Server ACL 求解器" "没有 C 编译器"
elif ! pkg-config --exists glib-2.0 2>/dev/null; then
    skip "Server ACL 求解器" "没有 glib-2.0（apt install libglib2.0-dev）"
else
    run "Server ACL 求解器 (C)" "$server/tests/cf-acl/run.sh"
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
    for f in '$docker_repo/build/cloudfile_14.0/read-manifest.py'; do
        python3 -m py_compile \"\$f\"
    done
    python3 -c \"import json; json.load(open('$docker_repo/docs/acl-cases.json'))\"
"

# 7. release.yaml 可解析且关键键齐全
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
