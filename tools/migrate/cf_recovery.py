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
    # Validate the effective Compose mounts, not a guess from .env.
    # This legacy copier only understands two local bind sources.
    try:
        resolved = subprocess.run(
            ["docker", "compose", "-f", "docker-compose.yml", "config", "--format", "json"],
            cwd=compose, text=True, capture_output=True, timeout=30)
        if resolved.returncode:
            raise RecoveryError("cannot resolve effective Compose mounts")
        services = json.loads(resolved.stdout)["services"]
        for service, target, source in (
            ("db", "/var/lib/mysql", "data/db"),
            ("cloudfile", "/shared", "data/seafile"),
            ("cf-worker", "/shared", "data/seafile"),
        ):
            mounts = [entry for entry in services[service]["volumes"]
                      if entry.get("target") == target]
            if len(mounts) != 1 or mounts[0].get("type") != "bind" or (
                    Path(mounts[0]["source"]).resolve() != (compose / source).resolve()):
                raise RecoveryError("effective Compose mount differs from legacy backup scope")
        p = subprocess.run(
            ["docker", "compose", "-f", "docker-compose.yml", "ps", "--status",
             "running", "--quiet"], cwd=compose, text=True, capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError) as exc:
        raise RecoveryError("cannot verify effective mounts or stopped services") from exc
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


def reject_unsupported_bulk_backup(compose, legacy_ce_only):
    """This legacy full-instance copier never backs up V2 per-library objects.

    Running this on auto-local could produce a misleading 'successful' archive.
    Always require an explicit legacy-only acknowledgement; no implicit scan or
    copy of all libraries is permitted.
    """
    if not legacy_ce_only:
        raise RecoveryError("whole-instance backup requires --legacy-ce-only; "
                            "use seafile-library-offline.py for a selected repo_id")
    # -f docker-compose.yml below intentionally supports only the baseline.
    # Refuse custom project overlays rather than quietly copy the wrong paths.
    requested_compose = os.environ.get("COMPOSE_FILE", "")
    if requested_compose and requested_compose not in ("docker-compose.yml", "./docker-compose.yml"):
        raise RecoveryError("custom COMPOSE_FILE cannot use legacy backup")
    managed = compose / "data/libraries"
    if managed.is_symlink() or (managed.is_dir() and any(managed.iterdir())):
        raise RecoveryError("V2 per-library objects are outside the legacy backup scope")
    if os.environ.get("CF_LIBRARY_STORAGE") == "auto":
        raise RecoveryError("CF_LIBRARY_STORAGE=auto is not a legacy CE installation")
    if os.environ.get("SEAF_SERVER_STORAGE_TYPE") == "multiple" or os.environ.get("CF_ENABLE_S3_STORAGE", "").lower() == "true":
        raise RecoveryError("S3/multiple storage cannot use legacy local-only backup")
    environment = compose / ".env"
    if environment.is_symlink():
        raise RecoveryError("compose .env must not be a symbolic link")
    if environment.is_file():
        for entry in environment.read_text(encoding="utf-8").splitlines():
            name, separator, value = entry.strip().partition("=")
            value = value.strip().strip("'\"")
            if separator and name.strip() == "COMPOSE_FILE" and value not in ("", "docker-compose.yml", "./docker-compose.yml"):
                raise RecoveryError("custom COMPOSE_FILE cannot use legacy backup")
            if separator and name.strip() == "CF_LIBRARY_STORAGE" and value == "auto":
                raise RecoveryError("persisted V2 auto-local mode is not a legacy CE installation")
            if separator and ((name.strip() == "SEAF_SERVER_STORAGE_TYPE" and value == "multiple") or
                              (name.strip() == "CF_ENABLE_S3_STORAGE" and value.lower() == "true")):
                raise RecoveryError("persisted S3/multiple storage is not a legacy CE backup")
    # Known CE14 Compose config locations. Unrecognized external data roots
    # are outside the contract of this explicitly acknowledged legacy tool.
    for relative in ("data/seafile/seafile/conf/seafile.conf",
                     "data/seafile/conf/seafile.conf"):
        conf = compose / relative
        if conf.is_file():
            from configparser import ConfigParser, Error as ConfigError
            cfg = ConfigParser(interpolation=None)
            try:
                cfg.read(conf)
                if cfg.has_option("cloudfile_v2", "auto_local_root"):
                    raise RecoveryError("V2 per-library root is not in the legacy backup scope")
                if cfg.getboolean("storage", "enable_storage_classes", fallback=False):
                    raise RecoveryError("storage classes are not supported by legacy local-only backup")
                for section in ("commit_object_backend", "fs_object_backend", "block_backend"):
                    if cfg.get(section, "name", fallback="") in ("s3", "multiple"):
                        raise RecoveryError("S3/multiple backend is not a legacy local-only backup")
            except (ValueError, ConfigError) as exc:
                raise RecoveryError("invalid Seafile storage config: " + str(exc)) from exc


def backup(args):
    compose = Path(args.compose_root).resolve(strict=True)
    dest = Path(args.output).absolute()
    disjoint(compose, dest)
    reject_unsupported_bulk_backup(compose, getattr(args, 'legacy_ce_only', False))
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
    b.add_argument("--legacy-ce-only", action="store_true", required=True,
                   help="explicitly acknowledge this is a full-instance legacy CE volume snapshot")
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
