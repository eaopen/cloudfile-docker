#!/bin/bash
#
# 在本机跑一遍与 CI 完全相同的基线门禁。
#
# 存在的理由很直接：CI 一轮 20 分钟，而前六次失败全是集成边界上的问题——
# PATH、依赖链、系统库、版本号格式、TLS——没有一个是 `bash -n` 或单元测试能
# 发现的。一次次"改一行、推一次、等二十分钟"太慢了。这个脚本把同样的步骤
# 搬到本地，失败在几分钟内就能看见。
#
#   ./tools/verify-local.sh              # 全流程
#   ./tools/verify-local.sh preflight    # 只做静态一致性检查（秒级）
#   ./tools/verify-local.sh build        # 只构建发行包
#   ./tools/verify-local.sh e2e          # 假设镜像已在，只跑起栈 + E2E
#   ./tools/verify-local.sh clean        # 清掉本地栈与数据
#
# 与 CI 的差异（有意为之，且只有这些）：
#   - 构建在 ubuntu 容器里跑（CI 的 runner 本身就是 ubuntu）
#   - 端口默认 80/443（与 CI 一致，绝对 URL 才对得上）；被占用时可用
#     CF_LOCAL_HTTP_PORT / CF_LOCAL_HTTPS_PORT 覆盖
#   - Compose 跑在临时目录里，不碰 deploy/compose/ 下你自己的 .env 和 data/
#   - 架构跟随本机（Apple Silicon 上是 arm64）。上游 arm 与 x86 的 Dockerfile
#     逐字节相同，所以这不影响结论；要验 amd64 就设 CF_PLATFORM=linux/amd64。

set -uo pipefail

here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$here/.." && pwd)
workspace=$(dirname "$repo")

VERSION=${CF_VERSION:-14.0.0-cf.0-local}
IMAGE=cloudfile/cloudfile:$VERSION
PROJECT=cloudfile-local
# 默认用 80/443，和 CI 保持一致。
#
# 改成 8080/8443 看似更"礼貌"，但会让验证失真：seahub 生成的是绝对 URL
# （上传/下载链接指向 https://<hostname>/seafhttp/...，隐含默认端口），
# 客户端连过去必然 Connection refused——报错落在"上传文件"上，离真因很远。
# 端口被占用时用 CF_LOCAL_HTTP_PORT/CF_LOCAL_HTTPS_PORT 覆盖，但要知道
# 上传下载那几项会因此失败。
HTTP_PORT=${CF_LOCAL_HTTP_PORT:-80}
HTTPS_PORT=${CF_LOCAL_HTTPS_PORT:-443}
ADMIN_EMAIL=admin@cloudfile.test
ADMIN_PASSWORD=CloudFile-Local-4417
STAGE_DIR=${CF_LOCAL_STAGE:-$repo/.local-verify}

