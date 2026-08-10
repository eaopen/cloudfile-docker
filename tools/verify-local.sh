#!/bin/bash
#
# 鍦ㄦ湰鏈鸿窇涓€閬嶄笌 CI 瀹屽叏鐩稿悓鐨勫熀绾块棬绂併€?
#
# 瀛樺湪鐨勭悊鐢卞緢鐩存帴锛欳I 涓€杞?20 鍒嗛挓锛岃€屽墠鍏澶辫触鍏ㄦ槸闆嗘垚杈圭晫涓婄殑闂鈥斺€?
# PATH銆佷緷璧栭摼銆佺郴缁熷簱銆佺増鏈彿鏍煎紡銆乀LS鈥斺€旀病鏈変竴涓槸 `bash -n` 鎴栧崟鍏冩祴璇曡兘
# 鍙戠幇鐨勩€備竴娆℃"鏀逛竴琛屻€佹帹涓€娆°€佺瓑浜屽崄鍒嗛挓"澶參浜嗐€傝繖涓剼鏈妸鍚屾牱鐨勬楠?
# 鎼埌鏈湴锛屽け璐ュ湪鍑犲垎閽熷唴灏辫兘鐪嬭銆?
#
#   ./tools/verify-local.sh              # 鍩虹嚎鍏ㄦ祦绋嬶紙寮€鍏冲叏鍏?= 鍘熺敓 CE锛?
#   ./tools/verify-local.sh preflight    # 鍙仛闈欐€佷竴鑷存€ф鏌ワ紙绉掔骇锛?
#   ./tools/verify-local.sh build        # 鍙瀯寤哄彂琛屽寘
#   ./tools/verify-local.sh e2e          # 鍋囪闀滃儚宸插湪锛屽彧璺戣捣鏍?+ E2E
#   ./tools/verify-local.sh cap acl      # 鑳藉姏闂ㄧ锛氬紑鐫€ ACL 璺戝叚鍏ュ彛鐭╅樀
#   ./tools/verify-local.sh clean        # 娓呮帀鏈湴鏍堜笌鏁版嵁
#
# 鍩虹嚎闂ㄧ涓庤兘鍔涢棬绂侀棶鐨勬槸涓嶅悓鐨勯棶棰橈紝鎵€浠ユ槸涓ゆ潯鍛戒护锛氬墠鑰呴棶"寮€鍏冲叏鍏虫椂鏄惁
# 绛夊悓鍘熺敓 CE"锛屽悗鑰呴棶"寮€鐫€寮€鍏虫椂锛屾瘡涓叆鍙ｆ槸鍚︾湡鐨勬墽琛屼簡瑙勫垯"銆?
#
# 涓?CI 鐨勫樊寮傦紙鏈夋剰涓轰箣锛屼笖鍙湁杩欎簺锛夛細
#   - 鏋勫缓鍦?ubuntu 瀹瑰櫒閲岃窇锛圕I 鐨?runner 鏈韩灏辨槸 ubuntu锛?
#   - 绔彛榛樿 80/443锛堜笌 CI 涓€鑷达紝缁濆 URL 鎵嶅寰椾笂锛夛紱琚崰鐢ㄦ椂鍙敤
#     CF_LOCAL_HTTP_PORT / CF_LOCAL_HTTPS_PORT 瑕嗙洊
#   - Compose 璺戝湪涓存椂鐩綍閲岋紝涓嶇 deploy/compose/ 涓嬩綘鑷繁鐨?.env 鍜?data/
#   - 鏋舵瀯璺熼殢鏈満锛圓pple Silicon 涓婃槸 arm64锛夈€備笂娓?arm 涓?x86 鐨?Dockerfile
#     閫愬瓧鑺傜浉鍚岋紝鎵€浠ヨ繖涓嶅奖鍝嶇粨璁猴紱瑕侀獙 amd64 灏辫 CF_PLATFORM=linux/amd64銆?

set -uo pipefail

here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$here/.." && pwd)
workspace=$(dirname "$repo")

VERSION=${CF_VERSION:-14.0.0-cf.0-local}
IMAGE=cloudfile/cloudfile:$VERSION
PROJECT=cloudfile-local
# 榛樿鐢?80/443锛屽拰 CI 淇濇寔涓€鑷淬€?
#
# 鏀规垚 8080/8443 鐪嬩技鏇?绀艰矊"锛屼絾浼氳楠岃瘉澶辩湡锛歴eahub 鐢熸垚鐨勬槸缁濆 URL
# 锛堜笂浼?涓嬭浇閾炬帴鎸囧悜 https://<hostname>/seafhttp/...锛岄殣鍚粯璁ょ鍙ｏ級锛?
# 瀹㈡埛绔繛杩囧幓蹇呯劧 Connection refused鈥斺€旀姤閿欒惤鍦?涓婁紶鏂囦欢"涓婏紝绂荤湡鍥犲緢杩溿€?
# 绔彛琚崰鐢ㄦ椂鐢?CF_LOCAL_HTTP_PORT/CF_LOCAL_HTTPS_PORT 瑕嗙洊锛屼絾瑕佺煡閬?
# 涓婁紶涓嬭浇閭ｅ嚑椤逛細鍥犳澶辫触銆?
HTTP_PORT=${CF_LOCAL_HTTP_PORT:-80}
HTTPS_PORT=${CF_LOCAL_HTTPS_PORT:-443}
ADMIN_EMAIL=admin@cloudfile.test
ADMIN_PASSWORD=CloudFile-Local-4417
STAGE_DIR=${CF_LOCAL_STAGE:-$repo/.local-verify}

