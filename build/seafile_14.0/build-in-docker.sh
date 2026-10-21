#!/usr/bin/env bash
# Compatibility name; resolve dev once using the canonical receipt builder.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
exec bash "$here/../cloudfile_14.0/build-in-docker.sh" "$@"
