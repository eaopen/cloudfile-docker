#!/bin/bash
#
# Build the reusable CloudFile CE 14 base image on a machine with reliable
# package access. Daily application builds must use docker-build.sh instead.
#
#   ./base-build.sh
#   CF_PLATFORM=linux/arm64 ./base-build.sh   # override the auto-detected host arch
#   CF_BASE_IMAGE=registry.internal/cloudfile/build-base:ce14-v2 ./base-build.sh

set -e

here=$(cd "$(dirname "$0")" && pwd)
repo_root=$(cd "$here/../.." && pwd)
manifest=$repo_root/release.yaml
reader=$repo_root/build/cloudfile_14.0/read-manifest.py
source "$repo_root/tools/build-platform.sh"

base_image=${CF_BASE_IMAGE:-$(python3 "$reader" "$manifest" build_base_image)}
ubuntu_base=${CF_UBUNTU_BASE:-$(python3 "$reader" "$manifest" ubuntu_base_image)}
platform=$(cf_normalize_platform "${CF_PLATFORM:-$(cf_host_platform)}") || exit 2

if ! docker info >/dev/null 2>&1; then
    echo "Docker is unavailable." >&2
    exit 2
fi

# On GitHub Actions, reuse the BuildKit layers via the Actions cache backend so
# the toolchain image is rebuilt only when Dockerfile.base or base_scripts
# actually changes. Locally the flags are omitted and a plain build runs.
cache_args=()
if [[ ${GITHUB_ACTIONS:-false} == true ]]; then
    cache_args=(
        --cache-from "type=gha,scope=cloudfile-build-base"
        --cache-to "type=gha,mode=max,scope=cloudfile-build-base"
    )
fi

if docker buildx version >/dev/null 2>&1; then
    docker buildx build \
        --platform "$platform" \
        --file "$here/Dockerfile.base" \
        --build-arg UBUNTU_BASE="$ubuntu_base" \
        --tag "$base_image" \
        --load \
        "${cache_args[@]}" \
        "$repo_root"
else
    host_platform=$(cf_host_platform) || exit 2
    if [[ $platform != "$host_platform" ]]; then
        echo "Docker without buildx can only build for $host_platform" >&2
        exit 2
    fi
    # Docker 18.09 cannot apply a seccomp override during build. Run the same
    # commands in an isolated container with a per-container override.
    context=$(mktemp -d "$repo_root/build/cloudfile_14.0/.base-context.XXXXXX")
    container="cloudfile-base-build-$$"
    trap 'docker rm -f "$container" >/dev/null 2>&1 || true; rm -rf "$context"' EXIT
    awk '
        /^RUN --mount=type=cache/ { sub(/^RUN --mount=[^ ]+ /, "RUN "); print; next }
        /^[[:space:]]+--mount=type=cache/ { next }
        { print }
    ' "$here/Dockerfile.base" > "$context/Dockerfile"
    python3 - "$context/Dockerfile" > "$context/run.sh" <<'PY'
import sys

lines = open(sys.argv[1]).readlines()
print("#!/bin/bash\nset -e")
command = ""
for line in lines:
    if line.startswith("RUN "):
        command = line[4:]
    elif command:
        command += line
    else:
        continue
    if command.rstrip().endswith("\\"):
        command = command.rstrip()[:-1] + " "
    else:
        print(command.strip())
        command = ""
if command:
    raise SystemExit("incomplete Dockerfile RUN instruction")
PY
    docker create --name "$container" --security-opt seccomp=unconfined \
        -e DEBIAN_FRONTEND=noninteractive -e LANG=en_US.UTF-8 \
        -e LANGUAGE=en_US:en -e LC_ALL=en_US.UTF-8 \
        -e CLOUDFILE_BUILD_BASE=true -e PIP_DISABLE_PIP_VERSION_CHECK=1 \
        -e NODE_VERSION=24.21.0 -w /opt/cloudfile-build \
        "$ubuntu_base" sleep infinity >/dev/null
    docker cp "$repo_root/base_scripts" "$container:/bd_build"
    docker cp "$context/run.sh" "$container:/tmp/cloudfile-base-build.sh"
    docker start "$container" >/dev/null
    exec_env=()
    if [[ -n ${PIP_INDEX_URL:-} ]]; then
        exec_env=(-e "PIP_INDEX_URL=$PIP_INDEX_URL")
    fi
    docker exec "${exec_env[@]}" "$container" bash /tmp/cloudfile-base-build.sh
    docker commit \
        --change 'ENV DEBIAN_FRONTEND=noninteractive LANG=en_US.UTF-8 LANGUAGE=en_US:en LC_ALL=en_US.UTF-8 CLOUDFILE_BUILD_BASE=true PIP_DISABLE_PIP_VERSION_CHECK=1' \
        --change 'WORKDIR /opt/cloudfile-build' \
        "$container" "$base_image" >/dev/null
fi

echo
echo "Built and loaded $base_image ($platform)"
