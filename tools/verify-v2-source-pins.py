#!/usr/bin/env python3
"""Fail closed when the CloudFile 2.0 source snapshot drifts across repositories."""
import argparse
from pathlib import Path
import re
import runpy
import subprocess
import sys

HEX_SHA = re.compile(r"[0-9a-f]{40}\\Z")
SOURCES = {
    "cloudfile_server": "cloudfile-server",
    "cloudfile_hub": "cloudfile-hub",
}


def verify(manifest, workspace):
    root = Path(__file__).resolve().parents[1]
    read = runpy.run_path(str(root / "build/cloudfile_14.0/read-manifest.py"))["load"]
    values = read(str(manifest))
    errors = []
    pins = {}
    for key, directory in SOURCES.items():
        ref = values.get(f"forks.{key}.ref", "")
        if not HEX_SHA.fullmatch(ref):
            errors.append(f"{key} must have an immutable 40-char source SHA")
            continue
        path = Path(workspace) / directory
        if not (path / ".git").exists():
            errors.append(f"{directory} git checkout unavailable")
            continue
        try:
            sha = subprocess.check_output(
                ["git", "-C", str(path), "rev-parse", "HEAD^{commit}"],
                text=True, stderr=subprocess.DEVNULL,
            ).strip()
        except (OSError, subprocess.CalledProcessError):
            errors.append(f"{directory} cannot resolve HEAD")
            continue
        if sha != ref:
            errors.append(f"{directory} checkout {sha} does not match pinned {ref}")
        else:
            pins[key] = sha
    if errors:
        raise ValueError("; ".join(errors))
    return pins


def main(argv=None):
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=root / "release.yaml")
    parser.add_argument("--workspace", type=Path, default=root.parent)
    args = parser.parse_args(argv)
    try:
        pins = verify(args.manifest, args.workspace)
    except (ValueError, OSError) as error:
        print(f"CloudFile 2.0 source pins invalid: {error}", file=sys.stderr)
        return 1
    for key, sha in pins.items():
        print(f"{key}={sha}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
