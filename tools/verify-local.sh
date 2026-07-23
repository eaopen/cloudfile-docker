#!/bin/bash
#
# 在本机跑一遍与 CI 完全相同的基线门禁。
#
# 存在的理由很直接：CI 一轮 20 分钟，而前六次失败全是集成边界上的问题——
# PATH、依赖链、系统库、版本号格式、TLS——没有一个是 `bash -n` 或单元测试能
# 发现的。一次次"改一行、推一次、等二十分钟"太慢了。这个脚本把同样的步骤
# 搬到本地，失败在几分钟内就能看见。
#
#   ./tools/verify-local.sh              # 基线全流程（开关全关 = 原生 CE）
#   ./tools/verify-local.sh preflight    # 只做静态一致性检查（秒级）
#   ./tools/verify-local.sh build        # 只构建发行包
#   ./tools/verify-local.sh e2e          # 假设镜像已在，只跑起栈 + E2E
#   ./tools/verify-local.sh cap acl      # 能力门禁：开着 ACL 跑六入口矩阵
#   ./tools/verify-local.sh clean        # 清掉本地栈与数据
#
# 基线门禁与能力门禁问的是不同的问题，所以是两条命令：前者问"开关全关时是否
# 等同原生 CE"，后者问"开着开关时，每个入口是否真的执行了规则"。
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
    say "构建发行包 ${VERSION}（容器内，宿主机不受影响）"

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

    # 清掉上一次的组装目录与同版本产物。
    #
    # 打包分两步：先把各组件装进 seafile-server/，再整体移进
    # seafile-server-<版本>/。两个目录**都会**让第二次构建失败，而且报的是不同
    # 的错——组装目录残留时是 "failed to copy upgrade scripts: File exists"，
    # 产物目录残留时是 "Destination path ... already exists"。只清后者会让人
    # 以为修好了，然后在下一层撞上同样的问题（本轮就是这么绕的）。
    #
    # 不碰 src/：那是 clone 缓存，重建它才是真正慢的部分。换架构或构建被中断
    # 后的彻底清理仍然用 distclean。
    rm -rf "$repo/build/cloudfile_14.0/seafile-server" \
           "$repo/build/cloudfile_14.0/seafile-server-$VERSION"

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
#
# 能力门禁登记表：<名字>|<开关>|<E2E 脚本>
#
# 基线门禁问"开关全关时是否等同原生 CE"，所以它一个能力都不测；能力门禁问
# "规则算出来之后，每个入口是否真的执行了"。两者必须分开跑，而本地此前**只有
# 前者**——于是每验证一个能力都要手抄一遍 acl-e2e.yml 的步骤，抄错了还看不出来
# （acl_matrix.py 缺 --insecure 就是这么留到今天的）。
#
# 加一个能力＝加一行，并保持与 .github/workflows/<能力>-e2e.yml 一致。
CAPABILITIES=(
    "acl|CF_ENABLE_DIR_ACL|tests/e2e/acl_matrix.py"
    "sso|CF_ENABLE_SSO|tests/e2e/sso_matrix.py"
)

# 由 capability 阶段设置：要在 .env 里打开的开关。
ENABLE_SWITCHES=${ENABLE_SWITCHES:-}
# 当前能力名，供 stage_compose 找到它的 cap_<名>_env / cap_<名>_run 钩子。
CAP_NAME=${CAP_NAME:-}

# ── 能力自己的配置与跑法 ─────────────────────────────────────────────────
#
# 光有开关不够：有的能力还要 provider 选型、外部服务地址这类配置，有的要跑不止
# 一遍。约定用两个可选函数表达，而不是把字段越加越多——字段能表达的东西有限，
# 而"改配置、重启、再断言"这种形状根本塞不进一行表格。
#
#   cap_<名>_env   往 .env 追加的行（每行 KEY=VALUE）
#   cap_<名>_run   自定义跑法；不定义则跑一遍 <能力>_matrix.py
#
# 必须与 .github/workflows/<能力>-e2e.yml 保持一致——本地门禁存在的全部理由就是
# 不要再手抄那份 workflow。

