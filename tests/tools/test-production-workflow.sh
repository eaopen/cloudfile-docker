#!/bin/bash

set -euo pipefail

repo_root=$(cd "$(dirname "$0")/../.." && pwd)
workflow=$repo_root/.github/workflows/prod.yml
planner=$repo_root/tools/release-build-plan.sh

require_text() {
    local file=$1 text=$2
    if ! grep -Fq -- "$text" "$file"; then
        echo "missing incremental release contract in $(basename "$file"): $text" >&2
        exit 1
    fi
}

if grep -Eq '^[[:space:]]+push:' "$workflow"; then
    echo 'production workflow must not run for every push' >&2
    exit 1
fi
require_text "$workflow" 'workflow_dispatch:'
require_text "$workflow" 'cancel-in-progress: true'
require_text "$workflow" "if: inputs.mode == 'full'"
require_text "$workflow" 'Build full release package'
require_text "$workflow" 'CF_BUILD_TARGET: backend'
require_text "$workflow" 'CF_BUILD_TARGET: frontend'
require_text "$workflow" 'CF_BUILD_TARGET: package'
require_text "$workflow" 'cf-backend-${{ needs.plan.outputs.backend_key }}'
require_text "$workflow" 'cf-frontend-${{ needs.plan.outputs.frontend_key }}'
require_text "$workflow" 'cf-package-tools-${{ needs.plan.outputs.package_key }}'
require_text "$planner" 'server_sha='
require_text "$planner" 'package_key='
require_text "$planner" 'server-inputs='
require_text "$planner" 'hub-inputs='
require_text "$planner" "':(glob)**/static/**'"

# Exercise the content boundaries with two tiny repositories. API/SQL-only
# edits must not compile either component; frontend and C edits invalidate only
# their own component.
fixture=$(mktemp -d)
trap 'rm -rf "$fixture"' EXIT
server=$fixture/cloudfile-server
hub=$fixture/cloudfile-hub
mkdir -p "$server/python" "$server/common" "$server/scripts/sql" \
         "$hub/frontend" "$hub/cloudfile_ext"

printf 'python baseline\n' > "$server/python/module.py"
printf 'int baseline;\n' > "$server/common/module.c"
printf 'CREATE TABLE baseline;\n' > "$server/scripts/sql/schema.sql"
printf 'frontend baseline\n' > "$hub/frontend/app.js"
printf 'api baseline\n' > "$hub/cloudfile_ext/api.py"
printf 'Django==5.2\n' > "$hub/requirements.txt"

for repo in "$server" "$hub"; do
    git -C "$repo" init -q
    git -C "$repo" config user.name CloudFile-Test
    git -C "$repo" config user.email cloudfile-test@example.invalid
    git -C "$repo" add .
    git -C "$repo" commit -qm baseline
done

plan_value() {
    local name=$1
    "$planner" 14.0.0-cf.0 "$server" "$hub" | sed -n "s/^${name}=//p"
}

backend_0=$(plan_value backend_key)
frontend_0=$(plan_value frontend_key)

printf 'api two-line edit\n' >> "$hub/cloudfile_ext/api.py"
git -C "$hub" commit -qam api-only
[[ $(plan_value backend_key) == "$backend_0" ]]
[[ $(plan_value frontend_key) == "$frontend_0" ]]

printf 'frontend two-line edit\n' >> "$hub/frontend/app.js"
git -C "$hub" commit -qam frontend-only
frontend_1=$(plan_value frontend_key)
[[ $frontend_1 != "$frontend_0" ]]
[[ $(plan_value backend_key) == "$backend_0" ]]

printf 'ALTER TABLE baseline;\n' >> "$server/scripts/sql/schema.sql"
git -C "$server" commit -qam sql-only
[[ $(plan_value backend_key) == "$backend_0" ]]
[[ $(plan_value frontend_key) == "$frontend_1" ]]

printf 'int changed;\n' >> "$server/common/module.c"
git -C "$server" commit -qam c-only
[[ $(plan_value backend_key) != "$backend_0" ]]
[[ $(plan_value frontend_key) == "$frontend_1" ]]