say()  { printf '\n\033[1m══ %s\033[0m\n' "$*"; }
fail() { printf '\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }
ok()   { printf '\033[32m✓ %s\033[0m\n' "$*"; }

need_docker() {
    docker info >/dev/null 2>&1 || fail "Docker 不可用（启动 OrbStack / Docker Desktop / colima）"
}

# ── preflight：静态一致性检查 ────────────────────────────────────────────
#
# 专抓"CI 里才会炸"的那类不一致：workflow 引用了不存在的脚本、E2E 的协议和
# Compose 的 TLS 设置对不上、开关清单三处不同步。都是秒级检查。
preflight() {
    say "preflight：静态一致性"
    local bad=0

    "$here/run-checks.sh" >/dev/null 2>&1 \
        && ok "run-checks.sh 全部通过" \
        || { printf '\033[31m✗ run-checks.sh 失败，单独跑一次看详情\033[0m\n'; bad=1; }

    python3 "$here/preflight-checks.py" "$repo" "$workspace" || bad=1

    [[ $bad -eq 0 ]] || fail "preflight 未通过——先修掉再花二十分钟构建"
    say "preflight 通过"
}

# ── 构建发行包 ──────────────────────────────────────────────────────────
build_dist() {
    need_docker
    say "构建发行包 $VERSION（容器内，宿主机不受影响）"

    # 默认构建**并排 checkout 的本地仓库**，而不是去 GitHub 拉。
    #
    # 本地门禁的意义就在于验证手头这份代码，包括还没 push 的分支；去拉远端
    # 等于验证了别的东西。设 CF_SERVER_URL/CF_HUB_URL 可以覆盖回远端。
    #
    # 只有已提交的内容会进构建（见 build-in-docker.sh），所以跑之前先 commit。
    for pair in "CF_SERVER_URL:cloudfile-server" "CF_HUB_URL:cloudfile-hub"; do
        var=${pair%%:*}; dir=${pair#*:}
        if [[ -z ${!var:-} && -d $workspace/$dir/.git ]]; then
            export "$var=$workspace/$dir"
            ref_var=${var%_URL}_REF
            if [[ -z ${!ref_var:-} ]]; then
                export "$ref_var=$(git -C "$workspace/$dir" rev-parse --abbrev-ref HEAD)"
            fi
            echo "  $dir → ${!ref_var}"
        fi
    done

    "$repo/build/cloudfile_14.0/build-in-docker.sh" "$VERSION" \
        || fail "发行包构建失败"
    ok "发行包完成"
    cat "$repo/build/cloudfile_14.0/seafile-server-$VERSION/cloudfile-build-info.txt" 2>/dev/null || true
}

build_image() {
    need_docker
    say "构建镜像 $IMAGE"
    "$repo/image/cloudfile_14.0/docker-build.sh" "$VERSION" || fail "镜像构建失败"
    ok "镜像完成"
}

# ── 起栈 + E2E ──────────────────────────────────────────────────────────
stage_compose() {
    rm -rf "$STAGE_DIR"
    mkdir -p "$STAGE_DIR"
    cp "$repo/deploy/compose/docker-compose.yml" "$repo/deploy/compose/Caddyfile" "$STAGE_DIR/"
    {
        sed -e "s|^SEAFILE_SERVER_HOSTNAME=.*|SEAFILE_SERVER_HOSTNAME=127.0.0.1|" \
            -e "s|^SEAFILE_SERVER_PROTOCOL=.*|SEAFILE_SERVER_PROTOCOL=https|" \
            -e "s|^INIT_SEAFILE_ADMIN_EMAIL=.*|INIT_SEAFILE_ADMIN_EMAIL=$ADMIN_EMAIL|" \
            -e "s|^INIT_SEAFILE_ADMIN_PASSWORD=.*|INIT_SEAFILE_ADMIN_PASSWORD=$ADMIN_PASSWORD|" \
            -e "s|^CADDY_TLS=.*|CADDY_TLS=internal|" \
            -e "s|^HTTP_PORT=.*|HTTP_PORT=$HTTP_PORT|" \
            -e "s|^HTTPS_PORT=.*|HTTPS_PORT=$HTTPS_PORT|" \
            "$repo/deploy/compose/.env.example"
        echo "CLOUDFILE_IMAGE=$IMAGE"
    } > "$STAGE_DIR/.env"
}

compose() { docker compose -p "$PROJECT" --project-directory "$STAGE_DIR" "$@"; }

up() {
    need_docker
    docker image inspect "$IMAGE" >/dev/null 2>&1 \
        || fail "本地没有镜像 $IMAGE，先跑 build"
    say "启动（开关全关）"
    stage_compose
    compose up -d || fail "compose 启动失败"
    compose ps
}

e2e() {
    # 443 时不带端口，让 URL 与 seahub 生成的绝对链接完全一致
    local base="https://127.0.0.1"
    [[ $HTTPS_PORT != 443 ]] && base="https://127.0.0.1:$HTTPS_PORT"
    say "原生 CE 冒烟 @ $base"
    python3 "$repo/tests/e2e/smoke.py" --url "$base" --insecure \
        --admin "$ADMIN_EMAIL" --admin-password "$ADMIN_PASSWORD" || return 1

    say "扩展点已装好，但没有能力启用"
    python3 "$repo/tests/e2e/baseline.py" --url "$base" --insecure \
        --admin "$ADMIN_EMAIL" --admin-password "$ADMIN_PASSWORD" || return 1
}

dump_logs() {
    say "容器日志（失败诊断）"
    compose ps -a || true
    compose logs --tail 200 cloudfile || true
    compose exec -T cloudfile tail -n 120 /opt/seafile/logs/seahub.log 2>/dev/null || true
    compose exec -T cloudfile tail -n 120 /opt/seafile/logs/seafile.log 2>/dev/null || true
}

# 构建树被中断过、或换过架构之后必须清。
#
# 踩过一次：amd64 构建被 kill 后残留的 src/ 被下一次 arm64 构建复用，vala 生成的
# repo.c（上游是**提交进仓库**的）状态错乱，编译报一堆 "redefinition of ..."。
# 症状离原因很远，所以宁可提供一条明确的命令。
distclean() {
    say "清理构建树"
    rm -rf "$repo/build/cloudfile_14.0/src" \
           "$repo/build/cloudfile_14.0/seafile-server" \
           "$repo"/build/cloudfile_14.0/seafile-server-*
    ok "构建树已清空（下次构建会重新 clone，慢但干净）"
}

clean() {
    say "清理本地栈"
    [[ -d $STAGE_DIR ]] && compose down -v 2>/dev/null
    rm -rf "$STAGE_DIR"
    ok "已清理（镜像保留，删除用 docker rmi $IMAGE）"
}

case "${1:-all}" in
    preflight) preflight ;;
    build)     preflight; build_dist; build_image ;;
    image)     build_image ;;
    up)        up ;;
    e2e)       e2e || { dump_logs; fail "E2E 未通过"; } ;;
    clean)     clean ;;
    distclean) clean; distclean ;;
    all)
        preflight
        build_dist
        build_image
        up
        if e2e; then
            say "全部通过——可以推了"
            clean
        else
            dump_logs
            echo
            echo "栈仍在运行，方便你继续排查：" >&2
            echo "  docker compose -p $PROJECT --project-directory $STAGE_DIR logs -f cloudfile" >&2
            echo "  ./tools/verify-local.sh clean   # 查完清理" >&2
            exit 1
        fi
        ;;
    *) fail "未知阶段：$1（preflight|build|image|up|e2e|clean|distclean|all）" ;;
esac
