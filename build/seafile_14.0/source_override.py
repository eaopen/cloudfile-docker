#!/usr/bin/env python3
"""Validate a local source checkout used for an unpublished CloudFile build."""

import argparse
import re
import subprocess
from pathlib import Path


COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


def _git(source, *arguments):
    result = subprocess.run(
        ("git", "-C", str(source), *arguments),
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or "git command failed"
        raise ValueError(detail)
    return result.stdout.strip()


def validate_override(path, expected_commit):
    """Require an exact, clean checkout so local builds remain reproducible."""
    source = Path(path)
    if not source.is_absolute():
        raise ValueError("local source override must be an absolute path")
    if not source.is_dir():
        raise ValueError("local source override directory does not exist")
    if not COMMIT_RE.fullmatch(expected_commit):
        raise ValueError("local source override requires a 40-character commit pin")

    checkout_root = Path(_git(source, "rev-parse", "--show-toplevel")).resolve()
    if checkout_root != source.resolve():
        raise ValueError("local source override must point to the checkout root")
    actual_commit = _git(source, "rev-parse", "HEAD")
    if actual_commit != expected_commit:
        raise ValueError(
            f"local source HEAD {actual_commit} does not match release pin {expected_commit}"
        )
    if _git(source, "status", "--porcelain", "--untracked-files=normal"):
        raise ValueError("local source override must have a clean worktree")
    return source.resolve()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    parser.add_argument("expected_commit")
    arguments = parser.parse_args()
    print(validate_override(arguments.path, arguments.expected_commit))


if __name__ == "__main__":
    main()
