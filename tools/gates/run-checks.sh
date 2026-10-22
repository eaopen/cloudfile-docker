#!/bin/bash
#
# CloudFile 快速检查。不需要构建镜像，几分钟内出结果。
#
# 三个仓库的 CI 都调用这一份，避免检查逻辑复制三遍后各自漂移。本地也可以直接跑：
#
#   ./tools/gates/run-checks.sh
#
# 需要三仓并排 checkout。缺少某个可选工具（go / cc / docker）时跳过对应检查
# 并说明原因，而不是假装通过——静默跳过的检查比没有检查更危险。

set -uo pipefail

here=$(cd "$(dirname "$0")" && pwd)
docker_repo=$(cd "$here/../.." && pwd)
workspace=$(dirname "$docker_repo")

hub=$workspace/cloudfile-hub
server=$workspace/cloudfile-server

# Keep local and CI checks on the same isolated dependency set. Never install
# into the developer's system Python or silently skip HTTP/auth tests.
if ! python3 -c 'import pytest, django, requests, jwt, cryptography, pymysql, requests_oauthlib, redis, rest_framework, yaml' >/dev/null 2>&1; then
    if [[ "${CF_CHECK_ENV_READY:-0}" != 1 ]] && command -v uv >/dev/null 2>&1; then
        exec env CF_CHECK_ENV_READY=1 uv run --no-project \
            --with-requirements "$here/check-requirements.txt" bash "$0" "$@"
    fi
    echo "Check dependencies unavailable; run with uv or install tools/gates/check-requirements.txt in a virtual environment." >&2
    exit 1
fi

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

# 1. 上游改动登记 —— fork 维护成本的可观测警告，不阻断 CI
run "上游改动登记" "$docker_repo/tools/gates/check-upstream-patches.sh"
run "上游改动警告语义" "$docker_repo/tests/tools/test-check-upstream-patches.sh"

# CE14 兼容锚点有三种结果，所以不能走 run()。无法验证时必须显式报成跳过：把它
# 当通过，正好会在"dev 落后于 CE 正式发布"这个不变式真的被违反、而本地又取不到
# 锚点提交的场合静默放行（CI 用 actions/checkout 检出，只配 origin，没有
# upstream remote）。这里不复用 skip()，因为它会再打一次分隔标题。
echo
echo "──────── CE14 兼容锚点 ────────"
"$docker_repo/tools/gates/check-ce-anchor.sh"
case $? in
    0)
        echo "✓ CE14 兼容锚点"
        ;;
    2)
        echo "⊘ 跳过：CE14 兼容锚点（无法取得锚点提交，判据未生效）"
        skipped+=("CE14 兼容锚点（无法取得锚点提交）")
        ;;
    *)
        echo "✗ CE14 兼容锚点"
        failed+=("CE14 兼容锚点")
        ;;
esac
run "容器工作流基础镜像契约" "$docker_repo/tests/tools/test-image-workflows.sh"
run "构建平台规范化" "$docker_repo/tests/tools/test-build-platform.sh"
run "构建缓存契约" "$docker_repo/tests/tools/test-build-cache-contract.sh"
run "增量发布工作流契约" "$docker_repo/tests/tools/test-production-workflow.sh"
run "前端产物完整性契约" "$docker_repo/tests/tools/test-production-artifact.sh"
run "最终发布包完整性契约" "$docker_repo/tests/tools/test-release-artifact.sh"
# Validate the exact dependency patch payload, not an unrelated local checkout.
# 这条不能并进下面的发现：该文件是 pytest 风格（pytest.mark.parametrize），
# unittest 的发现收不到它。
run "自动本地存储 Python 策略" python3 -m pytest "$docker_repo/tests/test_automatic_local_storage.py" -q
# 根级契约测试用一次发现跑完，而不是逐个写死路径。写死会让新加的
# tests/test_*.py 静默地永远不跑——2026-10-22 之前有 11 个测试从未进入任何
# 门禁，就是这么来的。tests/ 没有 __init__.py，所以发现只收根级 test_*.py，
# 不会递归进 e2e/、tools/、v2/：那些要真实栈，仍由 verify-local.sh 编排。
run "根级单元与契约测试" python3 -m unittest discover -s "$docker_repo/tests" -p 'test_*.py' -q
# 上面那次发现已经覆盖这条；这里仍按文件名显式跑一次，是因为 dev.yml 也按
# 文件名直跑同一份 ACL 文档合同，保留显式名字让 CI 与本地门禁的入口对得上。
run "当前 V2 ACL 无托管库文档合同" python3 "$docker_repo/tests/test_v2_authorization_contract.py"
# 九份 tests/cases/review-*-cases.json 的唯一 schema 校验器。它一直存在，
# 但此前没有任何入口调用，等于没有门禁。
run "review 用例集 schema" python3 "$docker_repo/tools/gates/validate-review-cases.py"
# Cheap current V2 4+1 table inventory only. Old 001-042 data conversion,
# checksum ledgers and build-time compatibility checks are not product CI.
agent=$workspace/cloudfile-local-agent2
if [[ -d $agent ]]; then
    run "V2 4+1 运行表合同（含 Agent2）" python3 "$docker_repo/tools/gates/check-sql-contracts.py" --server "$server" --hub "$hub" --agent "$agent"
