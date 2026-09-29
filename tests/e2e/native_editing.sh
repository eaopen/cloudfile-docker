#!/usr/bin/env bash
# Dedicated native fixture only. No existing deployment or database is touched.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
workspace=$(cd "$here/../../.." && pwd)
backend=${CF_NATIVE_BACKEND:-$workspace/cloudfile-docker/build/cloudfile_14.0/cloudfile-backend}
image=${CF_NATIVE_BASE_IMAGE:-cloudfile-build-base:ce14-v2}
test -x "$backend/seafile-server/seafile/bin/seaf-server"
test -x "$backend/fileserver/fileserver"
lab=${CF_NATIVE_REPORT_DIR:-$(mktemp -d /tmp/cf-native-editing.XXXXXX)}
mkdir -p "$lab"
lab=$(cd "$lab" && pwd)
suffix="$(date +%s)-$$"
network="cf-native-edit-$suffix"
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
    -e LD_LIBRARY_PATH=/backend/seafile-server/seafile/lib:/backend/seafile-server/seafile/lib/seafile \
    -e JWT_PRIVATE_KEY=isolated-fixture-only-not-production \
    -e SEAFILE_MYSQL_DB_HOST="$db" -e SEAFILE_MYSQL_DB_PORT=3306 \
    -e SEAFILE_MYSQL_DB_USER=cf_lab -e SEAFILE_MYSQL_DB_PASSWORD=isolated-fixture-only \
    -e SEAFILE_MYSQL_DB_CCNET_DB_NAME=cf_lab_ccnet -e SEAFILE_MYSQL_DB_SEAFILE_DB_NAME=cf_lab_seafile \
    -v "$lab:/lab" -v "$backend:/backend:ro" \
    -v "$workspace/cloudfile-hub:/hub:ro" -v "$workspace/cloudfile-server:/server:ro" \
    -v "$here:/tests:ro" "$image" sleep infinity >/dev/null
ready=false
for attempt in $(seq 1 90); do
    if docker exec "$db" mysqladmin ping --silent >/dev/null 2>&1; then ready=true; break; fi
    sleep 1
done
test "$ready" = true
docker exec "$runtime" python3 -m pip install --break-system-packages redis django==4.2.24 requests-oauthlib > "$lab/dependencies.log" 2>&1
docker exec "$runtime" python3 /tests/native_editing_bootstrap.py
docker exec -d "$runtime" /backend/seafile-server/seafile/bin/seaf-server \
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
cp "$backend/build-info.txt" "$lab/build-info.txt"
docker exec "$runtime" python3 /tests/native_editing_e2e.py | tee "$lab/test.log"
printf 'Native evidence: %s/native-result.json\n' "$lab"
