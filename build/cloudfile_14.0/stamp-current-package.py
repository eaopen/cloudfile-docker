#!/usr/bin/env python3
"""Verify installed package bytes exclusively against its build receipt."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "build/seafile_14.0"))
from build_receipt import load_receipt, verify_recipe
from package_provenance import verify_package

SOURCE_NAMES = ("seafile-server", "seahub", "seafobj", "seafdav", "seafevents", "libsearpc", "libevhtp")
COMMIT = re.compile(r"[0-9a-f]{40}\Z")


def build_sources(package, version):
    info = Path(package) / "cloudfile-build-info.txt"
    if not info.is_file() or info.is_symlink() or info.stat().st_size > 4096:
        raise ValueError("missing immutable build source record")
    values = {}
    for line in info.read_text().splitlines():
        key, separator, value = line.partition(": ")
        if not separator or key in values:
            raise ValueError("invalid or duplicate build source field")
        values[key] = value
    if values.get("product") != version:
        raise ValueError("build version differs from selected distribution")
    for name in (*SOURCE_NAMES, "cloudfile-docker"):
        if not COMMIT.fullmatch(values.get(name, "")):
            raise ValueError("incomplete build source commits")
    return values


def stamp(package, version, receipt_path=None):
    receipt_path = Path(receipt_path or os.environ.get("CF_BUILD_RECEIPT", ROOT / "build/cloudfile_14.0/build-receipt.json"))
    receipt = load_receipt(receipt_path)
    verify_recipe(receipt, ROOT)
    if receipt["version"] != version:
        raise ValueError("receipt version differs from distribution")
    values = build_sources(package, version)
    if values["cloudfile-docker"] != receipt["lock"]["docker_commit"]:
        raise ValueError("distribution has a different Docker source commit")
    for name, source in receipt["lock"]["sources"].items():
        if values[name] != source["ref"]:
            raise ValueError("distribution differs from build receipt: " + name)
    return verify_package(package, receipt_path)["package_sha256"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("package")
    parser.add_argument("version")
    parser.add_argument("--receipt")
    args = parser.parse_args()
    try:
        print(stamp(args.package, args.version, args.receipt))
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, "CloudFile receipt or byte verification failed: %s\n" % error)


if __name__ == "__main__":
    main()
