#!/bin/bash

set -euo pipefail

repo_root=$(cd "$(dirname "$0")/../.." && pwd)
verify=$repo_root/tools/verify-release-artifact.sh
fixture=$(mktemp -d)
trap 'rm -rf "$fixture"' EXIT

dist=$fixture/seafile-server-test
mkdir -p "$dist/seahub/frontend" \
         "$dist/seahub/media/assets/frontend/static/js" \
         "$dist/seahub/locale/zh_CN/LC_MESSAGES"
printf 'bundle\n' > "$dist/seahub/media/assets/frontend/static/js/app.123.js"
printf 'messages\n' > "$dist/seahub/locale/zh_CN/LC_MESSAGES/django.mo"
cat > "$dist/seahub/frontend/webpack-stats.pro.json" <<'JSON'
{"status":"done","assets":{"static/js/app.123.js":{"name":"static/js/app.123.js"}}}
JSON
cat > "$dist/cloudfile-build-info.txt" <<'INFO'
cloudfile-docker: 1111111111111111111111111111111111111111
seafile-server: 2222222222222222222222222222222222222222
seahub: 3333333333333333333333333333333333333333
INFO

"$verify" "$dist" >/dev/null

rm "$dist/seahub/media/assets/frontend/static/js/app.123.js"
if "$verify" "$dist" >/dev/null 2>&1; then
    echo "release verifier accepted a missing webpack asset" >&2
    exit 1
fi
