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

server_compile_tree=$(git -C "$server_dir" ls-files -s -- \
    Makefile.am autogen.sh configure.ac m4 include lib common python server \
    tools controller fuse fileserver notification-server | hash_stream)

# A backend rebuild is driven by C/Go source and its compiler/build recipe. A
# Hub-only commit therefore reuses the backend binary artifact.
backend_key=$({
    echo "backend-v1"
    echo "platform=linux-amd64"
    echo "server-inputs=$server_compile_tree"
    echo "libsearpc=$libsearpc_ref"
    echo "libevhtp=$libevhtp_ref"
    echo "build-base=$build_base_image"
    echo "ubuntu-base=$ubuntu_base_image"
    git -C "$repo_root" ls-tree -r HEAD -- \
        build/cloudfile_14.0 image/cloudfile_14.0/Dockerfile.base base_scripts
} | hash_stream)

# Webpack and collectstatic inputs are narrower than the Hub repository. This
# avoids recompiling the frontend for Python/API-only commits while still
# including static files and translations outside frontend/.
frontend_input_tree=$(git -C "$hub_dir" ls-files -s -- \
    frontend locale media 'requirements*.txt' \
    ':(glob)**/static/**' ':(glob)**/locale/**' | hash_stream)
frontend_key=$({
    echo "frontend-v1"
    echo "platform=linux-amd64"
    echo "hub-inputs=$frontend_input_tree"
    echo "server-python=$server_python_tree"
    echo "libsearpc=$libsearpc_ref"
    echo "build-base=$build_base_image"
    echo "ubuntu-base=$ubuntu_base_image"
    git -C "$repo_root" ls-tree -r HEAD -- \
        build/cloudfile_14.0 image/cloudfile_14.0/Dockerfile.base base_scripts
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
EOF
