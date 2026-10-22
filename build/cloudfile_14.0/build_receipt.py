#!/usr/bin/env python3
"""Resolve branch configuration once, then consume an immutable source lock."""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("release_yaml", ROOT / "build/cloudfile_14.0/read-manifest.py")
READER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(READER)
SHA = re.compile(r"[0-9a-f]{40}\Z")
FORKS = {"seafile-server": "cloudfile_server", "seahub": "cloudfile_hub",
         "cloudfile-docker": "cloudfile_docker"}
DEPENDENCIES = ("libevhtp", "libsearpc", "seafobj", "seafdav", "seafevents")


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="." + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def resolve(manifest, version, overrides=None):
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)+(?:-[A-Za-z0-9.-]+)?", version):
        raise ValueError("invalid build version")
    config = READER.load(manifest)
    overrides = overrides or {}
    branches, commits, urls = {}, {}, {}
    # Each branch is resolved exactly once. A remote error is fatal even if
    # a previous build or a local object database contains a usable commit.
    for name, key in FORKS.items():
        ref = overrides.get(name) or config["forks." + key + ".ref"]
        if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9/_.-]*", ref)
                or ".." in ref or ref.endswith("/") or SHA.fullmatch(ref)):
            raise ValueError("select a branch name, not a cached commit: " + name)
        url = config["forks." + key + ".url"]
        result = subprocess.check_output(
            ["git", "ls-remote", "--exit-code", url, "refs/heads/" + ref], text=True)
        lines = result.strip().splitlines()
        if len(lines) != 1:
            raise ValueError("remote branch is absent or ambiguous: " + name)
        commit, remote_ref = lines[0].split()
        if not SHA.fullmatch(commit) or remote_ref != "refs/heads/" + ref:
            raise ValueError("invalid remote branch result: " + name)
        branches[name], commits[name], urls[name] = ref, commit, url
    sources = {name: {"url": urls[name], "ref": commits[name]}
               for name in ("seafile-server", "seahub")}
    for name in DEPENDENCIES:
        pin = config["upstream." + name]
        if not SHA.fullmatch(pin):
            raise ValueError("CE dependencies require immutable source commits: " + name)
        sources[name] = {"url": "https://github.com/haiwen/" + name + ".git", "ref": pin}
    lock = {"schema": 1, "product_version": "v2", "seafile_version":
            config["ce_anchor.version"].removeprefix("v").removesuffix("-server"),
            "sources": sources, "docker_commit": commits["cloudfile-docker"]}
    return {"schema": 2, "created_at": datetime.now(timezone.utc).isoformat(),
            "version": version, "requested_branches": branches, "lock": lock,
            "tests": {}, "image": None}


def load_receipt(path):
    receipt = json.loads(Path(path).read_text())
    if receipt.get("schema") != 2 or not isinstance(receipt.get("lock"), dict):
        raise ValueError("a generated build receipt is required")
    from source_manifest import validate_manifest
    validate_manifest(receipt["lock"])
    if not SHA.fullmatch(receipt["lock"].get("docker_commit", "")):
        raise ValueError("receipt is missing the Docker source commit")
    if not isinstance(receipt.get("tests"), dict):
        raise ValueError("receipt has no test results")
    return receipt


def verify_recipe(receipt, repo):
    actual = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    if actual != receipt["lock"]["docker_commit"]:
        raise ValueError("Docker checkout differs from the resolved build receipt")
    dirty = subprocess.check_output(
        ["git", "-C", str(repo), "status", "--porcelain", "--untracked-files=normal"], text=True)
    if dirty:
        raise ValueError("Docker build recipe must have a clean worktree")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("resolve")
    create.add_argument("--manifest", type=Path, required=True)
    create.add_argument("--version", required=True)
    create.add_argument("--output", type=Path, required=True)
    for key in ("server", "hub", "docker"):
        create.add_argument("--" + key + "-ref")
    verify = sub.add_parser("verify")
    verify.add_argument("receipt", type=Path)
    verify.add_argument("--recipe", type=Path)
    verify.add_argument("--version")
    lock = sub.add_parser("lock")
    lock.add_argument("receipt", type=Path)
    lock.add_argument("output", type=Path)
    result = sub.add_parser("test")
    result.add_argument("receipt", type=Path)
    result.add_argument("name")
    result.add_argument("status", choices=("passed", "failed", "not-run"))
    result.add_argument("--command", dest="test_command", default="")
    result.add_argument("--log-sha256", default="")
    image = sub.add_parser("image")
    image.add_argument("receipt", type=Path)
    image.add_argument("tag")
    args = parser.parse_args()
    if args.command == "resolve":
        overrides = {"seafile-server": args.server_ref, "seahub": args.hub_ref,
                     "cloudfile-docker": args.docker_ref}
        receipt = resolve(args.manifest, args.version, overrides)
        verify_recipe(receipt, ROOT)
        atomic_json(args.output, receipt)
        return
    receipt = load_receipt(args.receipt)
    if args.command == "verify":
        if args.version and args.version != receipt.get("version"):
            raise ValueError("build version differs from the resolved receipt")
        if args.recipe:
            verify_recipe(receipt, args.recipe)
    elif args.command == "lock":
        atomic_json(args.output, receipt["lock"])
    elif args.command == "test":
        receipt["tests"][args.name] = {"status": args.status, "command": args.test_command,
            "log_sha256": args.log_sha256}
        atomic_json(args.receipt, receipt)
    elif args.command == "image":
        info = json.loads(subprocess.check_output(["docker", "image", "inspect", args.tag], text=True))[0]
        labels = info.get("Config", {}).get("Labels", {}) or {}
        for name, commit in (("seafile-server", receipt["lock"]["sources"]["seafile-server"]["ref"]),
                             ("seahub", receipt["lock"]["sources"]["seahub"]["ref"]),
                             ("cloudfile-docker", receipt["lock"]["docker_commit"])):
            if labels.get("com.cloudfile.source." + name) != commit:
                raise ValueError("built image differs from the source receipt: " + name)
        if labels.get("org.opencontainers.image.version") != receipt["version"]:
            raise ValueError("built image version differs from the receipt")
        digest = info["Id"]
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
            raise ValueError("invalid image content digest")
        receipt["image"] = {"tag": args.tag, "digest": digest,
            "digest_kind": "local-image-config", "repo_digests": info.get("RepoDigests", [])}
        atomic_json(args.receipt, receipt)
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