say()  { printf '\n\033[1m鈺愨晲 %s\033[0m\n' "$*"; }
fail() { printf '\033[31m鉁?%s\033[0m\n' "$*" >&2; exit 1; }
ok()   { printf '\033[32m鉁?%s\033[0m\n' "$*"; }

need_docker() {
    docker info >/dev/null 2>&1 || fail "Docker 涓嶅彲鐢紙鍚姩 OrbStack / Docker Desktop / colima锛?
}

# 鈹€鈹€ preflight锛氶潤鎬佷竴鑷存€ф鏌?鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
#
# 涓撴姄"CI 閲屾墠浼氱偢"鐨勯偅绫讳笉涓€鑷达細workflow 寮曠敤浜嗕笉瀛樺湪鐨勮剼鏈€丒2E 鐨勫崗璁拰
# Compose 鐨?TLS 璁剧疆瀵逛笉涓娿€佸紑鍏虫竻鍗曚笁澶勪笉鍚屾銆傞兘鏄绾ф鏌ャ€?
preflight() {
    say "preflight锛氶潤鎬佷竴鑷存€?
    local bad=0

    "$here/run-checks.sh" >/dev/null 2>&1 \
        && ok "run-checks.sh 鍏ㄩ儴閫氳繃" \
        || { printf '\033[31m鉁?run-checks.sh 澶辫触锛屽崟鐙窇涓€娆＄湅璇︽儏\033[0m\n'; bad=1; }

    python3 "$here/preflight-checks.py" "$repo" "$workspace" || bad=1

    [[ $bad -eq 0 ]] || fail "preflight 鏈€氳繃鈥斺€斿厛淇帀鍐嶈姳浜屽崄鍒嗛挓鏋勫缓"
    say "preflight 閫氳繃"
}

