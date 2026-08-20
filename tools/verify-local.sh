#!/bin/bash
#
# 在本机运行完整的构建与验收门禁。
#
# 存在的理由很直接：CI 一轮 20 分钟，而前六次失败全是集成边界上的问题——qu
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
# GitHub Actions 仅执行 dev 快速检查与 prod 构建；所有容器 E2E 均在本机执行。
# 本地环境与 GitHub runner 的差异：
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
# 能力门禁登记表：<名字>|<开关>|<E2E 脚本>。这是本地验收的唯一登记处。
CAPABILITIES=(
    "acl|CF_ENABLE_DIR_ACL|tests/e2e/acl_matrix.py"
    "sso|CF_ENABLE_SSO|tests/e2e/sso_matrix.py"
    "metadata|CF_ENABLE_METADATA CF_ENABLE_TAGS|tests/e2e/metadata_matrix.py"
    "audit|CF_ENABLE_AUDIT|tests/e2e/audit_matrix.py"
    "storage|CF_ENABLE_S3_STORAGE|tests/e2e/storage_matrix.py"
    "search|CF_ENABLE_SEARCH CF_ENABLE_DIR_ACL|tests/e2e/search_matrix.py"
    "external_sources|CF_ENABLE_EXTERNAL_SOURCES|tests/e2e/external_sources_matrix.py"
    "fileop|CF_FILEOP_TEST_PROVIDER|tests/e2e/fileop_matrix.py"
    "lock|CF_ENABLE_FILE_LOCK CF_ENABLE_CHECKOUT|tests/e2e/lock_matrix.py"
    "local-edit|CF_ENABLE_FILE_LOCK CF_ENABLE_LOCAL_APP|tests/e2e/local_edit_matrix.py"
    "office|CF_ENABLE_ONLYOFFICE|tests/e2e/office_matrix.py"
    "review-tree||tests/e2e/review_tree_matrix.py"
    "review-icon||tests/e2e/review_icon_matrix.py"
    "review-copy|CF_ENABLE_DIR_ACL CF_ENABLE_FILEOPS|tests/e2e/review_copy_matrix.py"
    "review-move|CF_ENABLE_DIR_ACL CF_ENABLE_FILEOPS|tests/e2e/review_move_matrix.py"
    "review-tags|CF_ENABLE_METADATA CF_ENABLE_TAGS|tests/e2e/review_tags_matrix.py"
    "review-search|CF_ENABLE_DIR_ACL CF_ENABLE_SEARCH|tests/e2e/review_search_matrix.py"
    "review-history||tests/e2e/review_history_matrix.py"
    "review-recycle||tests/e2e/review_recycle_matrix.py"
    "review-share|CF_ENABLE_SHARE_RESTRICT|tests/e2e/review_share_matrix.py"
    "favorites|CF_ENABLE_FAVORITES_ID|tests/e2e/favorites_matrix.py"
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
# 编排与矩阵放在同一脚本内，避免维护第二份 GitHub workflow。

cap_sso_env() {
    cat <<EOF
CF_PROVIDER_SSO_DIRECTORY=static
CF_SSO_GROUP_OWNER=$ADMIN_EMAIL
CF_SERVICE_SSO_DIRECTORY_SECRET=CloudFile-Local-Sso-Webhook-4417
CF_SSO_DIRECTORY_STATIC=[{"external_id":"eng","name":"SSO Engineering","members":["sso-matrix-a@example.com","sso-matrix-b@example.com"]},{"external_id":"sales","name":"SSO Sales","members":["sso-matrix-b@example.com"]}]
EOF
}

cap_sso_run() {
    local base=$1

    say "启动 SSO 周期 worker"
    compose --profile worker up -d cf-worker || return 1

    say "阶段 1 —— 组织结构落地"
    python3 "$repo/tests/e2e/sso_matrix.py" --phase 1 --url "$base" --insecure \
        --admin "$ADMIN_EMAIL" --admin-password "$ADMIN_PASSWORD" \
        --require-worker \
        --webhook-secret CloudFile-Local-Sso-Webhook-4417 || return 1

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

cap_metadata_run() {
    local base=$1

    say "启动官方 metadata-server"
    compose --profile metadata up -d --wait --wait-timeout 150 cloudfile-metadata || return 1

    say "属性/标签验收矩阵"
    python3 "$repo/tests/e2e/metadata_matrix.py" --url "$base" --insecure \
        --admin "$ADMIN_EMAIL" --admin-password "$ADMIN_PASSWORD" || return 1
}

cap_storage_env() {
    cat <<EOF
SEAF_SERVER_STORAGE_TYPE=multiple
S3_COMMIT_BUCKET=cloudfile-commits
S3_FS_BUCKET=cloudfile-fs
S3_BLOCK_BUCKET=cloudfile-blocks
MINIO_API_PORT=19000
MINIO_CONSOLE_PORT=19001
CF_STORAGE_CLASSES_JSON=[{"storage_id":"local","is_default":true,"commits":{"backend":"fs","dir":"/shared/seafile"},"fs":{"backend":"fs","dir":"/shared/seafile"},"blocks":{"backend":"fs","dir":"/shared/seafile"}},{"storage_id":"minio","commits":{"backend":"s3","bucket":"cloudfile-commits","host":"minio:9000","key_id":"minioadmin","key":"change-this-minio-password","use_https":false,"path_style_request":true,"max_retries":2},"fs":{"backend":"s3","bucket":"cloudfile-fs","host":"minio:9000","key_id":"minioadmin","key":"change-this-minio-password","use_https":false,"path_style_request":true,"max_retries":2},"blocks":{"backend":"s3","bucket":"cloudfile-blocks","host":"minio:9000","key_id":"minioadmin","key":"change-this-minio-password","use_https":false,"path_style_request":true,"max_retries":2}}]
EOF
}

# 存储门禁独有的两点，其它能力都不需要：
#
#   1. GC/FSCK/迁移是宿主机侧 CLI 行为，不经过 HTTP，storage_matrix.py 覆盖不到，
#      只能用 `compose exec`/`compose run` 直接驱动。
#   2. 迁移必须停服。不能只杀容器内的 seaf-server/fileserver 进程——
#      start.py 的 watch_controller 每 5 秒检查一次控制器，连续 4 次
#      (20 秒) 找不到就会杀掉整个容器，迁移一慢就会跟这个内部看门狗撞车。
#      改成停整个 cloudfile 容器、用同一份 /shared 卷跑一次性容器做迁移，
#      再重启——不给看门狗任何观察窗口。
cap_storage_run() {
    local base=$1 repo_id

    say "启动 MinIO"
    compose --profile s3 up -d --wait --wait-timeout 90 minio-init || return 1

    say "阶段 1 —— 上传并校验跨多个 block 的文件"
    python3 "$repo/tests/e2e/storage_matrix.py" --phase 1 --url "$base" --insecure \
        --admin "$ADMIN_EMAIL" --admin-password "$ADMIN_PASSWORD" \
        --state-file "$STAGE_DIR/storage-matrix-state.json" || return 1

    say "GC 与 FSCK 完整遍历 S3 后端"
    compose exec -T cloudfile bash -c \
        '/opt/seafile/$SEAFILE_SERVER-$SEAFILE_VERSION/seaf-gc.sh --dry-run' || return 1
    compose exec -T cloudfile bash -c \
        '/opt/seafile/$SEAFILE_SERVER-$SEAFILE_VERSION/seaf-fsck.sh' || return 1

    say "修复模式必须先停服——服务仍在运行时应被拒绝"
    local repair_output repair_status
    repair_output=$(compose exec -T cloudfile bash -c \
        '/opt/seafile/$SEAFILE_SERVER-$SEAFILE_VERSION/seaf-fsck.sh --repair' 2>&1)
    repair_status=$?
    if [[ $repair_status -eq 0 ]]; then
        echo "✗ seaf-fsck.sh --repair 应在服务运行时被拒绝，却返回了 0" >&2
        return 1
    fi
    if [[ $repair_output != *'stop seaf-server and fileserver'* ]]; then
        echo "✗ seaf-fsck.sh --repair 被拒绝，但错误信息不是预期的那条：$repair_output" >&2
        return 1
    fi
    ok "seaf-fsck.sh --repair 在服务运行时被正确拒绝"

    repo_id=$(python3 -c \
        "import json;print(json.load(open('$STAGE_DIR/storage-matrix-state.json'))['repo_id'])") \
        || { echo "✗ 读不到 phase 1 写入的 repo_id" >&2; return 1; }

    say "离线迁移：停止整个 cloudfile 容器"
    compose stop cloudfile || return 1

    say "以一次性容器执行 seaf-storage-migrate.sh（共享同一份 /shared 卷）"
    compose run --rm --no-deps --entrypoint bash cloudfile -c \
        "/etc/my_init.d/01_create_data_links.sh && /opt/seafile/\$SEAFILE_SERVER-\$SEAFILE_VERSION/seaf-storage-migrate.sh $repo_id minio" \
        || return 1

    say "重启并等待就绪"
    compose up -d --wait --wait-timeout 120 cloudfile || return 1

    say "阶段 2 —— 迁移后读写仍然正确"
    python3 "$repo/tests/e2e/storage_matrix.py" --phase 2 --url "$base" --insecure \
        --admin "$ADMIN_EMAIL" --admin-password "$ADMIN_PASSWORD" \
        --state-file "$STAGE_DIR/storage-matrix-state.json" || return 1

    say "迁移后 GC 与 FSCK 仍然通过"
    compose exec -T cloudfile bash -c \
        '/opt/seafile/$SEAFILE_SERVER-$SEAFILE_VERSION/seaf-gc.sh --dry-run' || return 1
    compose exec -T cloudfile bash -c \
        '/opt/seafile/$SEAFILE_SERVER-$SEAFILE_VERSION/seaf-fsck.sh' || return 1
}

# 阶段 1 要先把标记留空（全部放行）才能建出夹具；阶段 2 再把标记打开。
# 与 sso 的"目录变小 + 重启"、search 的"切 provider + 重启"是同一个形状：
# 配置切换与重启在这里做，矩阵自己只发 HTTP 请求。
cap_fileop_env() {
    cat <<EOF
CF_FILEOP_TEST_REFUSE_TOKEN=
CF_FILEOP_TEST_JOURNAL=/shared/cf-fileop-journal.log
EOF
}

cap_fileop_run() {
    local base=$1
    # 容器里的 /shared 就是宿主机的 data/seafile。
    local journal="$STAGE_DIR/data/seafile/cf-fileop-journal.log"

    say "阶段 1 —— 观察模式：每个写入口都产生事实，成功一次只产生一个"
    python3 "$repo/tests/e2e/fileop_matrix.py" --phase 1 --url "$base" --insecure \
        --admin "$ADMIN_EMAIL" --admin-password "$ADMIN_PASSWORD" \
        --journal "$journal" \
        --state-file "$STAGE_DIR/fileop-matrix-state.json" || return 1

    # 拒绝方向只有把标记打开才能测到，而夹具必须在打开之前建好——拒绝一开，
    # 建标记路径本身就会被拒，那恰好是被测操作之一。
    say "打开拒绝标记并重启（cf-refuse）"
    echo 'CF_FILEOP_TEST_REFUSE_TOKEN=cf-refuse' >> "$STAGE_DIR/.env"
    compose up -d || return 1

    say "阶段 2 —— 逐入口拒绝、零事实，外加反向对照"
    python3 "$repo/tests/e2e/fileop_matrix.py" --phase 2 --url "$base" --insecure \
        --admin "$ADMIN_EMAIL" --admin-password "$ADMIN_PASSWORD" \
        --journal "$journal" \
        --state-file "$STAGE_DIR/fileop-matrix-state.json" || return 1
}

# 锁门禁先开锁/签入签出跑跨协议矩阵，再关开关证原生透传。
# 矩阵自己只发 HTTP，配置切换与重启在这里做。
cap_lock_run() {
    local base=$1

    say "锁提供器确实注册"
    compose exec -T cloudfile grep -n 'file_lock_enabled = true' \
        /shared/seafile/conf/seafile.conf || return 1

    say "锁与签入签出跨协议矩阵"
    python3 "$repo/tests/e2e/lock_matrix.py" --url "$base" --insecure \
        --admin "$ADMIN_EMAIL" --admin-password "$ADMIN_PASSWORD" || return 1

    say "关闭后恢复原生 CE 透传"
    sed -i.bak -e "s|^CF_ENABLE_FILE_LOCK=.*|CF_ENABLE_FILE_LOCK=false|" \
               -e "s|^CF_ENABLE_CHECKOUT=.*|CF_ENABLE_CHECKOUT=false|" "$STAGE_DIR/.env" \
        && rm -f "$STAGE_DIR/.env.bak"
    compose up -d --wait --wait-timeout 120 cloudfile || return 1
    compose exec -T cloudfile grep -n 'file_lock_enabled = false' \
        /shared/seafile/conf/seafile.conf || return 1
    python3 "$repo/tests/e2e/smoke.py" --url "$base" --insecure \
        --admin "$ADMIN_EMAIL" --admin-password "$ADMIN_PASSWORD" || return 1
}

# review-search 的标签/创建人筛选只在 Meilisearch provider 下可断言（矩阵
# 头部契约：起 Meili、切 provider、跑一轮 cf_worker --once 均由这里编排）。
# 原 CI workflow 有这套编排，CI 清理时丢了。
cap_review-search_env() {
    cat <<EOF
MEILI_MASTER_KEY=CloudFile-Local-Search-4417
CF_MEILISEARCH_API_KEY=CloudFile-Local-Search-4417
EOF
}

# share-001（前端隐藏分享入口）是 channel=ui 用例，API 矩阵报 skipped；
# 浏览器套件在 API 用例之后跑同一栈（开关已开）。
cap_review-share_run() {
    local base=$1

    python3 "$repo/tests/e2e/review_share_matrix.py" --url "$base" --insecure \
        --admin "$ADMIN_EMAIL" --admin-password "$ADMIN_PASSWORD" || return 1

    say "浏览器套件：share-001 前端隐藏分享入口"
    python3 "$repo/tests/e2e/review_ui_share.py" --url "$base" --insecure \
        --admin "$ADMIN_EMAIL" --admin-password "$ADMIN_PASSWORD"
}

cap_review-search_run() {
    local base=$1

    say "启动 Meilisearch、切换 provider 并起 worker"
    compose --profile search up -d --wait --wait-timeout 90 meilisearch || return 1
    echo 'CF_PROVIDER_SEARCH=meilisearch' >> "$STAGE_DIR/.env"
    compose --profile worker up -d --wait --wait-timeout 180 cf-worker cloudfile || return 1

    say "手动跑一轮索引器回填"
    compose exec -T cloudfile bash -c \
        '/opt/seafile/$SEAFILE_SERVER-$SEAFILE_VERSION/seahub.sh python-env python3 /opt/seafile/$SEAFILE_SERVER-$SEAFILE_VERSION/seahub/manage.py cf_worker --once' \
        || return 1

    python3 "$repo/tests/e2e/review_search_matrix.py" --url "$base" --insecure \
        --admin "$ADMIN_EMAIL" --admin-password "$ADMIN_PASSWORD"
}

cap_search_env() {
    cat <<EOF
INIT_SS_ADMIN_USER=cf-search-admin
INIT_SS_ADMIN_PASSWORD=CloudFile-Local-Search-4417
CF_SEASEARCH_TOKEN=Y2Ytc2VhcmNoLWFkbWluOkNsb3VkRmlsZS1Mb2NhbC1TZWFyY2gtNDQxNw==
CF_SEASEARCH_INTERVAL=10s
MEILI_MASTER_KEY=CloudFile-Local-Search-4417
CF_MEILISEARCH_API_KEY=CloudFile-Local-Search-4417
CF_SEARCH_INDEX_INTERVAL=15
EOF
}

# review-copy 的大小/层级用例（copy-004/005）需要非零限制才有"超限"可测；
# 矩阵的契约是 100 字节 / 1 层（见 review_copy_matrix.py 头部注释）。
cap_review-copy_env() {
    cat <<EOF
CF_FILEOP_MAX_FILE_SIZE=100
CF_FILEOP_MAX_FOLDER_DEPTH=1
EOF
}

# bootstrap 对 CF_ENABLE_ONLYOFFICE=true 有 fail-fast：JWT secret 为空直接拒启
# （无签名回调漏过正是该门禁要移除的风险）。DS 8.2 镜像本机拉取曾中断，
# 浏览器内编辑会话与 convert 依赖它——先满足无 DS 也能跑的 6 项断言。
cap_office_env() {
    cat <<EOF
ONLYOFFICE_JWT_SECRET=CloudFile-Local-Office-4417
ONLYOFFICE_APIJS_URL=http://onlyoffice:80/web-apps/apps/api/documents/api.js
ONLYOFFICE_FILE_SERVER_ROOT=http://cloudfile:8082
EOF
}

# convert 往返需要真实 Document Server（office profile）。此前只有 CI 起 DS，
# CI 清理后本机门禁从未起过——convert 一直靠"此前容器门禁通过"背书。
cap_office_run() {
    local base=$1

    say "启动 Document Server 8.2（JWT 开）"
    if ! compose --profile office up -d --wait --wait-timeout 300 onlyoffice; then
        echo "⚠ Document Server 未能在 300s 内就绪（镜像拉取大）——convert 用例记为技术负债，其余断言继续" >&2
    fi

    python3 "$repo/tests/e2e/office_matrix.py" --url "$base" --insecure \
        --admin "$ADMIN_EMAIL" --admin-password "$ADMIN_PASSWORD"
}

# 原 CI workflow（63e27bb）有"准备挂载目录 fixture"步骤，CI 清理时丢了：
# 矩阵登记 /shared/external/e2e 后要读 readme.txt/nested/inside.txt，但这些
# 文件必须先写进宿主机 bind mount（./data/seafile = 容器 /shared）。
cap_external_sources_run() {
    local base=$1

    say "准备挂载目录 fixture"
    compose exec -T cloudfile bash -c \
        "mkdir -p /shared/external/e2e/nested && printf 'CloudFile external source fixture\\n' > /shared/external/e2e/readme.txt && printf 'nested fixture\\n' > /shared/external/e2e/nested/inside.txt" || return 1

    python3 "$repo/tests/e2e/external_sources_matrix.py" --url "$base" --insecure \
        --admin "$ADMIN_EMAIL" --admin-password "$ADMIN_PASSWORD"
}

# 三阶段对应三次配置变更；search_matrix.py 本身只发 HTTP 请求，不碰 .env 或
# 容器——配置切换与重启统一在这里做，与 sso 的目录变小+重启是同一个理由：
# 把"改配置会不会真的生效"和"规则算得对不对"分开验证。
cap_search_run() {
    local base=$1

    say "启动 SeaSearch 与 Meilisearch（缩短 SeaSearch 索引间隔到 10s）"
    compose --profile search up -d --wait --wait-timeout 90 seasearch meilisearch || return 1

    # seasearch 容器没有 healthcheck，--wait 只等 running；而 seafevents 在
    # SeaSearch 未就绪时 init index object 失败后 _enabled=False 且永不重试
    # （上游竞态）。等 /healthz 真正 200 后重启 cloudfile，让 seafevents 重新
    # 初始化索引对象。
    say "等待 SeaSearch /healthz 并重启 cloudfile 重试索引初始化"
    local i ok_health=0
    for i in $(seq 1 30); do
        if compose exec -T cloudfile bash -c \
            'curl -sf -m 3 http://seasearch:4080/healthz >/dev/null' 2>/dev/null; then
            ok_health=1; break
        fi
        sleep 2
    done
    [[ $ok_health -eq 1 ]] || { echo "✗ SeaSearch /healthz 60s 内未就绪" >&2; return 1; }
    compose restart cloudfile || return 1
    compose up -d --wait --wait-timeout 180 cloudfile || return 1

    say "阶段 1 —— 默认路径：CF_PROVIDER_SEARCH 留空，走 SeaSearch"
    python3 "$repo/tests/e2e/search_matrix.py" --phase 1 --url "$base" --insecure \
        --admin "$ADMIN_EMAIL" --admin-password "$ADMIN_PASSWORD" \
        --state-file "$STAGE_DIR/search-matrix-state.json" || return 1

    say "切到 CF_PROVIDER_SEARCH=meilisearch 并重启"
    echo 'CF_PROVIDER_SEARCH=meilisearch' >> "$STAGE_DIR/.env"
    compose up -d --wait --wait-timeout 120 cloudfile || return 1

    say "手动跑一轮索引器（不等定时，回填切换前已存在的提交）"
    compose exec -T cloudfile bash -c \
        '/opt/seafile/$SEAFILE_SERVER-$SEAFILE_VERSION/seahub.sh python-env python3 /opt/seafile/$SEAFILE_SERVER-$SEAFILE_VERSION/seahub/manage.py cf_worker --once' \
        || return 1

    say "阶段 2 —— Meilisearch 路径，验证回填"
    python3 "$repo/tests/e2e/search_matrix.py" --phase 2 --url "$base" --insecure \
        --admin "$ADMIN_EMAIL" --admin-password "$ADMIN_PASSWORD" \
        --state-file "$STAGE_DIR/search-matrix-state.json" || return 1

    say "关闭 CF_ENABLE_SEARCH 并重启，确认恢复原生行为"
    sed -i.bak "s|^CF_ENABLE_SEARCH=.*|CF_ENABLE_SEARCH=false|" "$STAGE_DIR/.env" \
        && rm -f "$STAGE_DIR/.env.bak"
    compose up -d --wait --wait-timeout 120 cloudfile || return 1

    say "阶段 3 —— 关闭后恢复原生 403"
    python3 "$repo/tests/e2e/search_matrix.py" --phase 3 --url "$base" --insecure \
        --admin "$ADMIN_EMAIL" --admin-password "$ADMIN_PASSWORD" \
        --state-file "$STAGE_DIR/search-matrix-state.json" || return 1
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
# 排查时分不清"规则拦错了"还是"服务压根没起来"，因此先跑原生冒烟。
capability_e2e() {
    local name=$1 switch test_rel entry
    for entry in "${CAPABILITIES[@]}"; do
        IFS='|' read -r cap switch test_rel <<< "$entry"
        [[ $cap == "$name" ]] && break
        cap=''
    done
    [[ -n ${cap:-} ]] || fail "未知能力：${name}（已登记：$(printf '%s ' "${CAPABILITIES[@]%%|*}")）"
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
        [[ $# -ge 2 ]] || fail "用法：$0 cap <能力名>（已登记：$(printf '%s ' "${CAPABILITIES[@]%%|*}")）"
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
