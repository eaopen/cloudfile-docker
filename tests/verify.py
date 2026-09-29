#!/usr/bin/env python3
"""Scoped development verification and explicit clean runtime release gate."""
import argparse
import ast
from contextlib import contextmanager
import hashlib
import fcntl
import json
from pathlib import Path
import secrets
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
HUB = WORKSPACE / 'cloudfile-hub'
DEFAULT_IMAGE = 'cloudfile/cloudfile:14.0.8-v0.2-rc-work'
OWNER = hashlib.sha256(str(WORKSPACE).encode()).hexdigest()[:16]
LABEL = 'com.cloudfile.dev-verifier'
GROUPS = {
    'identity': ('identity', 'sessions', 'directory'),
    'authorization': ('authorization', 'directory', 'acl'),
    'transfer': ('delegation', 'services', 'authorization', 'acl'),
    'migration': ('migration',),
    'audit': ('audit', 'events'),
}


def command(args, **kwargs):
    return subprocess.run(args, text=True, capture_output=True, **kwargs)


def git(repo, *args):
    result = command(['git', '-C', str(WORKSPACE / repo), *args])
    if result.returncode:
        raise RuntimeError('Git operation failed for ' + repo)
    return result.stdout.strip()


def extensions_hash():
    digest = hashlib.sha256()
    for path in sorted((HUB / 'cloudfile_extensions').rglob('*.py')):
        digest.update(str(path.relative_to(HUB)).encode() + b'\0' + path.read_bytes() + b'\0')
    return digest.hexdigest()


def baseline_checks(contract_python):
    reports = {}
    for name in ('verify_baseline.py', 'check_design_contracts.py'):
        interpreter = contract_python if name == 'check_design_contracts.py' else sys.executable
        result = command([interpreter, str(WORKSPACE / 'eap-cloudfile/tools' / name)])
        reports[name] = dict(passed=result.returncode == 0, output=result.stdout[-2000:])
    return reports


def changed_files(base=None):
    files = set()
    for repo in ('cloudfile-hub', 'cloudfile-server', 'cloudfile-docker', 'eap-cloudfile'):
        # NUL separation handles spaces; diff detects removed paths as well.
        for args in (['diff', '--name-only', '-z', 'HEAD'],
                     ['ls-files', '--others', '--exclude-standard', '-z']):
            files.update(repo + '/' + p for p in git(repo, *args).split('\0') if p)
        if base:
            files.update(repo + '/' + p for p in git(repo, 'diff', '--name-only', '-z', base + '...HEAD').split('\0') if p)
    return sorted(files)


def test_modules(group, seeds=None):
    """Reverse import closure includes downstream tests and shared test fixtures."""
    sources = {}
    for path in (HUB / 'cloudfile_extensions').rglob('*.py'):
        module = '.'.join(path.relative_to(HUB).with_suffix('').parts)
        if module.endswith('.__init__'):
            module = module.removesuffix('.__init__')
        sources[module] = path
    edges = {}
    for module, path in sources.items():
        imports = set()
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                package = module if path.name == '__init__.py' else module.rpartition('.')[0]
                parent = package.split('.')[:len(package.split('.')) - node.level + 1] if node.level else []
                prefix = '.'.join(parent + ([node.module] if node.module else []))
                imports.add(prefix)
                imports.update(prefix + '.' + alias.name for alias in node.names)
        edges[module] = imports
    affected = set(seeds) if seeds is not None else {module for module in sources if any(
        module == 'cloudfile_extensions.' + domain or module.startswith('cloudfile_extensions.' + domain + '.')
        for domain in GROUPS[group])}
    while True:
        expanded = affected | {module for module, imports in edges.items() if imports & affected}
        if expanded == affected:
            break
        affected = expanded
    return sorted(module for module in affected if module.startswith('cloudfile_extensions.tests.test_')
                  and not module.endswith('.test_download_actor'))


