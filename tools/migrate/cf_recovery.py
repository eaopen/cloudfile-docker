#!/usr/bin/env python3
"""CloudFile V05-05: offline compose-volume snapshot and isolated restore.

This utility copies *stopped* local CE volumes. It cannot quiesce external S3
or external databases and MUST NOT be used as a consistent backup for them.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

KINDS = ("data/db", "data/seafile")
OPTIONAL = ("data/minio",)
BLOCK = 1024 * 1024


class RecoveryError(Exception):
    pass


def stopped(compose):
    if not (compose / "docker-compose.yml").is_file():
        raise RecoveryError("compose file is missing")
    try:
        p = subprocess.run(
            ["docker", "compose", "-f", "docker-compose.yml", "ps", "--status",
             "running", "--quiet"], cwd=compose, text=True, capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RecoveryError("cannot verify that all CloudFile services are stopped") from exc
    if p.returncode != 0 or p.stdout.strip():
        raise RecoveryError("CloudFile services may be running; stop ALL writers and retry")


def files(root):
    if root.is_symlink() or not root.is_dir():
        raise RecoveryError("missing or unsafe snapshot directory")
    for base, dirs, names in os.walk(root, followlinks=False):
        for name in dirs + names:
            node = Path(base) / name
            if node.is_symlink() or not (node.is_file() or node.is_dir()):
                raise RecoveryError("symbolic links and special files are unsupported")
        for name in sorted(names):
            yield Path(base) / name


def checksum(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while piece := stream.read(BLOCK):
            digest.update(piece)
    return digest.hexdigest()


def collect_manifest(root):
    entries = {}
    for path in files(root):
        rel = path.relative_to(root).as_posix()
        if rel != "manifest.json":
            entries[rel] = {"sha256": checksum(path), "bytes": path.stat().st_size}
    return entries


def check_manifest(snapshot):
    manifest_file = snapshot / "manifest.json"
    if manifest_file.is_symlink() or not manifest_file.is_file():
        raise RecoveryError("manifest is missing")
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    if manifest.get("schema") != "cloudfile.offline-compose.v1":
        raise RecoveryError("unsupported snapshot schema")
    actual = collect_manifest(snapshot)
    expected = manifest.get("files")
    if not isinstance(expected, dict) or actual != expected:
        raise RecoveryError("snapshot does not match checksums and file inventory")
    for name in KINDS:
        if not any(key.startswith(name + "/") for key in actual):
            raise RecoveryError("required volume has no files: " + name)
    return manifest


def copy_allowed(source, destination):
    destination.mkdir(mode=0o700)
    for name in KINDS + OPTIONAL:
        src = source / name
        if name in KINDS and not src.is_dir():
            raise RecoveryError("required compose volume missing: " + name)
        if src.exists():
            list(files(src))  # reject symlinks and unsupported nodes before copying
            shutil.copytree(src, destination / name, symlinks=False, copy_function=shutil.copy2)


def disjoint(source, destination):
    a, b = source.resolve(), destination.resolve()
    if a == b or a in b.parents or b in a.parents:
        raise RecoveryError("source and destination paths overlap")
    if destination.exists():
        raise RecoveryError("destination must not exist")


def backup(args):
    compose = Path(args.compose_root).resolve(strict=True)
    dest = Path(args.output).absolute()
    disjoint(compose, dest)
    stopped(compose)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".cf-snapshot-", dir=dest.parent) as tmp:
        stage = Path(tmp) / "snapshot"
        copy_allowed(compose, stage)
        if (compose / ".env").is_symlink():
            raise RecoveryError("compose .env must not be a symbolic link")
        if (compose / ".env").is_file():
            shutil.copy2(compose / ".env", stage / ".env")
        manifest = {"schema": "cloudfile.offline-compose.v1",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "mode": "stopped-local-compose-volumes",
                    "files": collect_manifest(stage)}
        (stage / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
        check_manifest(stage)
        stage.rename(dest)
    os.chmod(dest, 0o700)
    print(json.dumps({"result": "backup", "destination": str(dest),
                      "files": len(manifest["files"])}, ensure_ascii=False))


def restore(args):
    snapshot = Path(args.snapshot).resolve(strict=True)
    destination = Path(args.destination).absolute()
    disjoint(snapshot, destination)
    manifest = check_manifest(snapshot)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".cf-restore-", dir=destination.parent) as tmp:
        stage = Path(tmp) / "restore"
        stage.mkdir(mode=0o700)
        # The inventory was verified; copy only expected local volume trees.
        for name in KINDS + OPTIONAL:
            if (snapshot / name).is_dir():
                shutil.copytree(snapshot / name, stage / name, symlinks=False)
        if (snapshot / ".env").is_file():
            shutil.copy2(snapshot / ".env", stage / ".env")
        shutil.copy2(snapshot / "manifest.json", stage / "manifest.json")
        check_manifest(stage)
        stage.rename(destination)
    os.chmod(destination, 0o700)
    print(json.dumps({"result": "restored_offline_files", "destination": str(destination),
                      "files": len(manifest["files"])}, ensure_ascii=False))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Offline CloudFile CE volume snapshot (local compose only)")
    commands = parser.add_subparsers(dest="operation", required=True)
    b = commands.add_parser("backup")
    b.add_argument("--compose-root", required=True)
    b.add_argument("--output", required=True)
    b.add_argument("--ack-writers-stopped", action="store_true", required=True)
    b.set_defaults(func=backup)
    v = commands.add_parser("verify")
    v.add_argument("--snapshot", required=True)
    v.set_defaults(func=lambda x: print(json.dumps({"result": "verified", "files":
                         len(check_manifest(Path(x.snapshot))["files"])})))
    r = commands.add_parser("restore")
    r.add_argument("--snapshot", required=True)
    r.add_argument("--destination", required=True)
    r.add_argument("--ack-isolated-destination", action="store_true", required=True)
    r.set_defaults(func=restore)
    args = parser.parse_args(argv)
    try:
        args.func(args)
        return 0
    except (RecoveryError, ValueError, OSError, json.JSONDecodeError) as exc:
        print("cf-recovery: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
