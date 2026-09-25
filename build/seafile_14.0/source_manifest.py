#!/usr/bin/env python3
"""Validate and query the reproducible CloudFile source manifest."""

import argparse
import json
import re
from pathlib import Path
from urllib.parse import urlparse


SOURCE_NAMES = (
    "libevhtp",
    "libsearpc",
    "seafile-server",
    "seafobj",
    "seafdav",
    "seafevents",
    "seahub",
)
REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")


def load_manifest(path):
    with Path(path).open(encoding="utf-8") as manifest_file:
        manifest = json.load(manifest_file)

    if manifest.get("schema") != 1:
        raise ValueError("release manifest schema must be 1")
    if manifest.get("product_version") != "v0.2":
        raise ValueError("release manifest product_version must be v0.2")
    version = manifest.get("seafile_version")
    if not isinstance(version, str) or not re.fullmatch(r"14\.0\.\d+", version):
        raise ValueError("release manifest must select a Seafile 14.0 patch version")

    sources = manifest.get("sources")
    if not isinstance(sources, dict) or set(sources) != set(SOURCE_NAMES):
        raise ValueError("release manifest sources do not match the required source set")
    for name, source in sources.items():
        if not isinstance(source, dict) or set(source) != {"url", "ref"}:
            raise ValueError(f"source {name!r} must contain only url and ref")
        parsed = urlparse(source["url"] if isinstance(source["url"], str) else "")
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError(f"source {name!r} must use an absolute HTTPS URL")
        if not isinstance(source["ref"], str) or not REF_RE.fullmatch(source["ref"]):
            raise ValueError(f"source {name!r} has an invalid ref")
    return manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest")
    parser.add_argument("key", choices=("product_version", "seafile_version", "url", "ref"))
    parser.add_argument("source", nargs="?")
    arguments = parser.parse_args()

    manifest = load_manifest(arguments.manifest)
    if arguments.key in ("product_version", "seafile_version"):
        if arguments.source:
            parser.error("source is not accepted for a release-level key")
        print(manifest[arguments.key])
        return
    if not arguments.source:
        parser.error("source is required for url and ref")
    print(manifest["sources"][arguments.source][arguments.key])


if __name__ == "__main__":
    main()