def plan(files):
    groups, gates, reasons, seeds = set(), set(), [], set()
    for item in files:
        repo, _, path = item.partition('/')
        if path.endswith('.md') or (repo == 'eap-cloudfile' and path.endswith('.txt')):
            if repo == 'eap-cloudfile':
                gates.add('baseline-contracts')
            continue
        if repo == 'cloudfile-hub' and path.startswith('cloudfile_extensions/tests/test_') and path.endswith('.py'):
            module = path[:-3].replace('/', '.')
            if module.endswith('test_download_actor'):
                gates.add('native-runtime')
            elif (HUB / path).exists():
                seeds.add(module)
                if module.endswith(('test_schema', 'test_common')):
                    gates.add('full-regression')
            else:
                gates.add('full-regression')
            continue
        if repo == 'cloudfile-hub' and path.startswith('cloudfile_extensions/'):
            domain = path.split('/')[1]
            if domain in ('common', 'schema', 'jobs') or path in ('cloudfile_extensions/apps.py', 'cloudfile_extensions/root_urls.py'):
                gates.add('full-regression')
            else:
                matches = {name for name, domains in GROUPS.items() if domain in domains}
                if matches:
                    groups.update(matches)
                    if path.endswith('.py'):
                        seeds.add(path[:-3].replace('/', '.').removesuffix('.__init__'))
                else:
                    gates.add('full-regression')
            if domain == 'identity':
                gates.add('identity-runtime')
                if any(name in path for name in ('manual_update', 'read_ticket', 'hosted_routes', 'configuration', '/urls.py')):
                    gates.add('web-runtime')
                if path in ('cloudfile_extensions/identity/configuration.py', 'cloudfile_extensions/identity/hosted_routes.py',
                            'cloudfile_extensions/identity/urls.py') or '/logout_' in path:
                    gates.add('identity-backchannel')
        elif repo == 'cloudfile-docker':
            groups.add('docker')
            if path == 'scripts/scripts_14.0/cloudfile-jit-worker.py':
                gates.update(('identity-provisioning', 'identity-backchannel'))
            elif path in ('scripts/scripts_14.0/cloudfile-audit-worker.py', 'tests/audit_export_runtime.py'):
                gates.add('audit-runtime')
            elif path == 'tests/delegated_transfer_runtime.py':
                gates.update(('transfer-runtime', 'web-runtime'))
            elif path == 'tests/identity_provisioning_runtime.py':
                gates.add('identity-provisioning')
            elif path == 'tests/identity_logout_runtime.py':
                gates.add('identity-logout')
            elif path in ('tests/identity_backchannel_runtime.py', 'scripts/scripts_14.0/cloudfile-logout-worker.py'):
                gates.add('identity-backchannel')
            elif path.startswith(('image/', 'build/', 'scripts/')):
                gates.add('native-runtime')
            elif path == 'tests/probe_identity_runtime.py':
                gates.update(('identity-runtime', 'audit-runtime'))
            elif path == 'tests/smoke_ce14_runtime.py':
                gates.add('native-runtime')
        elif repo == 'eap-cloudfile':
            gates.add('baseline-contracts')
        else:
            gates.update(('full-regression', 'native-build-and-runtime'))
            reasons.append('Unmapped or native change: ' + item)
    modules = set()
    if seeds:
        modules.update(test_modules('identity', seeds=seeds))
        # Dynamic imports are not an AST dependency. Unknown source edits
        # require a broad gate rather than passing an empty selection.
        if not modules:
            gates.add('full-regression')
    return dict(changed_files=files, groups=sorted(groups), modules=sorted(modules),
                required_gates=sorted(gates), reasons=reasons)


def docker(*args, input=None, timeout=180):
    result = command(['docker', *args], input=input, timeout=timeout)
    if result.returncode:
        raise RuntimeError('Docker operation failed: ' + args[0])
    return result.stdout.strip()


def owned(kind, name):
    result = command(['docker', kind, 'inspect', name])
    if result.returncode:
        # Do not interpret daemon errors as a missing resource.
        docker('info', '--format', '{{.ServerVersion}}')
        return None
    data = json.loads(result.stdout)[0]
    labels = (data.get('Config', {}) if kind == 'container' else data).get('Labels') or {}
    if labels.get(LABEL) != OWNER:
        raise RuntimeError('Refusing to use or remove unowned resource: ' + name)
    return data


