#!/usr/bin/env python3
"""Repackage an extensions-only Hub change, retaining verified frontend/native bytes."""
import argparse
import json
from pathlib import Path
import shutil
import tempfile

from package_provenance import RECORD_NAME, _git, preserved_digest, verify_package, write_provenance
from source_manifest import load_manifest


def changed_paths(hub, old, new):
    paths = _git(hub, 'diff', '--name-only', old, new).splitlines()
    if not paths or any(not name.startswith('cloudfile_extensions/') or
                        '..' in Path(name).parts for name in paths):
        raise ValueError('backend patch requires extensions-only changes')
    return paths


def assemble(base, hub, output, manifest_path):
    base, hub, output = (Path(value).resolve() for value in (base, hub, output))
    if output.exists():
        raise ValueError('fresh output directory required')
    original = json.loads((base / RECORD_NAME).read_text())
    manifest = load_manifest(manifest_path)
    expected = json.loads(json.dumps(original['manifest']))
    expected['sources']['seahub'] = manifest['sources']['seahub']
    if expected != manifest:
        raise ValueError('non-Hub inputs changed')
    pin = manifest['sources']['seahub']['ref']
    old = original['source_commits']['seahub']
    if _git(hub, 'rev-parse', 'HEAD') != pin or _git(hub, 'status', '--porcelain'):
        raise ValueError('clean pinned Hub required')
    paths = changed_paths(hub, old, pin)
    with tempfile.TemporaryDirectory() as work:
        previous = Path(work) / 'release.json'
        previous.write_text(json.dumps(original['manifest']))
        verify_package(base, previous)
    native = preserved_digest(base)
    with tempfile.TemporaryDirectory(prefix='.backend-patch-', dir=output.parent) as work:
        package = Path(work) / 'package'
        shutil.copytree(base, package, symlinks=True)
        (package / RECORD_NAME).unlink()
        for name in paths:
            source, target = hub / name, package / 'seahub' / name
            if source.is_symlink() or target.is_symlink():
                raise ValueError('extension symlink change is unsupported')
            if source.exists():
                if not source.is_file():
                    raise ValueError('extension change must be a file')
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
            elif target.exists():
                target.unlink()
        if preserved_digest(package) != native:
            raise ValueError('native/dependency bytes changed')
        record = write_provenance(package, dict(schema=1, manifest=manifest,
            source_commits={name: item['ref'] for name, item in manifest['sources'].items()},
            assembly=dict(kind='hub-application-reassembly', base_provenance=original,
                preserved_non_hub_sha256=native,
                frontend=dict(entry='retained', compiled_source=old, assets_sha256={},
                              retained_entries_source=old),
                recipe=['verified base package', 'extensions-only tracked file delta',
                        'retain all original frontend/native artifacts and base build-info'],
                changed_paths=paths)), manifest_path)
        verify_package(package, manifest_path)
        if _git(hub, 'rev-parse', 'HEAD') != pin or _git(hub, 'status', '--porcelain'):
            raise ValueError('Hub changed during assembly')
        package.rename(output)
    return record


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ('base', 'hub', 'output', 'manifest'):
        parser.add_argument('--' + option, required=True)
    args = parser.parse_args()
    print(json.dumps(assemble(args.base, args.hub, args.output, args.manifest), indent=2))
