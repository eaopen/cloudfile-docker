#!/usr/bin/env bash
# Required focused tests against precisely the checked-out Server receipt SHA.
set -euo pipefail
receipt=${1:?build receipt required}
server=${2:?Server source required}
here=$(cd "$(dirname "$0")" && pwd)
tool="$here/../seafile_14.0/build_receipt.py"
export CF_AUTO_STORAGE_CASES="$here/../../docs/features/automatic-local-storage-cases.json"
expected=$(python3 "$here/../seafile_14.0/source_manifest.py" "$receipt" ref seafile-server)
[[ $(git -C "$server" rev-parse HEAD) == "$expected" ]] || exit 2
logs="$here/test-results"
mkdir -p "$logs"
run_test() {
    local name=$1 command=$2 status=passed
    if ! (cd "$server" && bash -euo pipefail -c "$command") >"$logs/$name.log" 2>&1; then
        status=failed
    fi
    cat "$logs/$name.log"
    digest=$(sha256sum "$logs/$name.log" | cut -d' ' -f1)
    python3 "$tool" test "$receipt" "$name" "$status" --command "$command" --log-sha256 "$digest" >/dev/null
    [[ $status == passed ]]
}
if [[ ${CF_TEST_BIND_MOUNTS:-0} == 1 ]]; then
    run_test bind_mounts 'cd fileserver && CF_TEST_BIND_MOUNTS=1 go test -v ./objstore/... -run TestLocalAtomicBindMount -count=1'
else
    run_test local_storage 'bash tests/local_storage/run.sh'
    run_test objstore 'cd fileserver && go test -v ./objstore/... -count=1'
fi