else
    run "V2 4+1 运行表合同" python3 "$docker_repo/tools/gates/check-sql-contracts.py" --server "$server" --hub "$hub"
    skip "Agent2 当前 SQL/接口检查" "未检出 $agent"
fi
run "V05-01 只读容量诊断测试" python3 -m unittest discover -s "$hub/tests" -p test_cf_capacity_report.py -q


# 2. Hub 侧扩展测试（能力分支上还包括与 C 端共用用例集的求解器测试）
if [[ -d $hub ]]; then
    # The native HTTP unit tests use explicit RPC/ORM doubles and real DRF;
    # upstream runtime integration remains in the dedicated Seahub CI job.
    run "Hub 扩展测试 (Python)" python3 "$docker_repo/tools/gates/check-hub-contracts.py" cloudfile_ext/ --ignore=cloudfile_ext/v2/tests
    run "Hub 当前 V2 HTTP 契约" python3 "$docker_repo/tools/gates/check-hub-contracts.py" --v2
    # Current contracts use isolated SQL fixtures and minimal Django settings,
    # not Seahub's native runtime or its upstream integration test settings.
    run "Hub 当前契约与 Agent 路由" bash -c \
        "python3 '$docker_repo/tools/gates/check-hub-contracts.py'"
else
    skip "Hub 扩展测试" "找不到 $hub"
fi

# 3. Server 侧能力测试（不需要完整构建；目录分页另需 valac / jansson）
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
        # Some tracked shell fixtures lack the executable bit. Invoke their
        # declared Bash runtime so CI still executes and checks the test body.
        run "Server 能力测试 $(basename "$(dirname "$t")")" bash "$t"
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

    # 只跑 CloudFile 自己的测试，不跑 `go test ./...`：上游的 repomgr 测试要连
    # MySQL，在这条秒级门禁里必然失败，而一个总是红的检查等于没有检查。
    run "Go fileserver 契约测试" bash -c \
        "cd '$server/fileserver' && go test -count=1 -run 'Cf[A-Z]|CloudFile(Browser|Read)' ."
    # Object routing lives in a subpackage and is not covered by tests of '.'.
    run "Go 对象存储路由" bash -c \
        "cd '$server/fileserver' && go test -count=1 ./objstore"
fi

# 5. Compose 配置与 profile
if ! command -v docker >/dev/null || ! docker compose version >/dev/null 2>&1; then
    skip "Compose 配置" "没有 docker compose"
else
    run "Compose 配置" bash -c "
        cd '$docker_repo/deploy/compose'
        cf_compose_config=\$(mktemp)
        trap 'rm -f \"\$cf_compose_config\"' EXIT
        # 直接用 --env-file 读 .env.example，绝不 cp 到 .env 再删——那样会覆盖并
        # 销毁开发者自己的 deploy/compose/.env（gitignored，无法从 git 恢复）。
        docker compose --env-file .env.example config --quiet
        # 空标记是 FileOp 门禁的观察模式，不能被 Compose 的默认值吞掉；
        # SeaSearch 的短间隔则必须真的进入容器，CI 才不会等上游的 10 分钟默认值。
        CF_FILEOP_TEST_REFUSE_TOKEN='' CF_SEASEARCH_INTERVAL=10s \\
            docker compose --env-file .env.example config > \"\$cf_compose_config\"
        grep -Fq 'CF_FILEOP_TEST_REFUSE_TOKEN: \"\"' \"\$cf_compose_config\"
        grep -Fq 'CF_SEASEARCH_INTERVAL: 10s' \"\$cf_compose_config\"
        for p in search office worker full; do
            docker compose --env-file .env.example --profile \$p config --services >/dev/null
        done
    "
fi

