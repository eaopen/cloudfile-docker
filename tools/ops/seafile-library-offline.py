#!/usr/bin/env python3
"""Read-only, service-independent Seafile library discovery and explicit export.

A library is stored in the standard Seafile object layout under either the
native data root or one managed per-library directory. No CloudFile SQL or Hub
API is consulted. Logical files are exported by the original seaf-fsck binary;
this tool never interprets Seafile Commit/FS/Block contents itself.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
from uuid import UUID

KINDS = ("commits", "fs", "blocks")
KEY = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,78}[a-z0-9])?\Z")


class LibraryError(Exception):
    pass


def repository_id(raw):
    try:
        value = UUID(raw)
    except (TypeError, ValueError, AttributeError) as exc:
        raise LibraryError("--repo-id must be a complete UUID") from exc
    if str(value) != raw:
        raise LibraryError("--repo-id must be a canonical lowercase UUID")
    return raw


def real_dir(path):
    """Require mounted roots; never treat an explicitly supplied missing mount as absent."""
    path = Path(path)
    if not path.is_absolute():
        raise LibraryError("storage roots must be absolute")
    try:
        root = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise LibraryError("storage root is not accessible") from exc
    if not root.is_dir():
        raise LibraryError("storage root must be a directory")
    return root


def physical_dir(path):
    """Return true only for a real directory, never a symlink (no mutation)."""
    try:
        return stat.S_ISDIR(path.lstat().st_mode)
    except FileNotFoundError:
        return False


def candidate(root, repo_id, backend, key=None):
    if root is None:
        return None
    base = root / "storage"
    if not physical_dir(base):
        return None
    commit_parent = base / "commits"
    if not physical_dir(commit_parent):
        return None
    commits = commit_parent / repo_id
    if not physical_dir(commits):
        return None
    paths = {}
    for kind in KINDS:
        parent = base / kind
        if parent.exists() or parent.is_symlink():
            if not physical_dir(parent):
                raise LibraryError("unsafe Seafile object parent for " + kind)
        path = parent / repo_id
        if path.exists() or path.is_symlink():
            if not physical_dir(path):
                raise LibraryError("unsafe Seafile library object directory for " + kind)
            paths[kind] = str(path)
        else:
            paths[kind] = None  # A newly created/empty library can omit fs/blocks.
    return {"repo_id": repo_id, "backend": backend, "repo_key": key,
            "seafile_data_root": str(root), "object_dirs": paths}


def find_library(repo_id, native_root, managed_root):
    repo_id = repository_id(repo_id)
    native = real_dir(native_root)
    managed = real_dir(managed_root) if managed_root is not None else None
    if managed is not None and Path(managed_root).is_symlink():
        raise LibraryError("managed parent must not be a symbolic link")
    found = []
    item = candidate(native, repo_id, "seafile-native")
    if item is not None:
        found.append(item)
    if managed is not None:
        for child in sorted(managed.iterdir()):
            if not KEY.fullmatch(child.name):
                continue
            if not physical_dir(child):
                continue  # Never traverse links masquerading as libraries.
            item = candidate(child, repo_id, "auto-local", child.name)
            if item is not None:
                found.append(item)
    if not found:
        raise LibraryError("repo_id was not found in the native or managed object directories")
    if len(found) != 1:
        raise LibraryError("ambiguous repo_id in multiple physical stores; inspect manually")
    return found[0]


def output_directory(raw, sources):
    target = Path(raw)
    if not target.is_absolute():
        raise LibraryError("export destination must be an absolute path")
    if target.exists() or target.is_symlink():
        raise LibraryError("export destination already exists; overwrite is not supported")
    parent = target.parent.resolve(strict=True)
    if not parent.is_dir() or not physical_dir(parent):
        raise LibraryError("export destination parent must be a real existing directory")
    dest = parent / target.name
    for root in sources:
        source = Path(root).resolve()
        if source == dest or source in dest.parents or dest in source.parents:
            raise LibraryError("export directory must not overlap an object storage root")
    return dest


def export_library(args):
    item = find_library(args.repo_id, args.seafile_data, args.library_root)
    fsck = Path(args.seaf_fsck)
    if not fsck.is_absolute() or not fsck.is_file() or not os.access(fsck, os.X_OK):
        raise LibraryError("--seaf-fsck must name an executable Seafile fsck binary")
    roots = (args.seafile_data,) + ((args.library_root,) if args.library_root else ())
    target = output_directory(args.output_dir, roots)
    # Temp staging lives on the destination volume, not in /tmp and not in the
    # object store. Failed export is deleted; no target is published on error.
    with tempfile.TemporaryDirectory(prefix=".seafile-export-", dir=target.parent) as temporary:
        sandbox = Path(temporary)
        data = sandbox / "seafile-data"
        conf = sandbox / "conf"
        out = sandbox / "out"
        conf.mkdir()
        (data / "tmpfiles").mkdir(parents=True)
        out.mkdir()
        (conf / "seafile.conf").write_text(
            "[commit_object_backend]\nname = filesystem\n"
            "[fs_object_backend]\nname = filesystem\n"
            "[block_backend]\nname = filesystem\n", encoding="utf-8")
        for kind in KINDS:
            parent = data / "storage" / kind
            parent.mkdir(parents=True)
            original = item["object_dirs"][kind]
            target_dir = parent / item["repo_id"]
            if original is not None:
                target_dir.symlink_to(original, target_is_directory=True)
            else:
                target_dir.mkdir()  # No source-tree writes for an empty kind.
        # Stock Seafile CE filesystem routing, without cloudfile_v2 or a DB.
        command = [str(fsck), "-c", str(conf), "-d", str(data), "-F", str(conf),
                   "--export", str(out), item["repo_id"]]
        # Native export may print thousands of file messages; do not keep all
        # of them in RAM just to report the last error if it fails.
        with tempfile.TemporaryFile(dir=sandbox) as output_log:
            result = subprocess.run(command, cwd=sandbox, stdout=output_log,
                                    stderr=subprocess.STDOUT)
            if result.returncode != 0:
                output_log.seek(0, os.SEEK_END)
                length = output_log.tell()
                output_log.seek(max(0, length - 2048))
                tail = output_log.read().decode("utf-8", "replace")
                raise LibraryError("seaf-fsck export failed: " + tail[-1500:])
            # CE's export_file()/create_file() can log a per-file write error
            # yet return 0 after exporting the other files. Never publish
            # such a partial result as success. Scan the explicit export log
            # incrementally, not into memory, and keep the native reader.
            output_log.seek(0)
            for line in output_log:
                if (b"Failed to export file " in line or
                        b"Failed to mkdir " in line or
                        b"Failed to open block " in line):
                    raise LibraryError("seaf-fsck reported an incomplete export; "
                                       "no destination was published")
        children = list(out.iterdir())
        if len(children) != 1 or not physical_dir(children[0]) or \
                not children[0].name.startswith(item["repo_id"][:8] + "_"):
            raise LibraryError("seaf-fsck did not produce exactly one library export "
                               "(encrypted, empty/corrupt or unsupported library)")
        # Only the requested repo's result is published. No source bytes are
        # copied by inspect and no bulk backup is ever implicit.
        if target.exists() or target.is_symlink():
            raise LibraryError("export destination was created concurrently")
        target.mkdir(mode=0o700)  # Atomic no-overwrite reservation.
        try:
            children[0].rename(target / children[0].name)
        except Exception:
            target.rmdir()
            raise
    return {"action": "export", "repo_id": item["repo_id"],
            "backend": item["backend"], "export_dir": str(target),
            "status": "EXPORTED_UNVERIFIED",
            "warning": "Export is not a database backup or proof of full source integrity; "
                       "run verify-export explicitly when needed."}


def verify_export(args):
    repo_id = repository_id(args.repo_id)
    root = real_dir(args.output_dir)
    libraries = list(root.iterdir())
    if len(libraries) != 1 or not physical_dir(libraries[0]) or \
            not libraries[0].name.startswith(repo_id[:8] + "_"):
        raise LibraryError("export directory must contain one library matching repo_id")
    base = libraries[0]
    count = 0
    total = 0
    digest = hashlib.sha256() if args.hash else None
    for here, directories, names in os.walk(base, followlinks=False):
        # Canonical order: os.walk descends in readdir order, so a tree digest
        # would differ between identical exports on another filesystem/copy
        # unless directory order is pinned before recursing.
        directories.sort()
        for name in directories:
            if not physical_dir(Path(here) / name):
                raise LibraryError("export contains symlink or unsupported directory")
        for name in sorted(names):
            p = Path(here) / name
            if not stat.S_ISREG(p.lstat().st_mode):
                raise LibraryError("export contains symlink or non-regular file")
            count += 1
            total += p.stat().st_size
            if digest is not None:
                relative = p.relative_to(base).as_posix().encode("utf-8")
                digest.update(len(relative).to_bytes(4, "big") + relative)
                filehash = hashlib.sha256()
                with p.open("rb") as stream:
                    for piece in iter(lambda: stream.read(1024 * 1024), b""):
                        filehash.update(piece)
                digest.update(filehash.digest())
    return {"action": "verify-export", "repo_id": repo_id, "export_dir": str(root),
            "file_count": count, "total_bytes": total, "tree_sha256": digest.hexdigest() if digest else None,
            "note": "Local export inventory and readability only; source completeness is not proven."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    for op in ("inspect", "export", "verify-export"):
        cli = commands.add_parser(op)
        cli.add_argument("--repo-id", required=True, help="one exact Seafile UUID; never all libraries")
        if op != "verify-export":
            cli.add_argument("--seafile-data", required=True, help="absolute path to native seafile-data")
            cli.add_argument("--library-root", help="existing absolute managed root; omit for native CE only")
        if op == "export":
            cli.add_argument("--seaf-fsck", required=True, help="absolute path to native seaf-fsck executable")
            cli.add_argument("--output-dir", required=True, help="unused absolute destination directory")
        if op == "verify-export":
            cli.add_argument("--output-dir", required=True, help="absolute prior export directory")
            cli.add_argument("--hash", action="store_true", help="explicitly hash all exported file bytes")
    args = parser.parse_args(argv)
    try:
        if args.action == "inspect":
            result = {"action": "inspect", "status": "FOUND", **find_library(args.repo_id, args.seafile_data, args.library_root)}
        elif args.action == "export":
            result = export_library(args)
        else:
            result = verify_export(args)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (LibraryError, OSError, subprocess.SubprocessError) as exc:
        print("seafile-library-offline: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
