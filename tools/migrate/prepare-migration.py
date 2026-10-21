#!/usr/bin/env python3
"""Build an isolated CLI worktree from selected source directories."""

import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import time
from uuid import uuid4


CHUNK_SIZE = 1024 * 1024
DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate mapping field")
        result[key] = value
    return result


def parts(path, *, target):
    if not isinstance(path, str) or not path or "\x00" in path:
        raise ValueError("mapping paths must be nonempty strings")
    if target:
        if not path.startswith("/"):
            raise ValueError("target must be an absolute library path")
        if path == "/":
            return ()
        path = path[1:]
    elif path == ".":
        return ()
    elif path.startswith("/"):
        raise ValueError("source must be relative to the registered root")
    components = tuple(path.split("/"))
    if any(component in ("", ".", "..") or "\\" in component for component in components):
        raise ValueError("mapping path contains an invalid component")
    if len(components) > 128 or len(path.encode("utf-8")) + 1 > 4096:
        raise ValueError("mapping path exceeds the supported limit")
    return components


def read_mapping(path):
    with open(path, "rb") as stream:
        raw = stream.read(65537)
    if len(raw) > 65536:
        raise ValueError("mapping file exceeds 64 KiB")
    document = json.loads(raw.decode("utf-8"), object_pairs_hook=reject_duplicate_keys)
    if not isinstance(document, dict) or set(document) != {"version", "mappings"} or document["version"] != 1:
        raise ValueError("mapping file must contain version 1 and mappings")
    mappings = document["mappings"]
    if not isinstance(mappings, list) or not 1 <= len(mappings) <= 64:
        raise ValueError("mapping file must contain 1 to 64 entries")
    parsed = []
    for item in mappings:
        if not isinstance(item, dict) or set(item) != {"source", "target"}:
            raise ValueError("each mapping needs source and target")
        parsed.append((parts(item["source"], target=False), parts(item["target"], target=True)))
    for index, (source, target) in enumerate(parsed):
        for other_source, other_target in parsed[:index]:
            for left, right in ((source, other_source), (target, other_target)):
                folded_left = tuple(component.casefold() for component in left)
                folded_right = tuple(component.casefold() for component in right)
                if folded_left[:len(folded_right)] == folded_right or folded_right[:len(folded_left)] == folded_left:
                    raise ValueError("mapping source or target directories overlap")
    return parsed


