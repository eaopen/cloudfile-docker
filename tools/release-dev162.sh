#!/usr/bin/env bash
# Build CloudFile on the Linux build host and publish a versioned image to Nexus.

set -euo pipefail

usage() {
    echo "Usage: $0 <version> [all|build|push]" >&2
    echo "  all: pull, build, verify and push (default)" >&2
    echo "  build: pull, build and verify" >&2
    echo "  push: verify and push an existing local image" >&2
}

if [[ $# -lt 1 || $# -gt 2 || ! $1 =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]]; then
    usage
    exit 2
fi
version=$1
mode=${2:-all}
case "$mode" in
    all|build|push) ;;
    *) usage; exit 2 ;;
esac

here=$(cd "$(dirname "$0")" && pwd)
repo_root=$(cd "$here/.." && pwd)
workspace=$(cd "$repo_root/.." && pwd)
server_repo=$workspace/cloudfile-server
hub_repo=$workspace/cloudfile-hub
manifest=$repo_root/release.yaml
reader=$repo_root/build/cloudfile_14.0/read-manifest.py
dist=$repo_root/build/cloudfile_14.0/seafile-server-$version
local_image=$(python3 "$reader" "$manifest" image)
local_image=${local_image%%:*}:$version
registry=${CF_NEXUS_REGISTRY:-10.12.1.138:8041}
registry=${registry%/}
remote_image=$registry/$local_image
base_image=$(python3 "$reader" "$manifest" build_base_image)

if [[ $(uname -s) != Linux || $(uname -m) != x86_64 ]]; then
    echo "This release script requires a Linux x86_64 build host." >&2
    exit 2
fi
for repo in "$repo_root" "$server_repo" "$hub_repo"; do
    [[ -d $repo/.git ]] || { echo "Missing repository: $repo" >&2; exit 2; }
done
docker info >/dev/null

git_at() { (cd "$1" && shift && git "$@"); }
clean_at() {
    [[ -z $(git_at "$1" status --porcelain) ]] || {
        echo "Uncommitted changes in $1" >&2
        exit 2
    }
}

if [[ $mode != push ]]; then
    for repo in "$repo_root" "$server_repo" "$hub_repo"; do
        clean_at "$repo"
        branch=$(git_at "$repo" symbolic-ref --quiet --short HEAD) || {
            echo "Detached HEAD in $repo" >&2
            exit 2
        }
        echo "Updating $(basename "$repo") ($branch)"
        git_at "$repo" pull --ff-only origin "$branch"
    done
    server_ref=$(python3 "$reader" "$manifest" forks.cloudfile_server.ref)
    hub_ref=$(python3 "$reader" "$manifest" forks.cloudfile_hub.ref)
    [[ $(git_at "$server_repo" symbolic-ref --short HEAD) == "$server_ref" &&
       $(git_at "$hub_repo" symbolic-ref --short HEAD) == "$hub_ref" ]] || {
        echo "Local Server/Hub branches differ from release.yaml refs." >&2
        exit 2
    }
    if ! docker image inspect "$base_image" >/dev/null 2>&1; then
        echo "Building missing base image: $base_image"
        PIP_INDEX_URL=${PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple} \
            "$repo_root/image/cloudfile_14.0/base-build.sh"
    fi
    echo "Building distribution: $version"
    PIP_INDEX_URL=${PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple} \
    npm_config_registry=${npm_config_registry:-https://registry.npmmirror.com} \
    npm_config_fetch_retries=${npm_config_fetch_retries:-5} \
    GOPROXY=${GOPROXY:-https://goproxy.cn,direct} \
    CF_BUILD_JOBS=${CF_BUILD_JOBS:-16} \
    CF_SERVER_URL=$server_repo CF_HUB_URL=$hub_repo \
        "$repo_root/build/cloudfile_14.0/build-in-docker.sh" "$version"
    "$repo_root/tools/verify-release-artifact.sh" "$dist"
    echo "Building image: $local_image"
    "$repo_root/image/cloudfile_14.0/docker-build.sh" "$version"
fi

[[ -f $dist/cloudfile-build-info.txt ]] || {
    echo "Missing distribution: $dist" >&2
    exit 1
}
"$repo_root/tools/verify-release-artifact.sh" "$dist"
for entry in "seafile-server:$server_repo" "seahub:$hub_repo"; do
    component=${entry%%:*}
    path=${entry#*:}
    sha=$(git_at "$path" rev-parse HEAD)
    grep -Fqx "$component: $sha" "$dist/cloudfile-build-info.txt" || {
        echo "Distribution $component commit differs from local checkout." >&2
        exit 1
    }
done
docker image inspect "$local_image" >/dev/null
image_arch=$(docker image inspect --format '{{.Architecture}}' "$local_image")
[[ $image_arch == amd64 ]] || { echo "Image is $image_arch, expected amd64." >&2; exit 1; }
docker run --rm --network=none --entrypoint cat "$local_image" \
    "/opt/seafile/seafile-server-$version/cloudfile-build-info.txt" \
    | cmp -s "$dist/cloudfile-build-info.txt" - || {
        echo "Image build info differs from the distribution." >&2
        exit 1
    }

if [[ $mode == build ]]; then
    echo "Built and verified $local_image"
    exit 0
fi

echo "Publishing $remote_image"
docker tag "$local_image" "$remote_image"
docker push "$remote_image"
echo "Published $remote_image"
