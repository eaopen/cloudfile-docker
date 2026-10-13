#!/usr/bin/env python3
"""Append an S3 class and write a private Compose override (JSON is YAML).

Provider identity belongs to deployment; the storage backend remains 's3'.
Existing classes and their default are preserved, never migrated or replaced.
"""
import argparse
import copy
import json
import os
from pathlib import Path


KINDS = ("commits", "fs", "blocks")


def fresh_classes():
    return [
        dict(storage_id="legacy-default", storage_name="Existing local libraries",
             is_default=True, **{k: dict(backend="fs", dir="/shared/seafile/seafile-data") for k in KINDS}),
        dict(storage_id="auto-local", storage_name="New library directories",
             is_auto=True, is_default=False,
             **{k: dict(backend="fs", dir="/shared/seafile/library-storage") for k in KINDS}),
    ]


def append_class(classes, provider, storage_id, env):
    if not isinstance(classes, list) or not classes:
        raise ValueError("base must be a non-empty storage-class array")
    ids = set()
    for item in classes:
        if not isinstance(item, dict):
            raise ValueError("each storage class must be an object")
        ident = item.get("storage_id")
        if not isinstance(ident, str) or not ident or ident in ids:
            raise ValueError("base storage IDs must be non-empty and unique")
        ids.add(ident)
        if any(not isinstance(item.get(k), dict) or item[k].get("backend") not in ("fs", "s3") for k in KINDS):
            raise ValueError("each class requires commits, fs and blocks backends")
    if sum(item.get("is_default") is True for item in classes) != 1:
        raise ValueError("base must have exactly one default class")
    if not storage_id or storage_id in ids or storage_id.startswith("auto-local"):
        raise ValueError("new storage ID must be unique and outside the auto-local namespace")
    if provider not in ("rustfs", "minio"):
        raise ValueError("provider must be rustfs or minio")
    key_id, secret = env.get("S3_KEY_ID"), env.get("S3_SECRET_KEY")
    if not key_id or not secret:
        raise ValueError("set S3_KEY_ID and S3_SECRET_KEY for the new class")
    https = env.get("S3_USE_HTTPS", "false").lower()
    if https not in ("true", "false"):
        raise ValueError("S3_USE_HTTPS must be true or false")
    spec = dict(backend="s3", host=env.get("S3_HOST") or provider + ":9000",
                key_id=key_id, key=secret, use_https=https == "true",
                use_v4_signature=True, path_style_request=True,
                aws_region=env.get("S3_AWS_REGION") or "us-east-1")
    item = dict(storage_id=storage_id, storage_name=storage_id, is_default=False)
    for kind, var in zip(KINDS, ("S3_COMMIT_BUCKET", "S3_FS_BUCKET", "S3_BLOCK_BUCKET")):
        item[kind] = dict(spec, bucket=env.get(var) or "cloudfile-" + kind)
    return copy.deepcopy(classes) + [item]


def compose_override(classes):
    # Compose interpolates '$' even inside JSON strings. Escape once at the
    # Compose boundary; the runtime JSON and credentials retain literal '$'.
    value = json.dumps(classes, separators=(",", ":")).replace("$", "$$")
    env = dict(CF_ENABLE_S3_STORAGE="true", SEAF_SERVER_STORAGE_TYPE="multiple",
               CF_STORAGE_CLASSES_JSON=value)
    return {"services": {name: {"environment": dict(env)}
                         for name in ("cloudfile", "cf-worker")}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--base", type=Path, help="existing storage-class JSON file")
    source.add_argument("--fresh", action="store_true", help="NEW installations using the auto-library overlay only")
    parser.add_argument("--provider", choices=("rustfs", "minio"), default="rustfs")
    parser.add_argument("--storage-id", help="defaults to <provider>-standard")
    parser.add_argument("--output", type=Path, required=True, help="new private Compose override; refuses overwrite")
    args = parser.parse_args()
    try:
        base = json.loads(args.base.read_text()) if args.base else fresh_classes()
        classes = append_class(base, args.provider, args.storage_id or args.provider + "-standard", os.environ)
        content = json.dumps(compose_override(classes), indent=2) + "\n"
        fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as fp:
            fp.write(content)
    except (OSError, ValueError) as exc:
        parser.exit(1, "storage-class configuration failed: %s\n" % exc)


if __name__ == "__main__":
    main()