# 鈹€鈹€ 鏋勫缓鍙戣鍖?鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
build_dist() {
    need_docker
    say "鏋勫缓鍙戣鍖?${VERSION}锛堝鍣ㄥ唴锛屽涓绘満涓嶅彈褰卞搷锛?

    # 榛樿鏋勫缓**骞舵帓 checkout 鐨勬湰鍦颁粨搴?*锛岃€屼笉鏄幓 GitHub 鎷夈€?
    #
    # 鏈湴闂ㄧ鐨勬剰涔夊氨鍦ㄤ簬楠岃瘉鎵嬪ご杩欎唤浠ｇ爜锛屽寘鎷繕娌?push 鐨勫垎鏀紱鍘绘媺杩滅
    # 绛変簬楠岃瘉浜嗗埆鐨勪笢瑗裤€傝 CF_SERVER_URL/CF_HUB_URL 鍙互瑕嗙洊鍥炶繙绔€?
    #
    # 鍙湁宸叉彁浜ょ殑鍐呭浼氳繘鏋勫缓锛堣 build-in-docker.sh锛夛紝鎵€浠ヨ窇涔嬪墠鍏?commit銆?
    for pair in "CF_SERVER_URL:cloudfile-server" "CF_HUB_URL:cloudfile-hub"; do
        var=${pair%%:*}; dir=${pair#*:}
        if [[ -z ${!var:-} && -d $workspace/$dir/.git ]]; then
            export "$var=$workspace/$dir"
            ref_var=${var%_URL}_REF
            if [[ -z ${!ref_var:-} ]]; then
                export "$ref_var=$(git -C "$workspace/$dir" rev-parse --abbrev-ref HEAD)"
            fi
            echo "  $dir 鈫?${!ref_var}"
        fi
    done

    # 娓呮帀涓婁竴娆＄殑缁勮鐩綍涓庡悓鐗堟湰浜х墿銆?
    #
    # 鎵撳寘鍒嗕袱姝ワ細鍏堟妸鍚勭粍浠惰杩?seafile-server/锛屽啀鏁翠綋绉昏繘
    # seafile-server-<鐗堟湰>/銆備袱涓洰褰?*閮戒細**璁╃浜屾鏋勫缓澶辫触锛岃€屼笖鎶ョ殑鏄笉鍚?
    # 鐨勯敊鈥斺€旂粍瑁呯洰褰曟畫鐣欐椂鏄?"failed to copy upgrade scripts: File exists"锛?
    # 浜х墿鐩綍娈嬬暀鏃舵槸 "Destination path ... already exists"銆傚彧娓呭悗鑰呬細璁╀汉
    # 浠ヤ负淇ソ浜嗭紝鐒跺悗鍦ㄤ笅涓€灞傛挒涓婂悓鏍风殑闂锛堟湰杞氨鏄繖涔堢粫鐨勶級銆?
    #
    # 涓嶇 src/锛氶偅鏄?clone 缂撳瓨锛岄噸寤哄畠鎵嶆槸鐪熸鎱㈢殑閮ㄥ垎銆傛崲鏋舵瀯鎴栨瀯寤鸿涓柇
    # 鍚庣殑褰诲簳娓呯悊浠嶇劧鐢?distclean銆?
    rm -rf "$repo/build/cloudfile_14.0/seafile-server" \
           "$repo/build/cloudfile_14.0/seafile-server-$VERSION"

    "$repo/build/cloudfile_14.0/build-in-docker.sh" "$VERSION" \
        || fail "鍙戣鍖呮瀯寤哄け璐?
    ok "鍙戣鍖呭畬鎴?
    cat "$repo/build/cloudfile_14.0/seafile-server-$VERSION/cloudfile-build-info.txt" 2>/dev/null || true
}

build_image() {
    need_docker
    say "鏋勫缓闀滃儚 $IMAGE"
    "$repo/image/cloudfile_14.0/docker-build.sh" "$VERSION" || fail "闀滃儚鏋勫缓澶辫触"
    ok "闀滃儚瀹屾垚"
}

# 鈹€鈹€ 璧锋爤 + E2E 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
#
# 鑳藉姏闂ㄧ鐧昏琛細<鍚嶅瓧>|<寮€鍏?|<E2E 鑴氭湰>
#
# 鍩虹嚎闂ㄧ闂?寮€鍏冲叏鍏虫椂鏄惁绛夊悓鍘熺敓 CE"锛屾墍浠ュ畠涓€涓兘鍔涢兘涓嶆祴锛涜兘鍔涢棬绂侀棶
# "瑙勫垯绠楀嚭鏉ヤ箣鍚庯紝姣忎釜鍏ュ彛鏄惁鐪熺殑鎵ц浜?銆備袱鑰呭繀椤诲垎寮€璺戯紝鑰屾湰鍦版鍓?*鍙湁
# 鍓嶈€?*鈥斺€斾簬鏄瘡楠岃瘉涓€涓兘鍔涢兘瑕佹墜鎶勪竴閬?acl-e2e.yml 鐨勬楠わ紝鎶勯敊浜嗚繕鐪嬩笉鍑烘潵
# 锛坅cl_matrix.py 缂?--insecure 灏辨槸杩欎箞鐣欏埌浠婂ぉ鐨勶級銆?
#
# 鍔犱竴涓兘鍔涳紳鍔犱竴琛岋紝骞朵繚鎸佷笌 .github/workflows/<鑳藉姏>-e2e.yml 涓€鑷淬€?
CAPABILITIES=(
    "acl|CF_ENABLE_DIR_ACL|tests/e2e/acl_matrix.py"
    "sso|CF_ENABLE_SSO|tests/e2e/sso_matrix.py"
    "metadata|CF_ENABLE_METADATA CF_ENABLE_TAGS|tests/e2e/metadata_matrix.py"
    "audit|CF_ENABLE_AUDIT|tests/e2e/audit_matrix.py"
    "storage|CF_ENABLE_S3_STORAGE|tests/e2e/storage_matrix.py"
    "search|CF_ENABLE_SEARCH|tests/e2e/search_matrix.py"
    # fileop 鏄熀绾挎墿灞曠偣锛屼笉鏄兘鍔涳紝鎵€浠ュ畠鐨?寮€鍏?涓嶆槸 CF_ENABLE_*鈥斺€旈偅浠芥竻鍗?
    # 閲岀殑姣忎竴椤归兘鏄繍缁村彲浠ュ悎鐞嗘墦寮€鐨勪骇鍝佽兘鍔涳紝鑰岃繖涓彧鏄棬绂佺敤鐨勪华鍣ㄣ€?
    "fileop|CF_FILEOP_TEST_PROVIDER|tests/e2e/fileop_matrix.py"
)

# 鐢?capability 闃舵璁剧疆锛氳鍦?.env 閲屾墦寮€鐨勫紑鍏炽€?
ENABLE_SWITCHES=${ENABLE_SWITCHES:-}
# 褰撳墠鑳藉姏鍚嶏紝渚?stage_compose 鎵惧埌瀹冪殑 cap_<鍚?_env / cap_<鍚?_run 閽╁瓙銆?
CAP_NAME=${CAP_NAME:-}

# 鈹€鈹€ 鑳藉姏鑷繁鐨勯厤缃笌璺戞硶 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
#
# 鍏夋湁寮€鍏充笉澶燂細鏈夌殑鑳藉姏杩樿 provider 閫夊瀷銆佸閮ㄦ湇鍔″湴鍧€杩欑被閰嶇疆锛屾湁鐨勮璺戜笉姝?
# 涓€閬嶃€傜害瀹氱敤涓や釜鍙€夊嚱鏁拌〃杈撅紝鑰屼笉鏄妸瀛楁瓒婂姞瓒婂鈥斺€斿瓧娈佃兘琛ㄨ揪鐨勪笢瑗挎湁闄愶紝
# 鑰?鏀归厤缃€侀噸鍚€佸啀鏂█"杩欑褰㈢姸鏍规湰濉炰笉杩涗竴琛岃〃鏍笺€?
#
#   cap_<鍚?_env   寰€ .env 杩藉姞鐨勮锛堟瘡琛?KEY=VALUE锛?
#   cap_<鍚?_run   鑷畾涔夎窇娉曪紱涓嶅畾涔夊垯璺戜竴閬?<鑳藉姏>_matrix.py
#
# 蹇呴』涓?.github/workflows/<鑳藉姏>-e2e.yml 淇濇寔涓€鑷粹€斺€旀湰鍦伴棬绂佸瓨鍦ㄧ殑鍏ㄩ儴鐞嗙敱灏辨槸
# 涓嶈鍐嶆墜鎶勯偅浠?workflow銆?

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

    say "鍚姩 SSO 鍛ㄦ湡 worker"
    compose --profile worker up -d cf-worker || return 1

    say "闃舵 1 鈥斺€?缁勭粐缁撴瀯钀藉湴"
    python3 "$repo/tests/e2e/sso_matrix.py" --phase 1 --url "$base" --insecure \
        --admin "$ADMIN_EMAIL" --admin-password "$ADMIN_PASSWORD" \
        --require-worker \
        --webhook-secret CloudFile-Local-Sso-Webhook-4417 || return 1

    # 鍒犻櫎鏂瑰悜鍙湁鎶婄洰褰曟敼灏忔墠鑳芥祴鍒帮紝鑰?鍙姞涓嶅垹"鐨勫悓姝ュ湪闃舵 1 閲屾槸鍏ㄧ豢鐨勩€?
    # 閲嶅惎杩欎竴姝ュ悓鏃朵篃鍦ㄦ祴閰嶇疆姣忔鍚姩閲嶅啓鈥斺€旀敼浜?.env 鍗翠笉鐢熸晥鏄繖濂楅儴缃?
    # 韪╄繃鐨勫潙銆傚悗鍐欑殑鍚屽悕閿鐩栧厛鍐欑殑銆?
    say "鐩綍鍙樺皬骞堕噸鍚紙eng 鍙墿 A锛宻ales 娑堝け锛?
    echo 'CF_SSO_DIRECTORY_STATIC=[{"external_id":"eng","name":"SSO Engineering","members":["sso-matrix-a@example.com"]}]' \
        >> "$STAGE_DIR/.env"
    compose up -d || return 1

    say "闃舵 2 鈥斺€?鍒犻櫎鏂瑰悜涓庛€岃В闄ゆ槧灏勪笉绛変簬鍒犻櫎銆?
    python3 "$repo/tests/e2e/sso_matrix.py" --phase 2 --url "$base" --insecure \
        --admin "$ADMIN_EMAIL" --admin-password "$ADMIN_PASSWORD" || return 1
}

