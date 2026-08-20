#!/bin/bash

# Resolve moving release refs once and derive component-scoped cache keys.
# The resulting SHAs are passed to every build job so a branch update during a
# workflow cannot mix source revisions in one image.

set -euo pipefail

if [[ $# != 3 ]]; then
    echo "usage: $0 <version> <cloudfile-server-dir> <cloudfile-hub-dir>" >&2
    exit 2
fi

version=$1
if [[ ! $version =~ ^[0-9]+(\.[0-9]+)+(-[0-9A-Za-z.-]+)?$ ]]; then
    echo "invalid release version: $version" >&2
    exit 2
fi
server_dir=$(cd "$2" && pwd)
hub_dir=$(cd "$3" && pwd)
repo_root=$(cd "$(dirname "$0")/.." && pwd)
manifest=$repo_root/release.yaml
reader=$repo_root/build/cloudfile_14.0/read-manifest.py

server_sha=$(git -C "$server_dir" rev-parse 'HEAD^{commit}')
hub_sha=$(git -C "$hub_dir" rev-parse 'HEAD^{commit}')
server_python_tree=$(git -C "$server_dir" rev-parse 'HEAD:python')
libsearpc_ref=$(python3 "$reader" "$manifest" upstream.libsearpc)
libevhtp_ref=$(python3 "$reader" "$manifest" upstream.libevhtp)
build_base_image=$(python3 "$reader" "$manifest" build_base_image)
ubuntu_base_image=$(python3 "$reader" "$manifest" ubuntu_base_image)

hash_stream() {
    sha256sum | cut -d' ' -f1
}

# Recipe files for each job. Listed explicitly so a build-script change that
# only affects one stage invalidates only that stage's cache.
#
#   backend_recipe  : C/Go compile + Go fileserver compile + package backend
#                     archive; never reads the Dockerfile used by package.
#   frontend_recipe : webpack/collectstatic + Django static assets + frontend
#                     artifact packaging; never reads cloudfile-build.py
#                     (that only matters for C/Go compile).
#   package_recipe  : final assembly of artifacts into the dist tree, plus
#                     the production image build.
#
# build-in-docker.sh, read-manifest.py, and base-build.sh are common
# wrappers invoked by every job, so a change there invalidates every key.
# That is intentional: they sit on the control plane and not the data plane.
backend_recipe_files=(
    build/cloudfile_14.0/cloudfile-build.sh
    build/cloudfile_14.0/cloudfile-build.py
    build/cloudfile_14.0/build-in-docker.sh
    build/cloudfile_14.0/read-manifest.py
    image/cloudfile_14.0/Dockerfile.base
    image/cloudfile_14.0/base-build.sh
    base_scripts
)
frontend_recipe_files=(
    build/cloudfile_14.0/cloudfile-build.sh
    build/cloudfile_14.0/build-in-docker.sh
    build/cloudfile_14.0/read-manifest.py
    image/cloudfile_14.0/Dockerfile.base
    image/cloudfile_14.0/base-build.sh
    base_scripts
)
package_recipe_files=(
    build/cloudfile_14.0/cloudfile-build.sh
    build/cloudfile_14.0/cloudfile-build.py
    build/cloudfile_14.0/build-in-docker.sh
    build/cloudfile_14.0/read-manifest.py
    image/cloudfile_14.0/Dockerfile
    image/cloudfile_14.0/Dockerfile.base
    image/cloudfile_14.0/base-build.sh
    image/cloudfile_14.0/docker-build.sh
    base_scripts
)

recipe_fingerprint() {
    local repo=$1
    shift
    git -C "$repo" ls-tree -r HEAD -- "$@" | hash_stream
}

server_compile_tree=$(git -C "$server_dir" ls-files -s -- \
    Makefile.am autogen.sh configure.ac m4 include lib common python server \
    tools controller fuse fileserver notification-server | hash_stream)

# A backend rebuild is driven by C/Go source and its backend-stage recipe.
# A Hub-only commit therefore reuses the backend binary artifact.
backend_key=$({
    echo "backend-v2"
    echo "platform=linux-amd64"
    echo "server-inputs=$server_compile_tree"
    echo "libsearpc=$libsearpc_ref"
    echo "libevhtp=$libevhtp_ref"
    echo "build-base=$build_base_image"
    echo "ubuntu-base=$ubuntu_base_image"
    echo "recipe=$(recipe_fingerprint "$repo_root" "${backend_recipe_files[@]}")"
} | hash_stream)

# Webpack and collectstatic inputs are narrower than the Hub repository. This
# avoids recompiling the frontend for Python/API-only commits while still
# including static files and translations outside frontend/.
frontend_input_tree=$(git -C "$hub_dir" ls-files -s -- \
    frontend locale media 'requirements*.txt' \
    ':(glob)**/static/**' ':(glob)**/locale/**' | hash_stream)
frontend_key=$({
    echo "frontend-v2"
    echo "platform=linux-amd64"
    echo "hub-inputs=$frontend_input_tree"
    echo "server-python=$server_python_tree"
    echo "build-base=$build_base_image"
    echo "ubuntu-base=$ubuntu_base_image"
    echo "recipe=$(recipe_fingerprint "$repo_root" "${frontend_recipe_files[@]}")"
} | hash_stream)

# Package-stage cache key: feeds into cf-package-tools-. Backend/frontend
# jobs already gate their own caches; package only re-runs when the recipe
# that drives dist assembly or the production image build changes.
package_key=$({
    echo "package-v1"
    echo "platform=linux-amd64"
    echo "recipe=$(recipe_fingerprint "$repo_root" "${package_recipe_files[@]}")"
} | hash_stream)

# If release.yaml pins explicit release commits, fail instead of silently
# building another branch head. Empty values remain valid for development.
declared_server=$(python3 "$reader" "$manifest" server_commit || true)
declared_hub=$(python3 "$reader" "$manifest" hub_commit || true)
if [[ -n $declared_server && $declared_server != "$server_sha" ]]; then
    echo "server_commit does not match resolved server ref" >&2
    exit 1
fi
if [[ -n $declared_hub && $declared_hub != "$hub_sha" ]]; then
    echo "hub_commit does not match resolved hub ref" >&2
    exit 1
fi

cat <<EOF
server_sha=$server_sha
hub_sha=$hub_sha
backend_key=$backend_key
frontend_key=$frontend_key
package_key=$package_key
EOF
