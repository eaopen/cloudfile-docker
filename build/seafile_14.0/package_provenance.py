#!/usr/bin/env python3
"""Bind a completed native package to captured sources and its installed bytes."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess

from source_manifest import load_manifest


RECORD_NAME = "cloudfile-build.json"
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
REQUIRED_FILES = (
    "seafile/bin/seaf-server", "seafile/bin/fileserver", "seafile/bin/seaf-fuse",
    "seafile/lib/libcloudfile_acl.so.1", "seahub/cloudfile_extensions/apps.py",
)


def _git(source, *arguments):
    result = subprocess.run(["git", "-C", str(source), *arguments],
                            capture_output=True, text=True, check=False)
    if result.returncode:
        raise ValueError("package source Git validation failed")
    return result.stdout.strip()


def capture_sources(manifest_path, source_root):
    manifest = load_manifest(manifest_path)
    commits = {}
    for name, configured in manifest["sources"].items():
        pin = configured["ref"]
        if not COMMIT_RE.fullmatch(pin):
            raise ValueError("package sources require immutable commit pins")
        source = Path(source_root) / name
        if Path(_git(source, "rev-parse", "--show-toplevel")).resolve() != source.resolve():
            raise ValueError("package source must be its own checkout root")
        commit = _git(source, "rev-parse", "HEAD")
        if commit != pin:
            raise ValueError("package source HEAD differs from the release pin: " + name)
        if _git(source, "status", "--porcelain", "--untracked-files=normal"):
            raise ValueError("package source has modifications or untracked files: " + name)
        commits[name] = commit
    return {"schema": 1, "manifest": manifest, "source_commits": commits}


def package_digest(package):
    package = Path(package)
    if not package.is_dir() or package.is_symlink():
        raise ValueError("native package must be a real directory")
    for name in REQUIRED_FILES:
        path = package / name
        if not path.is_file() or path.is_symlink():
            raise ValueError("native package is missing a required installed file: " + name)
    digest = hashlib.sha256()
    # Include directory entries, executability, file bytes and symlink targets.
    # Never follow directory symlinks outside the packaged tree.
    for directory, directories, files in os.walk(package, followlinks=False):
        for name in sorted(directories + files):
            path = Path(directory) / name
            relative = path.relative_to(package).as_posix()
            if relative == RECORD_NAME:
                continue
            entry = path.lstat()
            mode = stat.S_IMODE(entry.st_mode)
            if stat.S_ISLNK(entry.st_mode):
                value = [relative, "symlink", mode, os.readlink(path)]
            elif stat.S_ISDIR(entry.st_mode):
                value = [relative, "directory", mode]
            elif stat.S_ISREG(entry.st_mode):
                content = hashlib.sha256()
                with path.open("rb") as source:
                    while True:
                        block = source.read(1024 * 1024)
                        if not block:
                            break
                        content.update(block)
                after = path.stat()
                if (entry.st_size, entry.st_mtime_ns, entry.st_ino) != (
                        after.st_size, after.st_mtime_ns, after.st_ino):
                    raise ValueError("native package changed during validation")
                value = [relative, "file", mode, entry.st_size, content.hexdigest()]
            else:
                raise ValueError("native package contains a special file")
            digest.update(json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode() + b"\n")
        directories.sort()
    return digest.hexdigest()


def _validate_sources(record, manifest):
    if (not isinstance(record, dict) or type(record.get("schema")) is not int or record.get("schema") != 1
            or record.get("manifest") != manifest):
        raise ValueError("native package provenance differs from the release manifest")
    commits = record.get("source_commits")
    if not isinstance(commits, dict) or set(commits) != set(manifest["sources"]):
        raise ValueError("native package provenance has an incomplete source set")
    for name, configured in manifest["sources"].items():
        if (not isinstance(commits[name], str) or not COMMIT_RE.fullmatch(commits[name])
                or commits[name] != configured["ref"]):
            raise ValueError("native package provenance has an incorrect source commit")


def write_provenance(package, captured, manifest_path):
    manifest = load_manifest(manifest_path)
    _validate_sources(captured, manifest)
    record = {**captured, "package_sha256": package_digest(package)}
    target = Path(package) / RECORD_NAME
    if target.exists() or target.is_symlink():
        raise ValueError("native package already has provenance; rebuild rather than restamp")
    with target.open("x", encoding="utf-8") as output:
        json.dump(record, output, sort_keys=True, indent=2)
        output.write("\n")
    return record


def verify_package(package, manifest_path):
    manifest = load_manifest(manifest_path)
    target = Path(package) / RECORD_NAME
    if not target.is_file() or target.is_symlink():
        raise ValueError("native package lacks build provenance; rebuild before image assembly")
    if target.stat().st_size > 65536:
        raise ValueError("native package provenance is oversized")
    with target.open(encoding="utf-8") as source:
        record = json.load(source)
    _validate_sources(record, manifest)
    if record.get("package_sha256") != package_digest(package):
        raise ValueError("native package content differs from its build provenance")
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("package")
    parser.add_argument("manifest")
    args = parser.parse_args()
    try:
        record = verify_package(args.package, args.manifest)
    except (ValueError, OSError):
        parser.exit(1, "Native package validation failed; rebuild from the locked sources.\n")
    print(record["package_sha256"])


if __name__ == "__main__":
    main()