cap_sso_env() {
    cat <<EOF
CF_PROVIDER_SSO_DIRECTORY=static
CF_SSO_GROUP_OWNER=$ADMIN_EMAIL
CF_SSO_DIRECTORY_STATIC=[{"external_id":"eng","name":"SSO Engineering","members":["sso-matrix-a@example.com","sso-matrix-b@example.com"]},{"external_id":"sales","name":"SSO Sales","members":["sso-matrix-b@example.com"]}]
EOF
}

cap_sso_run() {
    local base=$1

    say "阶段 1 —— 组织结构落地"
    python3 "$repo/tests/e2e/sso_matrix.py" --phase 1 --url "$base" --insecure \
        --admin "$ADMIN_EMAIL" --admin-password "$ADMIN_PASSWORD" || return 1

    # 删除方向只有把目录改小才能测到，而"只加不删"的同步在阶段 1 里是全绿的。
    # 重启这一步同时也在测配置每次启动重写——改了 .env 却不生效是这套部署
    # 踩过的坑。后写的同名键覆盖先写的。
    say "目录变小并重启（eng 只剩 A，sales 消失）"
    echo 'CF_SSO_DIRECTORY_STATIC=[{"external_id":"eng","name":"SSO Engineering","members":["sso-matrix-a@example.com"]}]' \
        >> "$STAGE_DIR/.env"
    compose up -d || return 1

    say "阶段 2 —— 删除方向与「解除映射不等于删除」"
    python3 "$repo/tests/e2e/sso_matrix.py" --phase 2 --url "$base" --insecure \
        --admin "$ADMIN_EMAIL" --admin-password "$ADMIN_PASSWORD" || return 1
}

stage_compose() {
    # 先把还活着的栈拆掉，再动目录。
    #
    # 每个服务的数据都是 ./data/... 的 bind mount，就在 STAGE_DIR 里面。直接
    # rm -rf 会在容器仍持有这些挂载时把宿主目录抽走：db 容器不会被重建，于是
    # 继续用着旧库，而 seafile-data 已经空了——setup 以为是全新安装，撞上一个
    # 已经建好 schema 的数据库，退出 1。
    #
    # 表面症状只有一个 Caddy 502，和真因隔着十万八千里。第二次跑本地门禁就是
    # 这么挂的，而第一次跑没事纯粹因为那时没有存量栈。
    if [[ -d $STAGE_DIR ]]; then
        compose down -v >/dev/null 2>&1 || true
    fi
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

    for sw in $ENABLE_SWITCHES; do
        grep -q "^$sw=" "$STAGE_DIR/.env" \
            || fail "$sw 不在 .env.example 里——开关清单不同步"
        sed -i.bak "s|^$sw=.*|$sw=true|" "$STAGE_DIR/.env" && rm -f "$STAGE_DIR/.env.bak"
        # 确认真的写进去了。开着开关跑却其实没开，全绿的矩阵毫无意义——
        # 而那种失败是完全静默的。
        grep -q "^$sw=true$" "$STAGE_DIR/.env" || fail "$sw 未能置为 true"
        ok "$sw=true"
    done

    # 能力自己的配置。追加而不是替换：后写的同名键覆盖先写的，而 JSON 值里的
    # 引号和方括号不必再去和 sed 表达式搏斗。
    if [[ -n $CAP_NAME ]] && declare -F "cap_${CAP_NAME}_env" >/dev/null; then
        local line
        while IFS= read -r line; do
            [[ -z $line ]] && continue
            echo "$line" >> "$STAGE_DIR/.env"
            # 同上：配置没写进去而门禁全绿，是最没有价值的一种绿。
            grep -qxF "$line" "$STAGE_DIR/.env" || fail "未能写入 .env：${line%%=*}"
            ok "${line%%=*} 已配置"
        done < <("cap_${CAP_NAME}_env")
    fi
}

compose() { docker compose -p "$PROJECT" --project-directory "$STAGE_DIR" "$@"; }

