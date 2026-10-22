#!/usr/bin/env bash
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
exec bash "$here/../../image/cloudfile_14.0/docker-build.sh" "$@"
