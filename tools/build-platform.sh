#!/bin/bash

# Canonicalize the two architectures supported by the CloudFile build images.
# Keep this in one place so the source build and final image build cannot drift.
cf_normalize_platform() {
    case "$1" in
        linux/amd64|amd64|x86_64)
            echo linux/amd64
            ;;
        linux/arm64|linux/arm64/v8|arm64|aarch64)
            echo linux/arm64
            ;;
        *)
            echo "unsupported platform '$1'; use linux/amd64 or linux/arm64" >&2
            return 2
            ;;
    esac
}

cf_host_platform() {
    cf_normalize_platform "$(uname -m)"
}

cf_platform_arch() {
    case "$1" in
        linux/amd64) echo amd64 ;;
        linux/arm64) echo arm64 ;;
        *)
            echo "platform is not normalized: $1" >&2
            return 2
            ;;
    esac
}