# 6. Shell 与 Python 语法
#
# 只扫 CloudFile 自己的文件。build/seafile_*/ 是上游原样保留的，它们的
# SyntaxWarning 不归我们管，混进来只会淹没真正的问题。
run "脚本语法" bash -c "
    set -e
    # -prune 掉 src/ 与构建产物：那里是 clone 下来的上游源码和发行包，不归
    # 我们管，而且上游的 bash-4 语法（&>>）在 macOS 自带的 bash 3.2 上会误报。
    #
    # 'seafile-server' 必须单列：clone 出来的工作树就叫这个名字，没有后缀，
    # 'seafile-server-*' 匹配不到。这个漏洞一直藏着，因为那个目录只在**构建
    # 跑过之后**才存在——干净的树上检查是绿的，跑过一次构建再跑就红。
    for f in \$(find '$docker_repo/tools' '$docker_repo/build/cloudfile_14.0' \
                     '$docker_repo/image/cloudfile_14.0' \
                     \\( -name src -o -name seafile-server -o -name 'seafile-server-*' \
                        -o -name node_modules \\) -prune \
                     -o -name '*.sh' -print); do
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

# 7. 构建脚本副本与清单锁定的真实上游提交相比，偏离没有变大
#
# build/cloudfile_14.0/cloudfile-build.py 是上游 seafile-build.py 的副本，预期
# 改了六处：放宽版本号校验以接受 14.0.0-cf.0；在 copy_scripts_and_libs() 的
# must_copy 循环里加一行，把离线 S3 迁移工具 seaf-storage-migrate.sh（新文件，
# 随 seaf-fsck.sh/seaf-gc.sh 一起来自 Seahub scripts/）随发行包一起复制出去
# ——不加这行，构建产物里就没有这个工具；给 Libevhtp 的 `make` 加 `-j`，让它
# 与 libsearpc/seafile 一样并行编译；新增 --compile-only / --package-only 两个
# CLI 开关并把 main() 的编译与打包拆开；package-only 在独立 runner 上也会
# 写入版本。默认 all 路径仍保持原有行为。
# 上游更新那个文件时，我们的副本会**静默变旧**——和上游改动登记一样的问题，
# 所以同样用脚本卡住。
run "构建脚本副本偏离" bash -c "
    set -e
    upstream_ref=\$(python3 '$docker_repo/build/cloudfile_14.0/read-manifest.py' \
        '$docker_repo/release.yaml' upstream.seafile_docker)
    upstream=\$(mktemp)
    trap 'rm -f \"\$upstream\"' EXIT
    # The checked-out upstream recipe has local provenance/ACL packaging patches.
    # Compare to immutable upstream bytes, not that modified recipe.
    git -C '$docker_repo' show \"\$upstream_ref:build/seafile_14.0/seafile-build.py\" > \"\$upstream\"
    ours='$docker_repo/build/cloudfile_14.0/cloudfile-build.py'
    hunks=\$(diff -u \"\$upstream\" \"\$ours\" | grep -c '^@@' || true)
    if [ \"\$hunks\" != '6' ]; then
        echo \"副本与上游相差 \$hunks 处，预期 6 处（版本号校验 + 发布脚本复制 + libevhtp make -j + compile/package 拆分 + 独立打包版本）。\"
        echo \"上游可能更新了 seafile-build.py：先 diff 确认，再决定是同步副本\"
        echo \"还是接受新的偏离并更新这个检查。\"
        diff -u \"\$upstream\" \"\$ours\" | head -40
        exit 1
    fi
    echo '仅 6 处预期偏离'
"

# 8. bootstrap 生成的 seahub_settings.py 片段真的能加载
#
# preflight 那条是静态的，只认 `FOO['bar'] =` 这一种形状。这条把生成函数抠出来
# 实际执行，覆盖引号、字面量、claim 冲突这些静态检查看不出的写法——它们的后果
# 与当年那次一样：seahub 吞掉异常，**整个文件的 CloudFile 配置一起丢**，而服务
# 看起来是好的。
run "配置生成" python3 "$docker_repo/tools/gates/test-bootstrap-settings.py"
run "v0.4 预览与正式库入口配置" python3 "$docker_repo/tools/gates/test-v04-preview-config.py"

# 9. release.yaml 可解析且关键键齐全
run "发布清单" bash -c "
    set -e
    for k in product image forks.cloudfile_server.ref forks.cloudfile_hub.ref \
             upstream.seahub upstream.seafile_server database_schema \
             ce_anchor.version ce_anchor.seafile_server ce_anchor.seahub; do
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