def core_names(warm):
    prefix = 'cf-dev-' + OWNER if warm else 'cf-unit-' + secrets.token_hex(6)
    return prefix + '-net', prefix + '-db', prefix + '-redis'


def core_up(names):
    network, db, cache = names
    created = []
    try:
        info = owned('network', network)
        if info is None:
            docker('network', 'create', '--internal', '--label', LABEL + '=' + OWNER, network)
            created.append(('network', network))
        elif not info.get('Internal'):
            raise RuntimeError('Development network must be internal')
        for name, alias, image, mount, env in (
                (db, 'test-db', 'mysql:8', '/var/lib/mysql:rw,size=1g', ['-e', 'MYSQL_ALLOW_EMPTY_PASSWORD=yes']),
                (cache, 'test-redis', 'redis:7-alpine', '/data:rw,size=64m', [])):
            info = owned('container', name)
            if info is None:
                try:
                    docker('run', '-d', '--name', name, '--network', network, '--network-alias', alias,
                           '--label', LABEL + '=' + OWNER, '--tmpfs', mount, *env, image)
                except Exception:
                    if owned('container', name) is not None:
                        docker('rm', '-f', name)
                    raise
                created.append(('container', name))
            elif (not info['State']['Running'] or info['HostConfig'].get('PortBindings')
                  or set(info['NetworkSettings']['Networks']) != {network}
                  or info['Image'] != json.loads(docker('image', 'inspect', image))[0]['Id']):
                raise RuntimeError('Warm services changed or stopped; explicitly run warm down/up')
        return created
    except Exception:
        for kind, name in reversed(created):
            docker('rm' if kind == 'container' else 'network', *(['-f', name] if kind == 'container' else ['rm', name]))
        raise


def core_down(names):
    for kind, name in [('container', names[2]), ('container', names[1]), ('network', names[0])]:
        if owned(kind, name) is not None:
            docker('rm', '-f', name) if kind == 'container' else docker('network', 'rm', name)


@contextmanager
def core(warm):
    names = core_names(warm)
    created = core_up(names)
    try:
        yield names[0], warm and not created
    finally:
        if not warm:
            core_down(names)


