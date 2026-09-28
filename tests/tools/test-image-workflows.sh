#!/bin/bash

set -e

repo_root=$(cd "$(dirname "$0")/../.." && pwd)
failed=0

while IFS= read -r workflow; do
    if ! grep -Fq './base-build.sh' "$workflow"; then
        echo "$(basename "$workflow"): docker-build.sh is used without base-build.sh" >&2
        failed=1
    fi
done < <(grep -lF './docker-build.sh' "$repo_root"/.github/workflows/*.yml)

exit "$failed"
