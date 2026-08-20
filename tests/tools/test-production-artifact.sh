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

# Round-trip: re-import into a fresh seahub root. The import function pins
# `seahub = ${code_path}/seahub`, so we swap the original seahub directory
# out and place the import target where the function looks for it.
import_seahub=$fixture/import-seahub
mkdir -p "$import_seahub"
rm -rf "$fixture/seahub"
mv "$import_seahub" "$fixture/seahub"
code_path=$fixture
current_dir=$builddir
seahub=$fixture/seahub

# shellcheck disable=SC1090
eval "$import_fn"
import_frontend_artifact

for p in "${required_paths[@]}"; do
    case $p in
        frontend/*) dest=$fixture/seahub/frontend/${p#frontend/} ;;
        media/*)    dest=$fixture/seahub/media/${p#media/} ;;
        build-info.txt)
            # build-info.txt only lives inside the artifact; import does
            # not need to restore it into seahub.
            continue ;;
    esac
    [[ -e $dest ]] || { echo "import missing: $dest" >&2; exit 1; }
done

# Compare content SHA between source and import for the runtime files.
hash_one() { sha256sum "$1" | cut -d' ' -f1; }

src_stats=$fixture/seahub/frontend/webpack-stats.pro.json
dst_stats=$fixture/seahub/frontend/webpack-stats.pro.json
[[ -f $dst_stats ]] || { echo "import missing: $dst_stats" >&2; exit 1; }
[[ $(hash_one "$src_stats") == "$(hash_one "$dst_stats")" ]] \
    || { echo "webpack-stats.pro.json content differs after round-trip" >&2; exit 1; }

src_mo=$fixture/seahub/seahub/locale/zh_CN/LC_MESSAGES/django.mo
dst_mo=$fixture/seahub/seahub/locale/zh_CN/LC_MESSAGES/django.mo
[[ -f $dst_mo ]] || { echo "import missing: $dst_mo" >&2; exit 1; }
[[ $(hash_one "$src_mo") == "$(hash_one "$dst_mo")" ]] \
    || { echo "django.mo content differs after round-trip" >&2; exit 1; }

echo "frontend artifact export/import round-trip OK"