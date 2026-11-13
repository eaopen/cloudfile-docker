#!/usr/bin/env bash
# Disposable protocol acceptance; never connects to an existing database or volume.
set -euo pipefail
root=$(cd "$(dirname "$0")/../../.." && pwd)
version=${1:?usage: run-file-protection.sh version}
package="$root/build/cloudfile_14.0/seafile-server-$version"
name="cf-protection-$(date +%s)-$$"
evidence="$root/build/cloudfile_14.0/test-results/protection/$name"
base=${CF_BASE_IMAGE:-cloudfile-build-base:ce14-v2}
bash "$root/tools/build/verify-release-artifact.sh" "$package"
python3 - "$root/build/cloudfile_14.0/build-receipt.json" "$package/cloudfile-build-info.txt" "$version" <<'PYCODE'
import json, pathlib, sys
receipt = json.loads(pathlib.Path(sys.argv[1]).read_text())
info = dict(line.split(': ', 1) for line in pathlib.Path(sys.argv[2]).read_text().splitlines() if ': ' in line)
assert receipt['version'] == sys.argv[3], 'receipt version mismatch'
lock = receipt['lock']
for name, sha in [('cloudfile-docker', lock['docker_commit']),
                  ('seafile-server', lock['sources']['seafile-server']['ref']),
                  ('seahub', lock['sources']['seahub']['ref'])]:
    assert info.get(name) == sha, 'package/receipt mismatch: ' + name
PYCODE
mkdir -p "$evidence"
# Keep the package source receipt and test revision distinct.
cp "$root/build/cloudfile_14.0/build-receipt.json" "$evidence/build-receipt.json"
git -C "$root" rev-parse HEAD > "$evidence/test-revision.txt"
git -C "$root" status --porcelain >> "$evidence/test-revision.txt"
docker image inspect "$base" --format '{{.Id}} {{.Architecture}}' > "$evidence/platform.txt"
cleanup() {
  docker rm -f "$name-probe" "$name-db" >/dev/null 2>&1 || true
  docker network rm "$name" >/dev/null 2>&1 || true
}
trap cleanup EXIT
docker network create "$name" >/dev/null
docker run -d --name "$name-db" --network "$name" --network-alias db \
  -e MARIADB_ROOT_PASSWORD=isolated-protection-test mariadb:10.11 >/dev/null
for attempt in $(seq 1 60); do
  if docker exec "$name-db" mariadb-admin ping --protocol=tcp -h127.0.0.1 -uroot -pisolated-protection-test --silent >/dev/null 2>&1; then break; fi
  if [ "$attempt" = 60 ]; then docker logs "$name-db"; exit 1; fi
  sleep 1
done
set +e
docker run --rm --name "$name-probe" --network "$name" --pull=never \
  -v "$package:/package:ro" -v "$root/tests/e2e/full:/tests:ro" -v "$evidence:/evidence" \
  -e CF_TEST_FILE_PROTECTION=1 -e CF_TEST_PROTECTION_EXTENDED=1 \
  -e CF_NATIVE_TEST_PACKAGE=/package -e CF_PROTECTION_REPORT=/evidence/acceptance.json \
  -e CF_PROTECTION_PERF_ROWS="${CF_PROTECTION_PERF_ROWS:-1000}" \
  -e PYTHONPATH=/package/seahub:/package/seahub/thirdpart:/package/seafile/lib/python3/site-packages \
  -e LD_LIBRARY_PATH=/package/seafile/lib \
  "$base" python3 /tests/file_protection_native.py 2>&1 | tee "$evidence/probe.log"

result=${PIPESTATUS[0]}
set -e
status=failed
if [ "$result" = 0 ]; then status=passed; fi
python3 "$root/build/cloudfile_14.0/build_receipt.py" test \
  "$root/build/cloudfile_14.0/build-receipt.json" file_protection "$status" \
  --command "bash tests/e2e/full/run-file-protection.sh $version" >/dev/null
exit "$result"
