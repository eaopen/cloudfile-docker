#!/usr/bin/env python3
"""Validate the private preparation evidence before binding a CLI worktree."""

import hashlib
import json
import os
import re
import sys


def inspect(root):
    private = os.open(os.path.join(root, ".cf-migration"), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        if os.path.exists(os.path.join(root, ".cf-migration", "incomplete")):
            raise ValueError("prepared worktree is incomplete")
        selection_fd = os.open("selection.json", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=private)
        with os.fdopen(selection_fd, "rb") as stream:
            raw = stream.read(65537)
        if len(raw) > 65536:
            raise ValueError("selection record exceeds limit")
        selection = json.loads(raw)
        if (not isinstance(selection, dict) or selection.get("version") != 1 or
                not isinstance(selection.get("mappings"), list) or
                not isinstance(selection.get("manifest_sha256"), str) or
                not re.fullmatch(r"[0-9a-f]{64}", selection["manifest_sha256"])):
            raise ValueError("invalid selection record")
        digest = hashlib.sha256()
        manifest_fd = os.open("manifest.ndjson", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=private)
        with os.fdopen(manifest_fd, "rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        if digest.hexdigest() != selection["manifest_sha256"]:
            raise ValueError("selection manifest changed")
        identity = hashlib.sha256(json.dumps({"mappings": selection["mappings"],
            "manifest_sha256": selection["manifest_sha256"]}, ensure_ascii=False,
            sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        if identity != selection.get("selection_id"):
            raise ValueError("selection identity changed")
        data = os.open(os.path.join(root, "data"), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        os.close(data)
        return identity
    finally:
        os.close(private)


if __name__ == "__main__":
    try:
        print(inspect(sys.argv[1]))
    except (OSError, ValueError, KeyError, IndexError, UnicodeError) as error:
        print("Invalid migration selection: " + str(error), file=sys.stderr)
        sys.exit(2)
