#!/usr/bin/env bash
# Compatibility name; the full dev builder is the single implementation.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
exec bash "$here/../cloudfile_14.0/cloudfile-build.sh" "$@"
