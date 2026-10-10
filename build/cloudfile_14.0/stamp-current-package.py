#!/usr/bin/env python3
"""Bind a CE14 dev distribution to its actual built source commits and bytes."""

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "build/seafile_14.0"))
from package_provenance import (  # noqa: E402
    RECORD_NAME, load_manifest, verify_package, write_provenance,
)

READER_SPEC = importlib.util.spec_from_file_location("cloudfile_yaml_reader", ROOT / "build/cloudfile_14.0/read-manifest.py")
READER = importlib.util.module_from_spec(READER_SPEC)
READER_SPEC.loader.exec_module(READER)

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
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if values.get("cloudfile-docker") != docker_commit:
        raise ValueError("distribution was built with a different Docker recipe commit")
    return {key: values[key] for key in SOURCE_NAMES}


def current_manifest(sources):
    """Resolve release.yaml inputs without changing the locked release record."""
    configured = READER.load(ROOT / "release.yaml")
    manifest = load_manifest(ROOT / "build/seafile_14.0/release.json")
    manifest["seafile_version"] = configured["ce_anchor.version"][1:].split("-server")[0]
    for name, commit in sources.items():
        fork = {"seafile-server": "cloudfile_server", "seahub": "cloudfile_hub"}.get(name)
        if fork:
            checkout = ROOT.parent / name.replace("seafile-server", "cloudfile-server").replace("seahub", "cloudfile-hub")
            ref = configured["forks." + fork + ".ref"]
            manifest["sources"][name]["url"] = configured["forks." + fork + ".url"]
            # Incremental package CI has immutable inputs from the plan job,
            # but no matching checkout of each build source.
            plan_key = "CF_SERVER_REF" if name == "seafile-server" else "CF_HUB_REF"
            expected = os.environ.get(plan_key, "")
            if expected and not COMMIT.fullmatch(expected):
                raise ValueError("invalid immutable plan source: " + name)
        else:
            checkout = ROOT / "build/cloudfile_14.0/src" / name
            ref = configured["upstream." + name]
            expected = ref if COMMIT.fullmatch(ref) else ""
        if not expected:
            # Preserve local-building support for moving refs, but require
            # exact SHA equality when an immutable plan pin is supplied.
            expected = subprocess.check_output(
                ["git", "rev-parse", ref + "^{commit}"],
                cwd=checkout, text=True).strip()
        if expected != commit:
            raise ValueError("distribution differs from release.yaml input: " + name)
        manifest["sources"][name]["ref"] = commit
    return manifest


def stamp(package, version):
    package = Path(package)
    sources = build_sources(package, version)
    manifest = current_manifest(sources)
    # The locked release.json remains release evidence. This dev build gets
    # an independent immutable manifest and the same package-byte validation.
    with tempfile.TemporaryDirectory(prefix="cloudfile-provenance-") as temporary:
        manifest_path = Path(temporary) / "release.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
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
