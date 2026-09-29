#!/usr/bin/env python3
"""Bind a CE14 dev distribution to its actual built source commits and bytes."""

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "build/seafile_14.0"))
from package_provenance import (  # noqa: E402
    RECORD_NAME, load_manifest, verify_package, write_provenance,
)

SOURCE_NAMES = ("seafile-server", "seahub", "seafobj", "seafdav", "seafevents",
                "libsearpc", "libevhtp")
COMMIT = re.compile(r"[0-9a-f]{40}\Z")


def build_sources(package, version):
    package = Path(package)
    info = package / "cloudfile-build-info.txt"
    if not info.is_file() or info.is_symlink() or info.stat().st_size > 4096:
        raise ValueError("missing immutable build source record")
    values = {}
    for line in info.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition(": ")
        if not separator or key in values:
            raise ValueError("invalid or duplicate build source field")
        values[key] = value
    if values.get("product") != version or not re.fullmatch(r"[A-Za-z0-9._-]+", version):
        raise ValueError("build version differs from selected distribution")
    if set(SOURCE_NAMES) - set(values) or not all(COMMIT.fullmatch(values[key]) for key in SOURCE_NAMES):
        raise ValueError("incomplete build source commits")
    docker_commit = subprocess.check_output(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip()
    if values.get("cloudfile-docker") != docker_commit:
        raise ValueError("distribution was built with a different Docker recipe commit")
    return {key: values[key] for key in SOURCE_NAMES}


def stamp(package, version):
    package = Path(package)
    manifest_path = ROOT / "build/seafile_14.0/release.json"
    manifest = load_manifest(manifest_path)
    sources = build_sources(package, version)
    for name, commit in sources.items():
        if manifest["sources"][name]["ref"] != commit:
            raise ValueError("distribution differs from the locked release source: " + name)
    record = package / RECORD_NAME
    if record.exists() or record.is_symlink():
        result = verify_package(package, manifest_path)
    else:
        result = write_provenance(package, {"schema": 1, "manifest": manifest,
            "source_commits": sources}, manifest_path)
    return result["package_sha256"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("package")
    parser.add_argument("version")
    args = parser.parse_args()
    try:
        print(stamp(args.package, args.version))
    except (OSError, ValueError, subprocess.CalledProcessError):
        parser.exit(1, "CloudFile distribution source or byte verification failed\n")


if __name__ == "__main__":
    main()