def run_components(modules, image, warm):
    started = time.monotonic()
    metadata = json.loads(docker('image', 'inspect', image))[0]
    image_id = metadata['Id']
    if (git('cloudfile-server', 'status', '--porcelain') or
            (metadata['Config'].get('Labels') or {}).get('com.cloudfile.source.seafile-server') != git('cloudfile-server', 'rev-parse', 'HEAD')):
        raise RuntimeError('Native source changed; rebuild matching native artifact before component integration')
    version = (metadata['Config'].get('Labels') or {}).get('com.cloudfile.seafile.version', '')
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise RuntimeError('Component image must have a CE version label')
    with core(warm) as (network, reused):
        runner = 'cf-unit-run-' + secrets.token_hex(6)
        args = ['run', '--rm', '-i', '--name', runner, '--label', LABEL + '=' + OWNER,
                '--network', network, '--entrypoint', 'python3',
                '-v', str(HUB) + ':/workspace/cloudfile-hub:ro',
                '-v', str(WORKSPACE / 'eap-cloudfile/contracts') + ':/workspace/eap-cloudfile/contracts:ro',
                '-v', str(ROOT / 'tests/run_component_tests.py') + ':/tmp/run_component_tests.py:ro',
                '-w', '/workspace/cloudfile-hub']
        # latest is created by the real CE entrypoint; this lightweight runner
        # intentionally starts neither initialization nor Seahub/native services.
        installed = command(['docker', 'run', '--rm', '--entrypoint', 'sh', image_id,
            '-c', 'printf "%s\\n" /opt/seafile/seafile-server-*'])
        packages = installed.stdout.strip().splitlines()
        if (installed.returncode or len(packages) != 1 or
                not re.fullmatch(r'/opt/seafile/seafile-server-' + re.escape(version) + r'(?:-[a-zA-Z0-9.-]+)?', packages[0])):
            raise RuntimeError('Component image has no unique CE package directory')
        package = packages[0]
        for key, value in dict(PYTHONDONTWRITEBYTECODE='1',
            PYTHONPATH=':'.join(['/workspace/cloudfile-hub', package + '/seahub/thirdpart',
                               package + '/seafile/lib/python3/site-packages', package + '/pro/python']),
            SEAHUB_DIR='/workspace/cloudfile-hub', SEAFES_DIR=package + '/pro/python',
            CF_TEST_DB_HOST='test-db', CF_TEST_DB_PORT='3306', CF_TEST_REDIS_HOST='test-redis',
            CF_TEST_REDIS_PORT='6379', CF_TEST_ACL_LIBRARY=package + '/seafile/lib/libcloudfile_acl.so.1').items():
            args += ['-e', key + '=' + value]
        try:
            result = command(['docker', *args, image_id, '/tmp/run_component_tests.py'],
                             input=json.dumps(modules), timeout=600)
        finally:
            if owned('container', runner) is not None:
                docker('rm', '-f', runner)
        try:
            report = json.loads(result.stdout)
        except ValueError:
            raise RuntimeError('Component runner failed before safe report; exit=' + str(result.returncode)) from None
        report.update(image_id=image_id, mode='development-source-overlay', warm_reused=reused,
                      total_seconds=round(time.monotonic() - started, 3))
        report['passed'] = result.returncode == 0
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('scope', choices=['changed', *GROUPS, 'docker', 'full', 'runtime', 'identity-runtime', 'identity-provisioning', 'identity-logout', 'identity-backchannel', 'transfer-runtime', 'web-runtime', 'audit-runtime', 'warm'])
    parser.add_argument('--base', help='Explicit common Git ref for committed diff in all four repositories')
    parser.add_argument('--changed-file', action='append', help='Repository/path; replaces Git change discovery')
    parser.add_argument('--plan', action='store_true', help='Show selection without running services/tests')
    parser.add_argument('--warm', action='store_true', help='Keep/reuse owned isolated MySQL/Redis for component tests')
    parser.add_argument('--warm-action', choices=['up', 'status', 'down'], default='status')
    parser.add_argument('--image', default=DEFAULT_IMAGE)
    parser.add_argument('--contract-python', default=sys.executable,
                        help='Python with eap-cloudfile/tools/design-requirements.txt installed; used only for contract gate')
    parser.add_argument('--annotations-probe', action='store_true', help='Runtime only: targeted native annotations source overlay')
    parser.add_argument('--annotations-http-probe', action='store_true', help='Identity-runtime only: targeted authenticated annotations source overlay')
    args = parser.parse_args()
    if args.annotations_http_probe and args.scope != 'identity-runtime':
        parser.error('--annotations-http-probe requires identity-runtime')
    if args.annotations_probe and args.scope != 'runtime':
        parser.error('--annotations-probe requires runtime scope')
    if args.scope == 'warm':
        names = core_names(True)
        if args.warm_action == 'up':
            core_up(names)
        elif args.warm_action == 'down':
            core_down(names)
        print(json.dumps(dict(action=args.warm_action, resources={name: owned(kind, name) is not None
            for kind, name in [('network', names[0]), ('container', names[1]), ('container', names[2])]})))
        return
    selection = plan(args.changed_file if args.changed_file is not None else changed_files(args.base)) if args.scope == 'changed' else dict(
        groups=[args.scope], modules=test_modules(args.scope) if args.scope in GROUPS else [], required_gates=[])
    if args.plan:
        print(json.dumps(selection, indent=2))
        return
    if args.scope in ('full', 'runtime', 'identity-runtime', 'identity-provisioning', 'identity-logout', 'identity-backchannel', 'transfer-runtime', 'web-runtime', 'audit-runtime'):
        # Full gate tests the packaged artifact, never the development overlay.
        if args.scope == 'full':
            if not all(item['passed'] for item in baseline_checks(args.contract_python).values()):
                raise RuntimeError('Locked source baseline failed; full gate refused')
            labels = json.loads(docker('image', 'inspect', args.image))[0]['Config']['Labels']
            for repo, label in [('cloudfile-hub', 'seahub'), ('cloudfile-server', 'seafile-server')]:
                if git(repo, 'status', '--porcelain') or labels.get('com.cloudfile.source.' + label) != git(repo, 'rev-parse', 'HEAD'):
                    raise RuntimeError('Full gate requires clean source matching packaged image: ' + repo)
        from smoke_ce14_runtime import run
        report = run(args.image, annotations_runtime=args.annotations_probe, extensions_regression=args.scope == 'full',
                     identity_runtime=args.scope in ('full', 'identity-runtime', 'identity-provisioning', 'identity-logout', 'identity-backchannel', 'transfer-runtime', 'web-runtime', 'audit-runtime'),
                     identity_scenario='annotations' if args.annotations_http_probe else 'provisioning' if args.scope == 'identity-provisioning' else
                         'logout' if args.scope == 'identity-logout' else
                         'backchannel' if args.scope == 'identity-backchannel' else
                         'transfer' if args.scope == 'transfer-runtime' else
                         'audit' if args.scope == 'audit-runtime' else
                         'web' if args.scope == 'web-runtime' else 'prebound')
        if args.scope == 'full':
            report['provisioning_runtime'] = run(args.image, identity_runtime=True,
                identity_scenario='provisioning')
            report['logout_runtime'] = run(args.image, identity_runtime=True,
                identity_scenario='logout')
            report['backchannel_runtime'] = run(args.image, identity_runtime=True,
                identity_scenario='backchannel')
        print(json.dumps(report, indent=2))
        return
    report = dict(selection=selection, scope='development-selected-tests', release_acceptance=False)
    passed = True
    before = extensions_hash()
    if selection['modules']:
        report['components'] = run_components(selection['modules'], args.image, args.warm)
        passed &= report['components']['passed']
    if 'docker' in selection['groups']:
        result = command(['docker', 'run', '--rm', '--entrypoint', 'python3', '-v', str(ROOT) + ':/workspace:ro',
            '-w', '/workspace', '-e', 'PYTHONDONTWRITEBYTECODE=1', args.image, '-m', 'unittest', 'discover', '-s', 'tests'], timeout=120)
        report['docker_tests'] = dict(passed=result.returncode == 0, output=result.stderr[-1500:])
        passed &= result.returncode == 0
    if 'baseline-contracts' in selection['required_gates']:
        report['baseline'] = baseline_checks(args.contract_python)
        passed &= all(item['passed'] for item in report['baseline'].values())
    report['source'] = {repo: dict(head=git(repo, 'rev-parse', 'HEAD'), dirty=bool(git(repo, 'status', '--porcelain')))
                        for repo in ('cloudfile-hub', 'cloudfile-server', 'cloudfile-docker', 'eap-cloudfile')}
    report['extensions_source_sha256'] = before
    report['source_unchanged_during_tests'] = before == extensions_hash()
    passed &= report['source_unchanged_during_tests']
    report['result'] = 'passed-selected-tests' if passed else 'failed'
    print(json.dumps(report, indent=2))
    # Required integration gates remain visible and do not turn into a false green.
    outstanding = set(selection['required_gates']) - {'baseline-contracts'}
    raise SystemExit(1 if not passed else 2 if outstanding else 0)


if __name__ == '__main__':
    # SQL schemas are random but several Redis fixtures flush the fixture DB.
    # Serialize all warm operations; never collide with another verifier run.
    with open('/tmp/cf-dev-' + OWNER + '.lock', 'a') as lock:
        if '--warm' in sys.argv or 'warm' in sys.argv[1:2]:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise SystemExit('Warm verification is already running for this workspace')
        main()
