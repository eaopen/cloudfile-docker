#!/bin/bash
#
# Verify that the cross-job frontend artifact produced by
# export_frontend_artifact contains everything the package job needs to
# restore the seahub tree, and that import_frontend_artifact puts those files
# back without losing content.
#
# This test exists because the previous contract test (test-production-workflow)
# only checked workflow text and cache keys. It never executed
# frontend export -> package import, so the shipped incremental image was
# missing webpack-stats.pro.json and compiled .mo files. The package built,
# the page 500'd.
#
# Strategy: source the build script's two frontend artifact functions,
# run them against a fixture that mimics the seahub tree after build, then
# assert every required path is in the artifact and round-trips through
# import.

set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
repo_root=$(cd "$here/../.." && pwd)
build_script=$repo_root/build/cloudfile_14.0/cloudfile-build.sh

if [[ ! -f $build_script ]]; then
    echo "missing build script: $build_script" >&2
    exit 1
fi

# Extract the two functions verbatim. We need the function bodies as the
# build script defines them today, so a copy-paste drift here cannot mask
# a missing export/import fix in the real script.
extract_function() {
    local name=$1
    awk -v fn="function ${name}()" '
        $0 ~ "^" fn { printing = 1 }
        printing { print }
        printing && /^\}/ { exit }
    ' "$build_script"
}

export_fn=$(extract_function export_frontend_artifact)
import_fn=$(extract_function import_frontend_artifact)

[[ -n $export_fn ]] || { echo "export_frontend_artifact not found in build script" >&2; exit 1; }
[[ -n $import_fn ]] || { echo "import_frontend_artifact not found in build script" >&2; exit 1; }

# Required paths inside the artifact and inside the imported seahub tree.
# These are the contract: if any one is missing, the incremental image
# breaks in production. Names match what the package job relies on.
required_paths=(
    frontend/build
    frontend/webpack-stats.pro.json
    media/assets
    build-info.txt
    manifest.sha256
)
# Compiled translations must exist for every language that Django writes
# during compilemessages. We seed zh_CN as the smoke case; the function
# mirrors whatever it finds under */locale/*/LC_MESSAGES/*.mo.
required_mo=(
    seahub/locale/zh_CN/LC_MESSAGES/django.mo
    seahub_extra/locale/zh_CN/LC_MESSAGES/django.mo
)

fixture=$(mktemp -d)
trap 'rm -rf "$fixture"' EXIT
seahub=$fixture/seahub
builddir=$fixture/builddir
server=$fixture/seafile-server
mkdir -p "$seahub" "$builddir" "$server" \
         "$seahub/frontend/build/static/js" \
         "$seahub/media/assets/css" \
         "$seahub/seahub/locale/zh_CN/LC_MESSAGES" \
         "$seahub/seahub_extra/locale/zh_CN/LC_MESSAGES"

# export_frontend_artifact reads two commits into build-info.txt:
#   * the seahub commit (`git -C "$seahub" rev-parse HEAD`)
#   * the server python tree (`git -C "$code_path/seafile-server" rev-parse HEAD:python`)
# Both need a working git repo. Seed files first, then init, so the initial
# commit is non-empty.
printf 'STATS %s\n' "$(date +%s)" > "$seahub/frontend/webpack-stats.pro.json"
printf 'BUNDLE %s\n' "$(date +%s)" > "$seahub/frontend/build/static/js/main.js"
printf 'CSS %s\n' "$(date +%s)" > "$seahub/media/assets/css/app.css"
printf 'MO-DJANGO %s\n' "$(date +%s)" > "$seahub/seahub/locale/zh_CN/LC_MESSAGES/django.mo"
printf 'MO-EXTRA %s\n' "$(date +%s)" > "$seahub/seahub_extra/locale/zh_CN/LC_MESSAGES/django.mo"
mkdir -p "$server/python"
printf 'PY %s\n' "$(date +%s)" > "$server/python/placeholder.py"

for repo in "$seahub" "$server"; do
    git -C "$repo" init -q
    git -C "$repo" config user.name CloudFile-Test
    git -C "$repo" config user.email cloudfile-test@example.invalid
    git -C "$repo" add -A
    git -C "$repo" commit -qm "fixture"
done

# The functions read two positional globals from the build script:
#   code_path   -> where the source tree (seahub) lives
#   current_dir -> where the artifact directory gets created/imported
code_path=$fixture
current_dir=$builddir

# shellcheck disable=SC1090
eval "$export_fn"
export_frontend_artifact

artifact=$builddir/cloudfile-frontend
missing=0
for p in "${required_paths[@]}"; do
    if [[ ! -e $artifact/$p ]]; then
        echo "missing required artifact path: $p" >&2
        missing=1
    fi
