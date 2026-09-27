#!/usr/bin/env python3
"""Create a new app package from verified native bytes and a clean Hub commit.

Does not rebuild native, relabel a completed package, or claim that retained
non-app frontend bundles were compiled from the new Hub source.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile

from package_provenance import (RECORD_NAME, _git, package_digest, preserved_digest,
                                verify_package, write_provenance)
from source_manifest import load_manifest


def assemble(base, hub, output, manifest_path, stats_path, evidence_path):
    base, hub, output = map(Path, (base, hub, output))
    if output.exists() or output.is_symlink():
        raise ValueError('fresh output directory required')
    base_record = json.loads((base / RECORD_NAME).read_text())
    with tempfile.TemporaryDirectory() as temporary:
        old_manifest = Path(temporary) / 'release.json'
        old_manifest.write_text(json.dumps(base_record['manifest']))
        verify_package(base, old_manifest)
    manifest = load_manifest(manifest_path)
    # Only the Hub pin may change; ABI/dependency drift requires native build.
    expected = json.loads(json.dumps(base_record['manifest']))
    expected['sources']['seahub'] = manifest['sources']['seahub']
    if expected != manifest:
        raise ValueError('non-Hub release inputs changed; native reuse refused')
    pin = manifest['sources']['seahub']['ref']
    if (Path(_git(hub, 'rev-parse', '--show-toplevel')).resolve() != hub.resolve() or
            _git(hub, 'rev-parse', 'HEAD') != pin or _git(hub, 'status', '--porcelain')):
        raise ValueError('clean exact Hub checkout required')
    evidence = json.loads(Path(evidence_path).read_text())
    compiled = evidence['source_commits']['cloudfile-hub']
    if not evidence['frontend_compile']['passed'] or evidence['frontend_compile']['entry'] != 'app':
        raise ValueError('successful app compilation evidence required')
    # Reuse compilation only if production frontend inputs did not change.
    changed = _git(hub, 'diff', '--name-only', compiled, pin, '--', 'frontend').splitlines()
    if changed:
        raise ValueError('frontend changed since compiled evidence; recompile app')
    stats = json.loads(Path(stats_path).read_text())
    hashes = evidence['frontend_compile']['assets_sha256']
    if stats.get('status') != 'done' or set(stats['chunks']) != {'app'} or set(stats['assets']) != set(hashes):
        raise ValueError('exact app stats and recorded asset set required')
    for name, row in stats['assets'].items():
        if (not name.startswith('static/') or '..' in Path(name).parts or row['name'] != name or
                hashlib.sha256(Path(row['path']).read_bytes()).hexdigest() != hashes[name]):
            raise ValueError('compiled asset differs from verified evidence')
    native_digest = preserved_digest(base)
    archive = subprocess.check_output(['git', '-C', str(hub), 'archive', pin])
    old_files = _git(hub, 'ls-tree', '-r', '--name-only',
                     base_record['source_commits']['seahub']).splitlines()
    # Build privately, publish only after content/provenance checks succeed.
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='build-output.app.', dir=output.parent) as temporary:
        package = Path(temporary) / 'package'
        shutil.copytree(base, package, symlinks=True)
        (package / RECORD_NAME).unlink()
        target = package / 'seahub'
        old_stats = json.loads((target / 'frontend/webpack-stats.pro.json').read_text())
        for name in old_files:
            path = target / name
            if path.is_file() or path.is_symlink():
                path.unlink()
        # git archive contains only trusted, clean repository paths.
        with tarfile.open(fileobj=io.BytesIO(archive)) as tree:
            tree.extractall(target)
        with (target / 'seahub/settings.py').open('a') as settings:
            settings.write('\nSEAFILE_VERSION = ' + json.dumps(manifest['seafile_version']) + '\n')
        composite = old_stats
        composite['chunks']['app'] = stats['chunks']['app']
        assets_root = target / 'media/assets/frontend'
        for name, row in stats['assets'].items():
            installed = assets_root / name
            installed.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(row['path'], installed)
            composite['assets'][name] = dict(name=name, path='frontend/' + name)
        (target / 'frontend/webpack-stats.pro.json').write_text(json.dumps(composite, indent=2) + '\n')
        # Webpack's immutable filenames already carry hashes. Add explicit
        # identity mappings to Django's existing collected-static manifest.
        static_manifest = target / 'media/assets/staticfiles.json'
        collected = json.loads(static_manifest.read_text())
        for name in hashes:
            collected['paths']['frontend/' + name] = 'frontend/' + name
        collected['hash'] = hashlib.md5(json.dumps(sorted(collected['paths'].items())).encode()).hexdigest()[:12]
        static_manifest.write_text(json.dumps(collected) + '\n')
        for names in composite['chunks'].values():
            for name in names:
                if not (assets_root / name).is_file():
                    raise ValueError('frontend bundle references missing installed asset')
        if preserved_digest(package) != native_digest:
            raise ValueError('native/dependency assets changed during app assembly')
        assembly = dict(kind='hub-application-reassembly', base_provenance=base_record,
            preserved_non_hub_sha256=native_digest, hub_archive_sha256=hashlib.sha256(archive).hexdigest(),
            frontend=dict(entry='app', compiled_source=compiled, assets_sha256=hashes,
                retained_entries_source=base_record['source_commits']['seahub'],
                retained_entries=[name for name in composite['chunks'] if name != 'app']),
            recipe=['clean Hub git archive replaces old tracked files', 'version appended to settings',
                'retain base generated locale/thirdpart/static files', 'replace app stats and install recorded assets',
                'extend Django static manifest with immutable webpack filenames'])
        captured = dict(schema=1, manifest=manifest,
            source_commits={name: value['ref'] for name, value in manifest['sources'].items()}, assembly=assembly)
        record = write_provenance(package, captured, manifest_path)
        verify_package(package, manifest_path)
        if _git(hub, 'rev-parse', 'HEAD') != pin or _git(hub, 'status', '--porcelain'):
            raise ValueError('Hub source changed during assembly')
        package.rename(output)
    return record


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('base', 'hub', 'output', 'manifest', 'stats', 'evidence'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    record = assemble(args.base, args.hub, args.output, args.manifest, args.stats, args.evidence)
    print(json.dumps(record, indent=2))
