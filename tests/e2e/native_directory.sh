#!/usr/bin/env bash
# Dedicated native fixture only. No existing deployment or database is touched.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
workspace=$(cd "$here/../../.." && pwd)
backend=${CF_NATIVE_BACKEND:-$workspace/cloudfile-docker/build/cloudfile_14.0/cloudfile-backend}
# Explicit worktree roots keep native and Hub code from drifting during review.
hub_root=${CF_NATIVE_HUB_ROOT:-$workspace/cloudfile-hub}
server_root=${CF_NATIVE_SERVER_ROOT:-$workspace/cloudfile-server}
image=${CF_NATIVE_BASE_IMAGE:-cloudfile-build-base:ce14-v2}
server_bin=${CF_NATIVE_SERVER_BINARY:?Set CF_NATIVE_SERVER_BINARY to the newly built seaf-server}
acl_lib=${CF_NATIVE_ACL_LIB_DIR:?Set CF_NATIVE_ACL_LIB_DIR to its shared library directory}
test -x "$server_bin"
test -x "$backend/fileserver/fileserver"
lab=${CF_NATIVE_REPORT_DIR:-$(mktemp -d /tmp/cf-native-directory.XXXXXX)}
mkdir -p "$lab"
lab=$(cd "$lab" && pwd)
suffix="$(date +%s)-$$"
network="cf-native-directory-$suffix"
db="cf-native-db-$suffix"
cache="cf-native-redis-$suffix"
runtime="cf-native-runtime-$suffix"
cleanup() {
    result=$?
    if [[ "$result" != 0 && "${CF_NATIVE_KEEP_ON_FAILURE:-0}" = 1 ]]; then
        printf 'Failed fixture retained: %s (network %s, evidence %s)\n' "$runtime" "$network" "$lab" >&2
        return
    fi
    docker rm -f "$runtime" "$cache" "$db" >/dev/null 2>&1 || true
    docker network rm "$network" >/dev/null 2>&1 || true
}
trap cleanup EXIT
docker network create "$network" >/dev/null
docker run --rm -d --name "$db" --network "$network" -e MYSQL_ALLOW_EMPTY_PASSWORD=yes mysql:8 >/dev/null
docker run --rm -d --name "$cache" --network "$network" redis:7-alpine >/dev/null
docker run --rm -d --name "$runtime" --network "$network" \
    -e CF_NATIVE_DB_HOST="$db" -e CF_NATIVE_REDIS_HOST="$cache" \
    -e LD_LIBRARY_PATH=/acl:/backend/seafile-server/seafile/lib:/backend/seafile-server/seafile/lib/seafile \
    -e JWT_PRIVATE_KEY=isolated-fixture-only-not-production \
    -e SEAFILE_MYSQL_DB_HOST="$db" -e SEAFILE_MYSQL_DB_PORT=3306 \
    -e SEAFILE_MYSQL_DB_USER=cf_lab -e SEAFILE_MYSQL_DB_PASSWORD=isolated-fixture-only \
    -e SEAFILE_MYSQL_DB_CCNET_DB_NAME=cf_lab_ccnet -e SEAFILE_MYSQL_DB_SEAFILE_DB_NAME=cf_lab_seafile \
    -v "$server_bin:/native/seaf-server:ro" -v "$acl_lib:/acl:ro" -v "$lab:/lab" -v "$backend:/backend:ro" \
    -v "$hub_root:/hub:ro" -v "$server_root:/server:ro" \
    -v "$here:/tests:ro" "$image" sleep infinity >/dev/null
ready=false
for attempt in $(seq 1 90); do
    if docker exec "$db" mysqladmin -h127.0.0.1 ping --silent >/dev/null 2>&1; then ready=true; break; fi
    sleep 1
done
test "$ready" = true
docker exec "$runtime" python3 -m pip install --break-system-packages redis django==4.2.24 requests-oauthlib cryptography > "$lab/dependencies.log" 2>&1
docker exec "$runtime" python3 /tests/native_editing_bootstrap.py
docker exec -d "$runtime" /native/seaf-server \
    -c /lab/ccnet -d /lab/seafile-data -F /lab/conf -f -l /lab/seafile.log -p /lab/seafile-data
ready=false
for attempt in $(seq 1 30); do
    if docker exec "$runtime" test -S /lab/seafile-data/seafile.sock; then ready=true; break; fi
    sleep 1
done
test "$ready" = true
docker exec -d "$runtime" /backend/fileserver/fileserver \
    -F /lab/conf -d /lab/seafile-data -l /lab/fileserver.log -p /lab/seafile-data
ready=false
for attempt in $(seq 1 30); do
    if docker exec "$runtime" python3 -c 'import urllib.request; urllib.request.urlopen("http://127.0.0.1:8082/protocol-version",timeout=1)' >/dev/null 2>&1; then ready=true; break; fi
    sleep 1
done
test "$ready" = true
docker exec "$runtime" python3 /tests/native_directory_e2e.py | tee "$lab/test.log"
printf 'Directory native evidence: %s/directory-result.json\n' "$lab"
