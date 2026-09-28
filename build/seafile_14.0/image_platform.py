#!/usr/bin/env python3
"""Resolve a Linux image platform and verify native release binaries."""

import argparse
from pathlib import Path
import platform
import struct


ARCH_ALIASES = {"arm64": "arm64", "aarch64": "arm64", "amd64": "amd64", "x86_64": "amd64"}
ELF_MACHINE = {"arm64": 183, "amd64": 62}


def resolve(value):
    if value == "native":
        value = platform.machine().lower()
    if value.startswith("linux/"):
        value = value.removeprefix("linux/")
    arch = ARCH_ALIASES.get(value)
    if arch is None:
        raise ValueError("platform must be native, linux/arm64, or linux/amd64")
    return "linux/" + arch


def verify_package(package, target):
    expected = ELF_MACHINE[target.removeprefix("linux/")]
    for name in ("seafile/bin/seaf-server", "seafile/bin/fileserver"):
        with (Path(package) / name).open("rb") as source:
            header = source.read(20)
        if len(header) < 20 or header[:4] != b"\x7fELF" or header[4] != 2 or header[5] not in (1, 2):
            raise ValueError(f"invalid Linux ELF binary: {name}")
        machine = struct.unpack("<H" if header[5] == 1 else ">H", header[18:20])[0]
        if machine != expected:
            raise ValueError(f"package binary {name} does not match {target}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("resolve", "verify"))
    parser.add_argument("platform", nargs="?", default="native")
    parser.add_argument("package", nargs="?")
    args = parser.parse_args()
    try:
        target = resolve(args.platform)
        if args.command == "verify":
            if not args.package:
                parser.error("verify requires a package directory")
            verify_package(args.package, target)
        print(target)
    except (ValueError, OSError) as error:
        parser.exit(2, str(error) + "\n")


if __name__ == "__main__":
    main()