done
for p in "${required_mo[@]}"; do
    # export uses `cd "$seahub" && find . -path '*/locale/*/LC_MESSAGES/*.mo'`
    # so each .mo preserves its full path under $seahub. The artifact stores
    # the whole subtree under locale/, so the path matches `p` exactly once
    # the leading $seahub prefix is dropped.
    src=$seahub/$p
    if [[ ! -e $artifact/locale/$p ]]; then
        echo "missing compiled .mo in artifact: locale/$p (source: $src)" >&2
        missing=1
    fi
done
[[ $missing -eq 0 ]] || { echo "frontend export contract broken" >&2; exit 1; }

# Round-trip: remove only generated outputs while preserving the checked-out
# Hub repository. Import validates build-info against that immutable checkout,
# exactly as the package job does on its fresh runner.
rm -rf "$seahub/frontend/build" "$seahub/media/assets"
rm -f "$seahub/frontend/webpack-stats.pro.json"
find "$seahub" -path '*/locale/*/LC_MESSAGES/*.mo' -delete
mkdir -p "$seahub/thirdpart/example/locale/zh_CN/LC_MESSAGES"
printf 'THIRDPARTY\n' \
    > "$seahub/thirdpart/example/locale/zh_CN/LC_MESSAGES/django.mo"
code_path=$fixture
current_dir=$builddir
seahub=$fixture/seahub

# shellcheck disable=SC1090
eval "$import_fn"
import_frontend_artifact
grep -Fqx THIRDPARTY \
    "$seahub/thirdpart/example/locale/zh_CN/LC_MESSAGES/django.mo" || {
    echo "frontend import removed third-party translations" >&2; exit 1; }

