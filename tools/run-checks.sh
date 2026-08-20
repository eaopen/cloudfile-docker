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

# 1. 上游改动登记 —— fork 维护成本的可观测警告，不阻断 CI
run "上游改动登记" "$docker_repo/tools/check-upstream-patches.sh"
run "上游改动警告语义" "$docker_repo/tests/tools/test-check-upstream-patches.sh"
run "容器工作流基础镜像契约" "$docker_repo/tests/tools/test-image-workflows.sh"
run "构建平台规范化" "$docker_repo/tests/tools/test-build-platform.sh"
run "构建缓存契约" "$docker_repo/tests/tools/test-build-cache-contract.sh"
run "增量发布工作流契约" "$docker_repo/tests/tools/test-production-workflow.sh"

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

    # 只跑 CloudFile 自己的测试，不跑 `go test ./...`：上游的 repomgr 测试要连
    # MySQL，在这条秒级门禁里必然失败，而一个总是红的检查等于没有检查。
    run "Go fileserver 契约测试" bash -c \
        "cd '$server/fileserver' && go test -count=1 -run 'Cf[A-Z]' ."
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

# 7. 构建脚本副本与上游的偏离没有变大
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
    upstream='$docker_repo/build/seafile_14.0/seafile-build.py'
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
run "配置生成" python3 "$docker_repo/tools/test-bootstrap-settings.py"

# 9. release.yaml 可解析且关键键齐全
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
