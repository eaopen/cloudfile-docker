#!/bin/bash
#
# prod.yml 契约：只在手动触发、只从一份收据构建、不做容器验收。
#
# 8ee34d1 把生产流程从"按提交内容拆 backend/frontend/package 三个增量 job"
# 改成"一次解析收据 → 单次全量构建 → 镜像组装"，prod.yml 因此从 400 行缩到
# 一百行出头。旧断言（inputs.mode == 'full'、CF_BUILD_TARGET 三段、
# backend_key/frontend_key/package_key）已随该实现一起退役；留着它们等于
# 要求仓库同时维持两套互斥流程。

set -euo pipefail

repo_root=$(cd "$(dirname "$0")/../.." && pwd)
workflow=$repo_root/.github/workflows/prod.yml
build_script=$repo_root/build/cloudfile_14.0/cloudfile-build.sh

require_text() {
    local file=$1 text=$2
    if ! grep -Fq -- "$text" "$file"; then
        echo "missing release contract in $(basename "$file"): $text" >&2
        exit 1
    fi
}

forbid_text() {
    local file=$1 text=$2
    if grep -Fq -- "$text" "$file"; then
        echo "production workflow must not contain: $text" >&2
        exit 1
    fi
}

# 1. 触发方式：不得回到每次 push，也不得挂 PR。
if grep -Eq '^[[:space:]]+push:' "$workflow"; then
    echo 'production workflow must not run for every push' >&2
    exit 1
fi
if grep -Eq '^[[:space:]]+pull_request:' "$workflow"; then
    echo 'production workflow must not run for pull requests' >&2
    exit 1
fi
require_text "$workflow" 'workflow_dispatch:'

# 2. 同一组合重复触发时让位给新任务：收据固定了 SHA，取消旧任务不会让产物
#    对应到别的源码。
require_text "$workflow" 'cancel-in-progress: true'

# 3. 三仓分支只在 plan job 解析一次，之后所有 job 按 docker_sha 检出、按收据
#    里的 SHA 取源码——不允许在后面的 job 里重新解析可变 ref。
require_text "$workflow" 'needs: plan'
require_text "$workflow" 'build_receipt.py resolve'
require_text "$workflow" 'ref: ${{ needs.plan.outputs.docker_sha }}'
require_text "$workflow" 'name: source-receipt'
require_text "$workflow" 'CF_BUILD_RECEIPT:'

# 4. 构建与组装链路：基础镜像、容器内编译、镜像组装、证据留存。
require_text "$workflow" 'image/cloudfile_14.0/base-build.sh'
require_text "$workflow" 'build/cloudfile_14.0/build-in-docker.sh'
require_text "$workflow" 'image/cloudfile_14.0/docker-build.sh'
require_text "$workflow" 'build-receipt.json'
require_text "$workflow" 'test-results'

# 5. 容器验收不进生产流程：这里的 E2E 与能力矩阵只在本地 verify-local.sh 跑。
forbid_text "$workflow" 'tests/e2e/'
forbid_text "$workflow" 'docker compose'

# 6. 源码检出必须按不可变提交，且重建前清掉旧发行目录——否则增量缓存会把
#    上一次的产物当成这一次的结果。
if ! grep -Fq 'git fetch --no-tags origin "$ref"' "$build_script"; then
    echo 'build script must fetch the requested ref from origin' >&2
    exit 1
fi
if ! grep -Fq 'git checkout --detach "$ref"' "$build_script"; then
    echo 'build script must check out the resolved commit, not a branch name' >&2
    exit 1
fi
if ! grep -Fq 'rm -rf "${current_dir}/seafile-server" "${current_dir}/seafile-server-${version}"' "$build_script"; then
    echo 'build script must clear the previous release directory before rebuilding' >&2
    exit 1
fi
if ! grep -Fq 'git clean -xfd -e frontend/node_modules/' "$build_script"; then
    echo 'checkout must drop stale generated stamps but keep node_modules' >&2
    exit 1
fi
if grep -Eq 'git clean -fd[[:space:]]*$' "$build_script"; then
    echo 'incremental checkout must not preserve stale ignored build stamps' >&2
    exit 1
fi

echo 'prod workflow matches the immutable receipt contract'
