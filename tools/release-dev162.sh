#!/usr/bin/env bash
# Build CloudFile on the Linux build host and publish a versioned image to Nexus.

set -euo pipefail

usage() {
    echo "Usage: $0 <version> [all|build|push]" >&2
    echo "  all: pull, reuse or build, verify and publish if needed (default)" >&2
    echo "  build: pull, reuse or build and verify" >&2
    echo "  push: verify and publish an existing local image if needed" >&2
}

if [[ ${1:-} == --help || ${1:-} == -h ]]; then
    usage
    echo "Environment: CF_NEXUS_REGISTRY, CF_FORCE_REBUILD, CF_BUILD_JOBS, PIP_INDEX_URL," >&2
    echo "  npm_config_registry, npm_config_fetch_retries, GOPROXY" >&2
    exit 0
fi

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

matches_local_sources() {
    [[ -f $dist/cloudfile-build-info.txt ]] || return 1
    local component path sha
    for entry in "seafile-server:$server_repo" "seahub:$hub_repo"; do
        component=${entry%%:*}
        path=${entry#*:}
        sha=$(git_at "$path" rev-parse HEAD)
        grep -Fqx "$component: $sha" "$dist/cloudfile-build-info.txt" || return 1
    done
}

matches_local_image() {
    docker image inspect "$local_image" >/dev/null 2>&1 || return 1
    [[ $(docker image inspect --format '{{.Architecture}}' "$local_image") == amd64 ]] || return 1
    docker run --rm --network=none --entrypoint cat "$local_image" \
        "/opt/seafile/seafile-server-$version/cloudfile-build-info.txt" \
        | cmp -s "$dist/cloudfile-build-info.txt" -
}

can_reuse_build() {
    matches_local_sources || return 1
    local built_docker_sha
    built_docker_sha=$(sed -n 's/^cloudfile-docker: //p' "$dist/cloudfile-build-info.txt")
    [[ $built_docker_sha =~ ^[0-9a-f]{40}$ ]] || return 1
    git_at "$repo_root" merge-base --is-ancestor "$built_docker_sha" HEAD || return 1
    # Release tooling and documentation can change without changing the image.
    git_at "$repo_root" diff --quiet "$built_docker_sha" HEAD -- \
        release.yaml build/cloudfile_14.0 image/cloudfile_14.0/Dockerfile \
        image/cloudfile_14.0/docker-build.sh scripts services tools/build-platform.sh || return 1
    "$repo_root/tools/verify-release-artifact.sh" "$dist" >/dev/null || return 1
    matches_local_image
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
    if [[ ${CF_FORCE_REBUILD:-0} != 1 ]] && can_reuse_build; then
        echo "Source and image unchanged; reusing $local_image"
    else
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
fi

[[ -f $dist/cloudfile-build-info.txt ]] || {
    echo "Missing distribution: $dist" >&2
    exit 1
}
"$repo_root/tools/verify-release-artifact.sh" "$dist"
matches_local_sources || { echo "Distribution differs from local source commits." >&2; exit 1; }
matches_local_image || { echo "Missing or mismatched amd64 image: $local_image" >&2; exit 1; }

if [[ $mode == build ]]; then
    echo "Built and verified $local_image"
    exit 0
fi

image_id=$(docker image inspect --format '{{.Id}}' "$local_image")
remote_manifest=$(DOCKER_CLI_EXPERIMENTAL=enabled docker manifest inspect --insecure "$remote_image" 2>/dev/null) || remote_manifest=
if [[ -n $remote_manifest ]]; then
    remote_id=$(printf '%s' "$remote_manifest" | python3 -c \
        'import json, sys; print(json.load(sys.stdin).get("config", {}).get("digest", ""))')
    if [[ $remote_id == "$image_id" ]]; then
        echo "Nexus already has $remote_image ($image_id); nothing to publish"
        exit 0
    fi
fi
echo "Publishing $remote_image"
docker tag "$local_image" "$remote_image"
docker push "$remote_image"
echo "Published $remote_image"
