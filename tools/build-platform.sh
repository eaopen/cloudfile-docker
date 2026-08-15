#!/bin/bash

# Canonicalize the host OS and the two architectures the CloudFile build
# images support, in one place so the source build, base build and final
# image build cannot drift. Build scripts ask "what should I build natively
# here?" via cf_host_platform() and get a fast, native answer per host:
#
#   macOS (Apple Silicon)      -> linux/arm64   (native, fast)
#   macOS (Intel)              -> linux/amd64   (native)
#   Linux (x86_64/amd64)       -> linux/amd64   (native)
#   Linux (aarch64/arm64)      -> linux/arm64   (native)
#   Windows (Docker Desktop)   -> linux/amd64   (Linux VM is amd64)
#
# CF_PLATFORM overrides this anywhere; cf_normalize_platform rejects anything
# else so a typo fails before a long QEMU build instead of after it.

#: Canonical host OS: darwin | linux | windows | unknown
cf_host_os() {
    case "$(uname -s)" in
        Darwin)  echo darwin ;;
        Linux)   echo linux ;;
        MINGW*|MSYS*|CYGWIN*) echo windows ;;
        *)       echo unknown ;;
    esac
}

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
    local os arch
    os=$(cf_host_os)
    case "$os" in
        darwin)
            arch=$(uname -m)
            # A terminal launched under Rosetta 2 reports x86_64 even though the
            # machine is arm64; Docker Desktop still runs the native arm64
            # daemon, so preferring the emulated amd64 here would silently turn
            # every build into a QEMU build. sysctl.proc_translated is 1 only
            # when the process is translated.
            if [[ $arch == x86_64 ]] \
               && [[ "$(sysctl -n sysctl.proc_translated 2>/dev/null)" == 1 ]]; then
                arch=arm64
            fi
            cf_normalize_platform "$arch"
            ;;
        linux)
            cf_normalize_platform "$(uname -m)"
            ;;
        windows)
            # Docker Desktop on Windows runs an amd64 Linux VM; Windows-on-ARM
            # is negligible and the MSYS uname reports x86_64 there anyway.
            echo linux/amd64
            ;;
        *)
            echo "unsupported host OS '$(uname -s)'; build on Linux or macOS" >&2
            return 2
            ;;
    esac
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