for p in "${required_paths[@]}"; do
    case $p in
        frontend/*) dest=$fixture/seahub/frontend/${p#frontend/} ;;
        media/*)    dest=$fixture/seahub/media/${p#media/} ;;
        build-info.txt|manifest.sha256)
            # Artifact metadata is validated during import but does not need
            # to be copied into the seahub source tree.
            continue ;;
    esac
    [[ -e $dest ]] || { echo "import missing: $dest" >&2; exit 1; }
done

# Compare content SHA between artifact and imported tree. The original
# seahub was replaced by the import target, so the artifact is the source
# of truth here.
hash_one() { sha256sum "$1" | cut -d' ' -f1; }

art_stats=$artifact/frontend/webpack-stats.pro.json
dst_stats=$fixture/seahub/frontend/webpack-stats.pro.json
[[ -f $dst_stats ]] || { echo "import missing: $dst_stats" >&2; exit 1; }
[[ $(hash_one "$art_stats") == "$(hash_one "$dst_stats")" ]] \
    || { echo "webpack-stats.pro.json content differs after round-trip" >&2; exit 1; }

art_mo=$artifact/locale/seahub/locale/zh_CN/LC_MESSAGES/django.mo
dst_mo=$fixture/seahub/seahub/locale/zh_CN/LC_MESSAGES/django.mo
[[ -f $dst_mo ]] || { echo "import missing: $dst_mo" >&2; exit 1; }
[[ -f $art_mo ]] || { echo "artifact missing: $art_mo" >&2; exit 1; }
[[ $(hash_one "$art_mo") == "$(hash_one "$dst_mo")" ]] \
    || { echo "django.mo content differs after round-trip" >&2; exit 1; }

# A changed byte must be rejected before import. Restore it afterwards so the
# remaining tests continue with the valid artifact.
cp "$art_stats" "$art_stats.valid"
printf 'tampered\n' >> "$art_stats"
if ( import_frontend_artifact ) >/dev/null 2>&1; then
    echo "tampered frontend artifact passed checksum verification" >&2
    exit 1
fi
mv "$art_stats.valid" "$art_stats"

# ── backend artifact round-trip ──────────────────────────────────────────
export_backend_fn=$(extract_function export_backend_artifact)
import_backend_fn=$(extract_function import_backend_artifact)
[[ -n $export_backend_fn && -n $import_backend_fn ]] || {
    echo "backend artifact functions not found in build script" >&2; exit 1; }

backend_fixture=$(mktemp -d)
backend_src=$backend_fixture/src
backend_build=$backend_fixture/build
mkdir -p "$backend_src" "$backend_build/seafile-server/seafile/bin" \
    "$backend_src/seafile-server/fileserver" \
    "$backend_src/seafile-server/notification-server"
for component in seafile-server libsearpc libevhtp; do
    repo=$backend_src/$component
    mkdir -p "$repo"
    printf '%s source\n' "$component" > "$repo/source.txt"
    git -C "$repo" init -q
    git -C "$repo" config user.name CloudFile-Test
    git -C "$repo" config user.email cloudfile-test@example.invalid
    git -C "$repo" add -A
    git -C "$repo" commit -qm fixture
done
printf 'server binary\n' > "$backend_build/seafile-server/seafile/bin/seaf-server"
printf 'fileserver binary\n' > "$backend_src/seafile-server/fileserver/fileserver"
printf 'notification binary\n' \
    > "$backend_src/seafile-server/notification-server/notification-server"
chmod +x "$backend_build/seafile-server/seafile/bin/seaf-server" \
    "$backend_src/seafile-server/fileserver/fileserver" \
    "$backend_src/seafile-server/notification-server/notification-server"

code_path=$backend_src
current_dir=$backend_build
version=artifact-test
eval "$export_backend_fn"
eval "$import_backend_fn"
export_backend_artifact

backend_artifact=$backend_build/cloudfile-backend
[[ -s $backend_artifact/manifest.sha256 ]] || {
    echo "backend manifest missing" >&2; exit 1; }
rm -rf "$backend_build/seafile-server"
rm -f "$backend_src/seafile-server/fileserver/fileserver" \
    "$backend_src/seafile-server/notification-server/notification-server"
import_backend_artifact
[[ -x $backend_build/seafile-server/seafile/bin/seaf-server ]] || {
    echo "backend import missing seaf-server" >&2; exit 1; }
[[ -x $backend_src/seafile-server/fileserver/fileserver ]] || {
    echo "backend import missing fileserver" >&2; exit 1; }

printf 'tampered\n' >> "$backend_artifact/fileserver/fileserver"
if ( import_backend_artifact ) >/dev/null 2>&1; then
    echo "tampered backend artifact passed checksum verification" >&2
    exit 1
fi

# ── layer_frontend cache round-trip ─────────────────────────────────────
# The frontend layer cache must carry the locale subtree too: a hit without
# it would restore build/assets/stats but leave the tree without .mo files.
layer_fn=$(extract_function layer_frontend)
[[ -n $layer_fn ]] || { echo "layer_frontend not found in build script" >&2; exit 1; }

# Mock only external helpers; execute the real layer_frontend body for both
# the fill and hit passes so the test cannot drift from production commands.
cache_hit_mode=0
layer_hit() { [[ $cache_hit_mode == 1 ]]; }
layer_mark() { :; }
build_seahub_frontend() {
    [[ $cache_hit_mode == 0 ]] || {
        echo "ERROR: build_seahub_frontend ran on a cache hit" >&2
        exit 1
    }
}
frontend_fingerprint() { echo fp-test; }
eval "$layer_fn"

cache_fixture=$(mktemp -d)
cf_seahub=$cache_fixture/seahub
mkdir -p "$cf_seahub/frontend/build/static/js" "$cf_seahub/media/assets/css" \
         "$cf_seahub/seahub/locale/zh_CN/LC_MESSAGES" \
         "$cf_seahub/seahub_extra/locale/zh_CN/LC_MESSAGES"
printf 'BUNDLE2\n' > "$cf_seahub/frontend/build/static/js/main.js"
printf 'ASSETS2\n' > "$cf_seahub/media/assets/css/app.css"
printf 'STATS2\n' > "$cf_seahub/frontend/webpack-stats.pro.json"
printf 'MO2\n' > "$cf_seahub/seahub/locale/zh_CN/LC_MESSAGES/django.mo"
printf 'MO2X\n' > "$cf_seahub/seahub_extra/locale/zh_CN/LC_MESSAGES/django.mo"
expected_bundle=$(hash_one "$cf_seahub/frontend/build/static/js/main.js")
expected_mo=$(hash_one "$cf_seahub/seahub/locale/zh_CN/LC_MESSAGES/django.mo")

code_path=$cache_fixture
cache=$code_path/.cache/frontend-build
CF_FORCE_REBUILD=0
CF_FORCE_FRONTEND_REBUILD=0

layer_frontend

[[ -f $cache/locale/seahub/locale/zh_CN/LC_MESSAGES/django.mo ]] || {
    echo "cache fill missing .mo" >&2; exit 1; }

# Hit pass: wipe outputs, seed a stale translation, then invoke the real cache
# restore. The stale file must be removed and replaced with cached content.
rm -rf "$cf_seahub/frontend/build" "$cf_seahub/media/assets"
find "$cf_seahub" -path '*/locale/*/LC_MESSAGES/*.mo' -delete
mkdir -p "$cf_seahub/seahub/locale/zh_CN/LC_MESSAGES"
printf 'STALE\n' > "$cf_seahub/seahub/locale/zh_CN/LC_MESSAGES/django.mo"
cache_hit_mode=1
layer_frontend

[[ $(hash_one "$cf_seahub/frontend/build/static/js/main.js") == "$expected_bundle" ]] || {
    echo "restored bundle content differs" >&2; exit 1; }
[[ -f $cf_seahub/seahub_extra/locale/zh_CN/LC_MESSAGES/django.mo ]] || {
    echo "restore missing extra .mo" >&2; exit 1; }
[[ $(hash_one "$cf_seahub/seahub/locale/zh_CN/LC_MESSAGES/django.mo") == "$expected_mo" ]] || {
    echo ".mo content differs after cache round-trip" >&2; exit 1; }

echo "frontend layer cache round-trip OK"
