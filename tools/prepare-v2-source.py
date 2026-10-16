#!/usr/bin/env python3
"""Assemble fixed native CE trees plus reviewed files, never the fork HEAD tree."""
import argparse
import ast
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile


FORBIDDEN_IMPORTS = ('cloudfile_extensions', 'cloudfile_ext.apps', 'cloudfile_ext.registry',
                     'cloudfile_ext.sso', 'cloudfile_ext.acl')


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args])


def check_overlay(path):
    if path.suffix != '.py':
        return
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        modules = []
        if isinstance(node, ast.Import):
            modules = [item.name for item in node.names]
        elif isinstance(node, ast.ImportFrom):
            package = next(parent for parent in path.parents if parent.name == 'v2')
            if node.level and node.level > len(path.relative_to(package).parts):
                raise ValueError('overlay import escapes V2 package')
            modules = [node.module or '']
        for module in modules:
            if module.startswith('cloudfile_ext') and not (module == 'cloudfile_ext.v2' or module.startswith('cloudfile_ext.v2.')):
                raise ValueError('legacy CloudFile dependency: ' + module)
            if any(module == prefix or module.startswith(prefix + '.') for prefix in FORBIDDEN_IMPORTS):
                raise ValueError('legacy CloudFile dependency: ' + module)


def extract(repo, ref, destination, paths=()):
    raw = git(repo, 'archive', '--format=tar', ref, *(['--', *paths] if paths else []))
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        archive.extractall(destination, filter='data')


def assemble(workspace, output, source_set, refs):
    if output.exists():
        raise ValueError('destination already exists')
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.cf-v2-source-', dir=output.parent))
    receipt = {'ce_version': source_set['ce_version'], 'components': {}}
    try:
        for component, config in source_set['components'].items():
            repo = workspace / component
            base = config['native_commit']
            if not re.fullmatch('[0-9a-f]{40}', base):
                raise ValueError('native source must be immutable')
            overlay_ref = git(repo, 'rev-parse', refs[component] + '^{commit}').decode().strip()
            target = stage / config['directory']
            target.mkdir()
            extract(repo, base, target)
            native_files = {p.relative_to(target).as_posix() for p in target.rglob('*') if p.is_file()}
            overlay_files = []
            for prefix in config['overlay']:
                files = git(repo, 'ls-tree', '-r', '--name-only', overlay_ref, '--', prefix).decode().splitlines()
                if not files:
                    raise ValueError('reviewed overlay absent: ' + prefix)
                for file in files:
                    if file in native_files or file.startswith('/') or '..' in Path(file).parts:
                        raise ValueError('overlay must not replace native source: ' + file)
                    overlay_files.append(file)
                extract(repo, overlay_ref, target, [prefix])
            digests = {}
            for file in overlay_files:
                path = target / file
                if path.is_symlink():
                    raise ValueError('overlay symlinks are not supported')
                check_overlay(path)
                digests[file] = hashlib.sha256(path.read_bytes()).hexdigest()
            if (target / 'cloudfile_extensions').exists() or (target / 'cloudfile_ext/apps.py').exists():
                raise ValueError('legacy runtime leaked into native source')
            receipt['components'][component] = {'native_commit': base, 'overlay_commit': overlay_ref,
                                                'overlay_sha256': digests}
        (stage / 'v2-source-receipt.json').write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
        stage.rename(output)
    except BaseException:
        shutil.rmtree(stage)
        raise
    return receipt


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--hub-ref', default='HEAD')
    parser.add_argument('--server-ref', default='HEAD')
    args = parser.parse_args()
    config = Path(__file__).resolve().parents[1] / 'build/v2/source-set.json'
    receipt = assemble(args.workspace.resolve(), args.output.resolve(), json.loads(config.read_text()),
                       {'cloudfile-hub': args.hub_ref, 'cloudfile-server': args.server_ref})
    print(json.dumps(receipt, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