up() {
    need_docker
    docker image inspect "$IMAGE" >/dev/null 2>&1 \
        || fail "本地没有镜像 ${IMAGE}，先跑 build"
    if [[ -n $ENABLE_SWITCHES ]]; then
        say "启动（开启：${ENABLE_SWITCHES}）"
    else
        say "启动（开关全关）"
    fi
    stage_compose
    compose up -d || fail "compose 启动失败"
    compose ps
}

base_url() {
    # 443 时不带端口，让 URL 与 seahub 生成的绝对链接完全一致
    local base="https://127.0.0.1"
    [[ $HTTPS_PORT != 443 ]] && base="https://127.0.0.1:$HTTPS_PORT"
    echo "$base"
}

e2e() {
    local base; base=$(base_url)
    say "原生 CE 冒烟 @ $base"
    python3 "$repo/tests/e2e/smoke.py" --url "$base" --insecure \
        --admin "$ADMIN_EMAIL" --admin-password "$ADMIN_PASSWORD" || return 1

    say "扩展点已装好，但没有能力启用"
    python3 "$repo/tests/e2e/baseline.py" --url "$base" --insecure \
        --admin "$ADMIN_EMAIL" --admin-password "$ADMIN_PASSWORD" || return 1
}

# 能力门禁：开着自己的开关起栈，先证明没把原生功能弄坏，再跑能力自己的用例。
#
# 顺序是有意的：冒烟先挂的话，能力矩阵的失败信息会指向一堆下游症状，
# 排查时分不清"规则拦错了"还是"服务压根没起来"。与 <能力>-e2e.yml 同序。
capability_e2e() {
    local name=$1 switch test_rel entry
    for entry in "${CAPABILITIES[@]}"; do
        IFS='|' read -r cap switch test_rel <<< "$entry"
        [[ $cap == "$name" ]] && break
        cap=''
    done
    [[ -n ${cap:-} ]] || fail "未知能力：${name}（已登记：$(printf '%s ' "${CAPABILITIES[@]%%|*}"))"
    [[ -f $repo/$test_rel ]] || fail "找不到 $test_rel"

    ENABLE_SWITCHES=$switch
    CAP_NAME=$name
    up

    local base; base=$(base_url)
    say "原生功能未被破坏（$switch 已开启）"
    python3 "$repo/tests/e2e/smoke.py" --url "$base" --insecure \
        --admin "$ADMIN_EMAIL" --admin-password "$ADMIN_PASSWORD" || return 1

    say "能力门禁：$name"
    if declare -F "cap_${name}_run" >/dev/null; then
        "cap_${name}_run" "$base" || return 1
    else
        python3 "$repo/$test_rel" --url "$base" --insecure \
            --admin "$ADMIN_EMAIL" --admin-password "$ADMIN_PASSWORD" || return 1
    fi
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
    ok "已清理（镜像保留，删除用 docker rmi ${IMAGE}）"
}

case "${1:-all}" in
    preflight) preflight ;;
    build)     preflight; build_dist; build_image ;;
    image)     build_image ;;
    up)        up ;;
    e2e)       e2e || { dump_logs; fail "E2E 未通过"; } ;;
    clean)     clean ;;
    distclean) clean; distclean ;;
    # 能力门禁。镜像必须已经在（先跑 build），因为能力代码来自被构建的那个
    # 分支，不是运行时开关能变出来的。
    cap|capability)
        [[ $# -ge 2 ]] || fail "用法：$0 cap <能力名>（已登记：$(printf '%s ' "${CAPABILITIES[@]%%|*}"))"
        if capability_e2e "$2"; then
            say "能力门禁通过：$2"
            clean
        else
            dump_logs
            echo
            echo "栈仍在运行，方便你继续排查：" >&2
            echo "  docker compose -p $PROJECT --project-directory $STAGE_DIR logs -f cloudfile" >&2
            echo "  ./tools/verify-local.sh clean" >&2
            exit 1
        fi
        ;;
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
