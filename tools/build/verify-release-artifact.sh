#!/bin/bash

# Reject a release tree assembled from incomplete or stale component artifacts.
# Full and incremental builds must satisfy the same runtime contract.

set -euo pipefail

if [[ $# != 1 ]]; then
    echo "usage: $0 <seafile-server-release-dir>" >&2
    exit 2
fi

dist=$1
stats=$dist/seahub/frontend/webpack-stats.pro.json
assets=$dist/seahub/media/assets/frontend
build_info=$dist/cloudfile-build-info.txt

[[ -d $assets && -f $stats && -f $build_info ]] || {
    echo "release is missing frontend assets, webpack stats, or build info" >&2
    exit 1
}

find "$dist/seahub/locale" -type f -path '*/LC_MESSAGES/*.mo' -print -quit \
    | grep -q . || {
        echo "release has no compiled first-party locale" >&2
        exit 1
    }

for component in cloudfile-docker seafile-server seahub; do
    grep -Eq "^${component}: [0-9a-f]{40}$" "$build_info" || {
        echo "release build info has no immutable ${component} commit" >&2
        exit 1
    }
done

python3 - "$stats" "$assets" <<'PY'
import json
import pathlib
import sys

stats_path = pathlib.Path(sys.argv[1])
assets_root = pathlib.Path(sys.argv[2])
try:
    payload = json.loads(stats_path.read_text())
except (OSError, json.JSONDecodeError) as exc:
    raise SystemExit(f"invalid webpack stats: {exc}")

if payload.get("status") != "done":
    raise SystemExit("webpack stats status is not done")
assets = payload.get("assets")
if not isinstance(assets, dict) or not assets:
    raise SystemExit("webpack stats contains no assets")

missing = []
for value in assets.values():
    name = value.get("name") if isinstance(value, dict) else None
    path = pathlib.PurePosixPath(name) if name else None
    if not path or path.is_absolute() or ".." in path.parts:
        raise SystemExit(f"invalid webpack asset entry: {value!r}")
    if not (assets_root / name).is_file():
        missing.append(name)
if missing:
    raise SystemExit("webpack stats references missing assets: " + ", ".join(missing[:5]))
PY

echo "release artifact verified: $dist"