def open_directory(root, components):
    descriptor = os.dup(root)
    try:
        for component in components:
            child = os.open(component, DIRECTORY_FLAGS, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def flush_volume(path):
    syncfs = getattr(ctypes.CDLL(None, use_errno=True), "syncfs", None)
    if syncfs is None:
        raise ValueError("volume durability requires Linux syncfs")
    syncfs.argtypes = [ctypes.c_int]
    syncfs.restype = ctypes.c_int
    descriptor = os.open(path, DIRECTORY_FLAGS)
    try:
        if syncfs(descriptor) != 0:
            raise OSError(ctypes.get_errno(), "syncfs failed")
    finally:
        os.close(descriptor)


def build(source_root, output_root, mappings, *, durability="file"):
    started = time.monotonic()
    if durability not in ("file", "volume"):
        raise ValueError("durability must be file or volume")
    if durability == "volume" and sys.platform != "linux":
        raise ValueError("volume durability requires Linux")
    source = Path(source_root)
    output = Path(output_root)
    if not source.is_absolute() or not output.is_absolute() or output.exists() or output.is_symlink():
        raise ValueError("absolute source and unused absolute output paths are required")
    real_source = source.resolve(strict=True)
    real_parent = output.parent.resolve(strict=True)
    real_output = real_parent / output.name
    if real_source == real_output or real_source in real_output.parents or real_output in real_source.parents:
        raise ValueError("source and output trees must not overlap")
    working = output.with_name(output.name + ".incomplete-" + uuid4().hex)
    source_fd = os.open(source, DIRECTORY_FLAGS)
    try:
        # Validate every selection before creating any output.
        for selected, _ in mappings:
            os.close(open_directory(source_fd, selected))
        working.mkdir(mode=0o700)
        private = working / ".cf-migration"
        private.mkdir(mode=0o700)
        incomplete = private / "incomplete"
        incomplete.touch(mode=0o600)
        data = working / "data"
        data.mkdir(mode=0o700)
        counts = {"files": 0, "directories": 0, "bytes": 0}
        manifest_hash = hashlib.sha256()

        with (private / "manifest.ndjson").open("xb") as manifest:
            def record(value):
                encoded = (json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
                manifest.write(encoded)
                manifest_hash.update(encoded)

            def copy_directory(source_dir, target_dir, prefix, depth):
                if depth > 128:
                    raise ValueError("source directory exceeds depth limit")
                before_dir = os.fstat(source_dir)
                with os.scandir(source_dir) as entries:
                    for entry in entries:
                        name = entry.name
                        relative = prefix + name
                        if len(relative.encode("utf-8")) + 1 > 4096:
                            raise ValueError("source path exceeds the supported limit")
                        before = entry.stat(follow_symlinks=False)
                        if stat.S_ISDIR(before.st_mode):
                            child_source = os.open(name, DIRECTORY_FLAGS, dir_fd=source_dir)
                            try:
                                observed = os.fstat(child_source)
                                if (observed.st_dev, observed.st_ino) != (before.st_dev, before.st_ino):
                                    raise ValueError("source directory changed during preparation")
                                os.mkdir(name, mode=0o700, dir_fd=target_dir)
                                child_target = os.open(name, DIRECTORY_FLAGS, dir_fd=target_dir)
                                try:
                                    counts["directories"] += 1
                                    record({"path": relative, "kind": "directory"})
                                    copy_directory(child_source, child_target, relative + "/", depth + 1)
                                finally:
                                    os.close(child_target)
                            finally:
                                os.close(child_source)
                        elif stat.S_ISREG(before.st_mode):
                            input_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=source_dir)
                            try:
                                observed = os.fstat(input_fd)
                                if not stat.S_ISREG(observed.st_mode) or (observed.st_dev, observed.st_ino) != (before.st_dev, before.st_ino):
                                    raise ValueError("source file changed during preparation")
                                output_fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=target_dir)
                                digest = hashlib.sha256()
                                size = 0
                                try:
                                    while chunk := os.read(input_fd, CHUNK_SIZE):
                                        digest.update(chunk)
                                        size += len(chunk)
                                        view = memoryview(chunk)
                                        while view:
                                            written = os.write(output_fd, view)
                                            if written == 0:
                                                raise OSError("copy stopped making progress")
                                            view = view[written:]
                                    if durability == "file":
                                        os.fsync(output_fd)
                                finally:
                                    os.close(output_fd)
                                after = os.fstat(input_fd)
                                if (observed.st_size, observed.st_mtime_ns, observed.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns) or size != observed.st_size:
                                    raise ValueError("source file changed during preparation")
                                counts["files"] += 1
                                counts["bytes"] += size
                                record({"path": relative, "kind": "file", "size": size, "sha256": digest.hexdigest()})
                            finally:
                                os.close(input_fd)
                        else:
                            raise ValueError("source contains a link or special file")
                after_dir = os.fstat(source_dir)
                if (before_dir.st_mtime_ns, before_dir.st_ctime_ns) != (after_dir.st_mtime_ns, after_dir.st_ctime_ns):
                    raise ValueError("source directory changed during preparation")
                os.fsync(target_dir)

            target_root = os.open(data, DIRECTORY_FLAGS)
            try:
                for selected, destination in mappings:
                    selected_fd = open_directory(source_fd, selected)
                    destination_fd = os.dup(target_root)
                    try:
                        prefix = ""
                        for component in destination:
                            prefix += component + "/"
                            try:
                                os.mkdir(component, mode=0o700, dir_fd=destination_fd)
                                counts["directories"] += 1
                                record({"path": prefix[:-1], "kind": "directory"})
                            except FileExistsError:
                                pass
                            child = os.open(component, DIRECTORY_FLAGS, dir_fd=destination_fd)
                            os.close(destination_fd)
                            destination_fd = child
                        copy_directory(selected_fd, destination_fd, prefix, len(destination))
                    finally:
                        os.close(destination_fd)
                        os.close(selected_fd)
                os.fsync(target_root)
            finally:
                os.close(target_root)
            if counts["files"] == 0 and counts["directories"] == 0:
                raise ValueError("selection is empty")
            manifest.flush()
            os.fsync(manifest.fileno())

        if durability == "volume":
            flush_volume(working)

        normalized = [{"source": "." if not src else "/".join(src), "target": "/" + "/".join(dst)} for src, dst in mappings]
        identity = hashlib.sha256(json.dumps({"mappings": normalized, "manifest_sha256": manifest_hash.hexdigest()},
                                      ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        summary = {"version": 1, "selection_id": identity, "manifest_sha256": manifest_hash.hexdigest(),
                   "mappings": normalized, **counts}
        selection = private / "selection.json"
        with selection.open("x", encoding="utf-8") as stream:
            json.dump(summary, stream, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        incomplete.unlink()
        for directory in (private, data, working):
            descriptor = os.open(directory, DIRECTORY_FLAGS)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        os.rename(working, output)
        parent_fd = os.open(output.parent, DIRECTORY_FLAGS)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
        return {**summary, "prepare_seconds": round(time.monotonic() - started, 3)}
    finally:
        os.close(source_fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--mapping-file", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--durability", choices=("file", "volume"), default="file",
                        help="file fsyncs each copied file; volume uses one Linux syncfs before publishing")
    args = parser.parse_args()
    try:
        result = build(args.source_root, args.output_root, read_mapping(args.mapping_file), durability=args.durability)
    except (OSError, ValueError, UnicodeError) as error:
        print("Migration preparation failed: " + str(error), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