cap_metadata_run() {
    local base=$1

    say "鍚姩瀹樻柟 metadata-server"
    compose --profile metadata up -d --wait --wait-timeout 150 cloudfile-metadata || return 1

    say "灞炴€?鏍囩楠屾敹鐭╅樀"
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

# 瀛樺偍闂ㄧ鐙湁鐨勪袱鐐癸紝鍏跺畠鑳藉姏閮戒笉闇€瑕侊細
#
#   1. GC/FSCK/杩佺Щ鏄涓绘満渚?CLI 琛屼负锛屼笉缁忚繃 HTTP锛宻torage_matrix.py 瑕嗙洊涓嶅埌锛?
#      鍙兘鐢?`compose exec`/`compose run` 鐩存帴椹卞姩銆?
#   2. 杩佺Щ蹇呴』鍋滄湇銆備笉鑳藉彧鏉€瀹瑰櫒鍐呯殑 seaf-server/fileserver 杩涚▼鈥斺€?
#      start.py 鐨?watch_controller 姣?5 绉掓鏌ヤ竴娆℃帶鍒跺櫒锛岃繛缁?4 娆?
#      (20 绉? 鎵句笉鍒板氨浼氭潃鎺夋暣涓鍣紝杩佺Щ涓€鎱㈠氨浼氳窡杩欎釜鍐呴儴鐪嬮棬鐙楁挒杞︺€?
#      鏀规垚鍋滄暣涓?cloudfile 瀹瑰櫒銆佺敤鍚屼竴浠?/shared 鍗疯窇涓€娆℃€у鍣ㄥ仛杩佺Щ锛?
#      鍐嶉噸鍚€斺€斾笉缁欑湅闂ㄧ嫍浠讳綍瑙傚療绐楀彛銆?
cap_storage_run() {
    local base=$1 repo_id

    say "鍚姩 MinIO"
    compose --profile s3 up -d --wait --wait-timeout 90 minio-init || return 1

    say "闃舵 1 鈥斺€?涓婁紶骞舵牎楠岃法澶氫釜 block 鐨勬枃浠?
    python3 "$repo/tests/e2e/storage_matrix.py" --phase 1 --url "$base" --insecure \
        --admin "$ADMIN_EMAIL" --admin-password "$ADMIN_PASSWORD" \
        --state-file "$STAGE_DIR/storage-matrix-state.json" || return 1

    say "GC 涓?FSCK 瀹屾暣閬嶅巻 S3 鍚庣"
    compose exec -T cloudfile bash -c \
        '/opt/seafile/$SEAFILE_SERVER-$SEAFILE_VERSION/seaf-gc.sh --dry-run' || return 1
    compose exec -T cloudfile bash -c \
        '/opt/seafile/$SEAFILE_SERVER-$SEAFILE_VERSION/seaf-fsck.sh' || return 1

    say "淇妯″紡蹇呴』鍏堝仠鏈嶁€斺€旀湇鍔′粛鍦ㄨ繍琛屾椂搴旇鎷掔粷"
    local repair_output repair_status
    repair_output=$(compose exec -T cloudfile bash -c \
        '/opt/seafile/$SEAFILE_SERVER-$SEAFILE_VERSION/seaf-fsck.sh --repair' 2>&1)
    repair_status=$?
    if [[ $repair_status -eq 0 ]]; then
        echo "鉁?seaf-fsck.sh --repair 搴斿湪鏈嶅姟杩愯鏃惰鎷掔粷锛屽嵈杩斿洖浜?0" >&2
        return 1
    fi
    if [[ $repair_output != *'stop seaf-server and fileserver'* ]]; then
        echo "鉁?seaf-fsck.sh --repair 琚嫆缁濓紝浣嗛敊璇俊鎭笉鏄鏈熺殑閭ｆ潯锛?repair_output" >&2
        return 1
    fi
    ok "seaf-fsck.sh --repair 鍦ㄦ湇鍔¤繍琛屾椂琚纭嫆缁?

    repo_id=$(python3 -c \
        "import json;print(json.load(open('$STAGE_DIR/storage-matrix-state.json'))['repo_id'])") \
        || { echo "鉁?璇讳笉鍒?phase 1 鍐欏叆鐨?repo_id" >&2; return 1; }

    say "绂荤嚎杩佺Щ锛氬仠姝㈡暣涓?cloudfile 瀹瑰櫒"
    compose stop cloudfile || return 1

    say "浠ヤ竴娆℃€у鍣ㄦ墽琛?seaf-storage-migrate.sh锛堝叡浜悓涓€浠?/shared 鍗凤級"
    compose run --rm --no-deps --entrypoint bash cloudfile -c \
        "/etc/my_init.d/01_create_data_links.sh && /opt/seafile/\$SEAFILE_SERVER-\$SEAFILE_VERSION/seaf-storage-migrate.sh $repo_id minio" \
        || return 1

    say "閲嶅惎骞剁瓑寰呭氨缁?
    compose up -d --wait --wait-timeout 120 cloudfile || return 1

    say "闃舵 2 鈥斺€?杩佺Щ鍚庤鍐欎粛鐒舵纭?
    python3 "$repo/tests/e2e/storage_matrix.py" --phase 2 --url "$base" --insecure \
        --admin "$ADMIN_EMAIL" --admin-password "$ADMIN_PASSWORD" \
        --state-file "$STAGE_DIR/storage-matrix-state.json" || return 1

    say "杩佺Щ鍚?GC 涓?FSCK 浠嶇劧閫氳繃"
    compose exec -T cloudfile bash -c \
        '/opt/seafile/$SEAFILE_SERVER-$SEAFILE_VERSION/seaf-gc.sh --dry-run' || return 1
    compose exec -T cloudfile bash -c \
        '/opt/seafile/$SEAFILE_SERVER-$SEAFILE_VERSION/seaf-fsck.sh' || return 1
}

# 闃舵 1 瑕佸厛鎶婃爣璁扮暀绌猴紙鍏ㄩ儴鏀捐锛夋墠鑳藉缓鍑哄す鍏凤紱闃舵 2 鍐嶆妸鏍囪鎵撳紑銆?
# 涓?sso 鐨?鐩綍鍙樺皬 + 閲嶅惎"銆乻earch 鐨?鍒?provider + 閲嶅惎"鏄悓涓€涓舰鐘讹細
# 閰嶇疆鍒囨崲涓庨噸鍚湪杩欓噷鍋氾紝鐭╅樀鑷繁鍙彂 HTTP 璇锋眰銆?
cap_fileop_env() {
    cat <<EOF
CF_FILEOP_TEST_REFUSE_TOKEN=
CF_FILEOP_TEST_JOURNAL=/shared/cf-fileop-journal.log
EOF
}

cap_fileop_run() {
    local base=$1
    # 瀹瑰櫒閲岀殑 /shared 灏辨槸瀹夸富鏈虹殑 data/seafile銆?
    local journal="$STAGE_DIR/data/seafile/cf-fileop-journal.log"

    say "闃舵 1 鈥斺€?瑙傚療妯″紡锛氭瘡涓啓鍏ュ彛閮戒骇鐢熶簨瀹烇紝鎴愬姛涓€娆″彧浜х敓涓€涓?
    python3 "$repo/tests/e2e/fileop_matrix.py" --phase 1 --url "$base" --insecure \
        --admin "$ADMIN_EMAIL" --admin-password "$ADMIN_PASSWORD" \
        --journal "$journal" \
        --state-file "$STAGE_DIR/fileop-matrix-state.json" || return 1

    # 鎷掔粷鏂瑰悜鍙湁鎶婃爣璁版墦寮€鎵嶈兘娴嬪埌锛岃€屽す鍏峰繀椤诲湪鎵撳紑涔嬪墠寤哄ソ鈥斺€旀嫆缁濅竴寮€锛?
    # 寤烘爣璁拌矾寰勬湰韬氨浼氳鎷掞紝閭ｆ伆濂芥槸琚祴鎿嶄綔涔嬩竴銆?
    say "鎵撳紑鎷掔粷鏍囪骞堕噸鍚紙cf-refuse锛?
    echo 'CF_FILEOP_TEST_REFUSE_TOKEN=cf-refuse' >> "$STAGE_DIR/.env"
    compose up -d || return 1

    say "闃舵 2 鈥斺€?閫愬叆鍙ｆ嫆缁濄€侀浂浜嬪疄锛屽鍔犲弽鍚戝鐓?
    python3 "$repo/tests/e2e/fileop_matrix.py" --phase 2 --url "$base" --insecure \
        --admin "$ADMIN_EMAIL" --admin-password "$ADMIN_PASSWORD" \
        --journal "$journal" \
        --state-file "$STAGE_DIR/fileop-matrix-state.json" || return 1
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

# 涓夐樁娈靛搴斾笁娆￠厤缃彉鏇达紱search_matrix.py 鏈韩鍙彂 HTTP 璇锋眰锛屼笉纰?.env 鎴?
# 瀹瑰櫒鈥斺€旈厤缃垏鎹笌閲嶅惎缁熶竴鍦ㄨ繖閲屽仛锛屼笌 sso 鐨勭洰褰曞彉灏?閲嶅惎鏄悓涓€涓悊鐢憋細
# 鎶?鏀归厤缃細涓嶄細鐪熺殑鐢熸晥"鍜?瑙勫垯绠楀緱瀵逛笉瀵?鍒嗗紑楠岃瘉銆?
cap_search_run() {
    local base=$1

    say "鍚姩 SeaSearch 涓?Meilisearch锛堢缉鐭?SeaSearch 绱㈠紩闂撮殧鍒?10s锛?
    compose --profile search up -d --wait --wait-timeout 90 seasearch meilisearch || return 1

    say "闃舵 1 鈥斺€?榛樿璺緞锛欳F_PROVIDER_SEARCH 鐣欑┖锛岃蛋 SeaSearch"
    python3 "$repo/tests/e2e/search_matrix.py" --phase 1 --url "$base" --insecure \
        --admin "$ADMIN_EMAIL" --admin-password "$ADMIN_PASSWORD" \
        --state-file "$STAGE_DIR/search-matrix-state.json" || return 1

    say "鍒囧埌 CF_PROVIDER_SEARCH=meilisearch 骞堕噸鍚?
    echo 'CF_PROVIDER_SEARCH=meilisearch' >> "$STAGE_DIR/.env"
    compose up -d --wait --wait-timeout 120 cloudfile || return 1

    say "鎵嬪姩璺戜竴杞储寮曞櫒锛堜笉绛夊畾鏃讹紝鍥炲～鍒囨崲鍓嶅凡瀛樺湪鐨勬彁浜わ級"
    compose exec -T cloudfile bash -c \
        '/opt/seafile/$SEAFILE_SERVER-$SEAFILE_VERSION/seahub.sh python-env python3 /opt/seafile/$SEAFILE_SERVER-$SEAFILE_VERSION/seahub/manage.py cf_worker --once' \
        || return 1

    say "闃舵 2 鈥斺€?Meilisearch 璺緞锛岄獙璇佸洖濉?
    python3 "$repo/tests/e2e/search_matrix.py" --phase 2 --url "$base" --insecure \
        --admin "$ADMIN_EMAIL" --admin-password "$ADMIN_PASSWORD" \
        --state-file "$STAGE_DIR/search-matrix-state.json" || return 1

    say "鍏抽棴 CF_ENABLE_SEARCH 骞堕噸鍚紝纭鎭㈠鍘熺敓琛屼负"
    sed -i.bak "s|^CF_ENABLE_SEARCH=.*|CF_ENABLE_SEARCH=false|" "$STAGE_DIR/.env" \
        && rm -f "$STAGE_DIR/.env.bak"
    compose up -d --wait --wait-timeout 120 cloudfile || return 1

    say "闃舵 3 鈥斺€?鍏抽棴鍚庢仮澶嶅師鐢?403"
    python3 "$repo/tests/e2e/search_matrix.py" --phase 3 --url "$base" --insecure \
        --admin "$ADMIN_EMAIL" --admin-password "$ADMIN_PASSWORD" \
        --state-file "$STAGE_DIR/search-matrix-state.json" || return 1
}

stage_compose() {
    # 鍏堟妸杩樻椿鐫€鐨勬爤鎷嗘帀锛屽啀鍔ㄧ洰褰曘€?
    #
    # 姣忎釜鏈嶅姟鐨勬暟鎹兘鏄?./data/... 鐨?bind mount锛屽氨鍦?STAGE_DIR 閲岄潰銆傜洿鎺?
    # rm -rf 浼氬湪瀹瑰櫒浠嶆寔鏈夎繖浜涙寕杞芥椂鎶婂涓荤洰褰曟娊璧帮細db 瀹瑰櫒涓嶄細琚噸寤猴紝浜庢槸
    # 缁х画鐢ㄧ潃鏃у簱锛岃€?seafile-data 宸茬粡绌轰簡鈥斺€攕etup 浠ヤ负鏄叏鏂板畨瑁咃紝鎾炰笂涓€涓?
    # 宸茬粡寤哄ソ schema 鐨勬暟鎹簱锛岄€€鍑?1銆?
    #
    # 琛ㄩ潰鐥囩姸鍙湁涓€涓?Caddy 502锛屽拰鐪熷洜闅旂潃鍗佷竾鍏崈閲屻€傜浜屾璺戞湰鍦伴棬绂佸氨鏄?
    # 杩欎箞鎸傜殑锛岃€岀涓€娆¤窇娌′簨绾补鍥犱负閭ｆ椂娌℃湁瀛橀噺鏍堛€?
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
            || fail "$sw 涓嶅湪 .env.example 閲屸€斺€斿紑鍏虫竻鍗曚笉鍚屾"
        sed -i.bak "s|^$sw=.*|$sw=true|" "$STAGE_DIR/.env" && rm -f "$STAGE_DIR/.env.bak"
        # 纭鐪熺殑鍐欒繘鍘讳簡銆傚紑鐫€寮€鍏宠窇鍗村叾瀹炴病寮€锛屽叏缁跨殑鐭╅樀姣棤鎰忎箟鈥斺€?
        # 鑰岄偅绉嶅け璐ユ槸瀹屽叏闈欓粯鐨勩€?
        grep -q "^$sw=true$" "$STAGE_DIR/.env" || fail "$sw 鏈兘缃负 true"
        ok "$sw=true"
    done

    # 鑳藉姏鑷繁鐨勯厤缃€傝拷鍔犺€屼笉鏄浛鎹細鍚庡啓鐨勫悓鍚嶉敭瑕嗙洊鍏堝啓鐨勶紝鑰?JSON 鍊奸噷鐨?
    # 寮曞彿鍜屾柟鎷彿涓嶅繀鍐嶅幓鍜?sed 琛ㄨ揪寮忔悘鏂椼€?
    if [[ -n $CAP_NAME ]] && declare -F "cap_${CAP_NAME}_env" >/dev/null; then
        local line
        while IFS= read -r line; do
            [[ -z $line ]] && continue
            echo "$line" >> "$STAGE_DIR/.env"
            # 鍚屼笂锛氶厤缃病鍐欒繘鍘昏€岄棬绂佸叏缁匡紝鏄渶娌℃湁浠峰€肩殑涓€绉嶇豢銆?
            grep -qxF "$line" "$STAGE_DIR/.env" || fail "鏈兘鍐欏叆 .env锛?{line%%=*}"
            ok "${line%%=*} 宸查厤缃?
        done < <("cap_${CAP_NAME}_env")
    fi
}

compose() { docker compose -p "$PROJECT" --project-directory "$STAGE_DIR" "$@"; }

up() {
    need_docker
    docker image inspect "$IMAGE" >/dev/null 2>&1 \
        || fail "鏈湴娌℃湁闀滃儚 ${IMAGE}锛屽厛璺?build"
    if [[ -n $ENABLE_SWITCHES ]]; then
        say "鍚姩锛堝紑鍚細${ENABLE_SWITCHES}锛?
    else
        say "鍚姩锛堝紑鍏冲叏鍏筹級"
    fi
    stage_compose
    compose up -d || fail "compose 鍚姩澶辫触"
    compose ps
}

base_url() {
    # 443 鏃朵笉甯︾鍙ｏ紝璁?URL 涓?seahub 鐢熸垚鐨勭粷瀵归摼鎺ュ畬鍏ㄤ竴鑷?
    local base="https://127.0.0.1"
    [[ $HTTPS_PORT != 443 ]] && base="https://127.0.0.1:$HTTPS_PORT"
    echo "$base"
}

e2e() {
    local base; base=$(base_url)
    say "鍘熺敓 CE 鍐掔儫 @ $base"
    python3 "$repo/tests/e2e/smoke.py" --url "$base" --insecure \
        --admin "$ADMIN_EMAIL" --admin-password "$ADMIN_PASSWORD" || return 1

    say "鎵╁睍鐐瑰凡瑁呭ソ锛屼絾娌℃湁鑳藉姏鍚敤"
    python3 "$repo/tests/e2e/baseline.py" --url "$base" --insecure \
        --admin "$ADMIN_EMAIL" --admin-password "$ADMIN_PASSWORD" || return 1
}

# 鑳藉姏闂ㄧ锛氬紑鐫€鑷繁鐨勫紑鍏宠捣鏍堬紝鍏堣瘉鏄庢病鎶婂師鐢熷姛鑳藉紕鍧忥紝鍐嶈窇鑳藉姏鑷繁鐨勭敤渚嬨€?
#
# 椤哄簭鏄湁鎰忕殑锛氬啋鐑熷厛鎸傜殑璇濓紝鑳藉姏鐭╅樀鐨勫け璐ヤ俊鎭細鎸囧悜涓€鍫嗕笅娓哥棁鐘讹紝
# 鎺掓煡鏃跺垎涓嶆竻"瑙勫垯鎷﹂敊浜?杩樻槸"鏈嶅姟鍘嬫牴娌¤捣鏉?銆備笌 <鑳藉姏>-e2e.yml 鍚屽簭銆?
capability_e2e() {
    local name=$1 switch test_rel entry
    for entry in "${CAPABILITIES[@]}"; do
        IFS='|' read -r cap switch test_rel <<< "$entry"
        [[ $cap == "$name" ]] && break
        cap=''
    done
    [[ -n ${cap:-} ]] || fail "鏈煡鑳藉姏锛?{name}锛堝凡鐧昏锛?(printf '%s ' "${CAPABILITIES[@]%%|*}"))"
    [[ -f $repo/$test_rel ]] || fail "鎵句笉鍒?$test_rel"

    ENABLE_SWITCHES=$switch
    CAP_NAME=$name
    up

    local base; base=$(base_url)
    say "鍘熺敓鍔熻兘鏈鐮村潖锛?switch 宸插紑鍚級"
    python3 "$repo/tests/e2e/smoke.py" --url "$base" --insecure \
        --admin "$ADMIN_EMAIL" --admin-password "$ADMIN_PASSWORD" || return 1

    say "鑳藉姏闂ㄧ锛?name"
    if declare -F "cap_${name}_run" >/dev/null; then
        "cap_${name}_run" "$base" || return 1
    else
        python3 "$repo/$test_rel" --url "$base" --insecure \
            --admin "$ADMIN_EMAIL" --admin-password "$ADMIN_PASSWORD" || return 1
    fi
}

dump_logs() {
    say "瀹瑰櫒鏃ュ織锛堝け璐ヨ瘖鏂級"
    compose ps -a || true
    compose logs --tail 200 cloudfile || true
    compose exec -T cloudfile tail -n 120 /opt/seafile/logs/seahub.log 2>/dev/null || true
    compose exec -T cloudfile tail -n 120 /opt/seafile/logs/seafile.log 2>/dev/null || true
}

# 鏋勫缓鏍戣涓柇杩囥€佹垨鎹㈣繃鏋舵瀯涔嬪悗蹇呴』娓呫€?
#
# 韪╄繃涓€娆★細amd64 鏋勫缓琚?kill 鍚庢畫鐣欑殑 src/ 琚笅涓€娆?arm64 鏋勫缓澶嶇敤锛寁ala 鐢熸垚鐨?
# repo.c锛堜笂娓告槸**鎻愪氦杩涗粨搴?*鐨勶級鐘舵€侀敊涔憋紝缂栬瘧鎶ヤ竴鍫?"redefinition of ..."銆?
# 鐥囩姸绂诲師鍥犲緢杩滐紝鎵€浠ュ畞鍙彁渚涗竴鏉℃槑纭殑鍛戒护銆?
distclean() {
    say "娓呯悊鏋勫缓鏍?
    rm -rf "$repo/build/cloudfile_14.0/src" \
           "$repo/build/cloudfile_14.0/seafile-server" \
           "$repo"/build/cloudfile_14.0/seafile-server-*
    ok "鏋勫缓鏍戝凡娓呯┖锛堜笅娆℃瀯寤轰細閲嶆柊 clone锛屾參浣嗗共鍑€锛?
}

clean() {
    say "娓呯悊鏈湴鏍?
    [[ -d $STAGE_DIR ]] && compose down -v 2>/dev/null
    rm -rf "$STAGE_DIR"
    ok "宸叉竻鐞嗭紙闀滃儚淇濈暀锛屽垹闄ょ敤 docker rmi ${IMAGE}锛?
}

case "${1:-all}" in
    preflight) preflight ;;
    build)     preflight; build_dist; build_image ;;
    image)     build_image ;;
    up)        up ;;
    e2e)       e2e || { dump_logs; fail "E2E 鏈€氳繃"; } ;;
    clean)     clean ;;
    distclean) clean; distclean ;;
    # 鑳藉姏闂ㄧ銆傞暅鍍忓繀椤诲凡缁忓湪锛堝厛璺?build锛夛紝鍥犱负鑳藉姏浠ｇ爜鏉ヨ嚜琚瀯寤虹殑閭ｄ釜
    # 鍒嗘敮锛屼笉鏄繍琛屾椂寮€鍏宠兘鍙樺嚭鏉ョ殑銆?
    cap|capability)
        [[ $# -ge 2 ]] || fail "鐢ㄦ硶锛?0 cap <鑳藉姏鍚?锛堝凡鐧昏锛?(printf '%s ' "${CAPABILITIES[@]%%|*}"))"
        if capability_e2e "$2"; then
            say "鑳藉姏闂ㄧ閫氳繃锛?2"
            clean
        else
            dump_logs
            echo
            echo "鏍堜粛鍦ㄨ繍琛岋紝鏂逛究浣犵户缁帓鏌ワ細" >&2
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
            say "鍏ㄩ儴閫氳繃鈥斺€斿彲浠ユ帹浜?
            clean
        else
            dump_logs
            echo
            echo "鏍堜粛鍦ㄨ繍琛岋紝鏂逛究浣犵户缁帓鏌ワ細" >&2
            echo "  docker compose -p $PROJECT --project-directory $STAGE_DIR logs -f cloudfile" >&2
            echo "  ./tools/verify-local.sh clean   # 鏌ュ畬娓呯悊" >&2
            exit 1
        fi
        ;;
    *) fail "鏈煡闃舵锛?1锛坧reflight|build|image|up|e2e|clean|distclean|all锛? ;;
esac
