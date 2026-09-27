#!/usr/bin/env bash
set -euo pipefail

# The client is bidirectional. The source must be a dedicated local staging
# copy; keeping state on a separate volume makes interrupted runs resumable.
source_dir=/migration/source
state_dir=/migration/state
control_dir=/migration/control
conf_dir="${state_dir}/ccnet"
token_file=/run/secrets/cf_migration_token

for name in CF_MIGRATION_SERVER_URL CF_MIGRATION_REPO_ID CF_MIGRATION_USER CF_MIGRATION_SOURCE_HOST; do
    if [[ -z "${!name:-}" ]]; then
        echo "Missing ${name}" >&2
        exit 2
    fi
done
if [[ ! "${CF_MIGRATION_REPO_ID}" =~ ^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$ ]]; then
    echo 'CF_MIGRATION_REPO_ID must be a repository UUID' >&2
    exit 2
fi
if [[ ! "${CF_MIGRATION_STATUS_INTERVAL:-60}" =~ ^[1-9][0-9]*$ ]]; then
    echo 'CF_MIGRATION_STATUS_INTERVAL must be a positive integer' >&2
    exit 2
fi
if [[ ! -d "$source_dir" || ! -r "$source_dir" || ! -w "$source_dir" ]]; then
    echo "Staging directory must be readable and writable: ${source_dir}" >&2
    exit 2
fi
if [[ -z "$(find "$source_dir" -mindepth 1 -maxdepth 1 -print -quit)" ]]; then
    echo "Staging directory is empty: ${source_dir}" >&2
    exit 2
fi
if [[ ! -s "$token_file" ]]; then
    echo "Missing nonempty token file: ${token_file}" >&2
    exit 2
fi
mkdir -p "$state_dir"
mkdir -p "$control_dir"

# The control volume is shared across every migration invocation; keep the
# lock separate from per-repository client state so changing state cannot
# accidentally permit concurrent imports.
exec 9>"${control_dir}/migration.lock"
if ! flock -n 9; then
    echo 'Another repository migration is already running' >&2
    exit 2
fi
# Do not leak the lock fd into the daemon or its child processes.
cli() {
    seaf-cli "$@" 9>&-
}
repo_file="${state_dir}/repo-id"
if [[ -s "$repo_file" && "$(<"$repo_file")" != "$CF_MIGRATION_REPO_ID" ]]; then
    echo "State belongs to a different repository: $(<"$repo_file")" >&2
    exit 2
fi
if [[ ! -e "$repo_file" ]]; then
    printf '%s\n' "$CF_MIGRATION_REPO_ID" > "$repo_file"
fi
source_file="${state_dir}/source-host"
if [[ -s "$source_file" && "$(<"$source_file")" != "$CF_MIGRATION_SOURCE_HOST" ]]; then
    echo "State belongs to a different staging path: $(<"$source_file")" >&2
    exit 2
fi
if [[ ! -e "$source_file" ]]; then
    printf '%s\n' "$CF_MIGRATION_SOURCE_HOST" > "$source_file"
fi

if [[ ! -f "${conf_dir}/seafile.ini" ]]; then
    if [[ -e "$conf_dir" ]]; then
        echo "Incomplete client state: ${conf_dir}" >&2
        exit 2
    fi
    cli init -c "$conf_dir" -d "$state_dir"
fi

cleanup() {
    cli stop -c "$conf_dir" >/dev/null 2>&1 || true
}
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT

cli start -c "$conf_dir"

# Refuse to attach a second repository or a different worktree to this client.
repo_list="$(cli list -c "$conf_dir" --json)"
link_status=0
python3 -c '
import json, os, sys
repos = json.loads(sys.argv[1])
repo_id = os.environ["CF_MIGRATION_REPO_ID"]
source = os.path.realpath("/migration/source")
if len(repos) > 1 or any(r["id"] != repo_id or os.path.realpath(r["path"]) != source for r in repos):
    print("Client state contains another repository or worktree", file=sys.stderr)
    sys.exit(2)
sys.exit(0 if repos else 1)
' "$repo_list" || link_status=$?
if [[ "$link_status" -eq 2 ]]; then
    exit 2
fi
if [[ "$link_status" -eq 1 ]]; then
    # A token argument is required by seaf-cli. It is read from a mounted
    # secret and never written to Compose, the image, or the logs.
    token="$(<"$token_file")"
    cli sync -c "$conf_dir" -l "$CF_MIGRATION_REPO_ID" \
        -s "$CF_MIGRATION_SERVER_URL" -d "$source_dir" \
        -u "$CF_MIGRATION_USER" -T "$token"
    unset token
fi

# Keep the daemon active until an operator validates counts/content and stops
# this one-shot service. JSON status exposes errors without declaring a false
# completion while the client is still indexing millions of files.
while :; do
    cli status -c "$conf_dir" --json
    sleep "${CF_MIGRATION_STATUS_INTERVAL:-60}" 9>&- &
    wait $!
done
