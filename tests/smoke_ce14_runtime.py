#!/usr/bin/env python3
"""Disposable CE14 native HTTP acceptance; no host volumes or published ports."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import secrets
import subprocess
import time
import textwrap
from urllib.parse import urlencode, urlsplit


HTTP_CLIENT = r'''
import base64, json, sys, urllib.request, urllib.error
r = json.load(sys.stdin)
request = urllib.request.Request('http://127.0.0.1' + r['path'],
    data=base64.b64decode(r['body']) if 'body' in r else None,
    headers=r.get('headers', {}), method=r.get('method', 'GET'))
try:
    response = urllib.request.urlopen(request, timeout=10)
except urllib.error.HTTPError as error:
    response = error
with response:
    print(json.dumps({'status': response.status, 'headers': dict(response.headers),
        'body': base64.b64encode(response.read()).decode()}))
'''


def docker(*args, input=None, timeout=180):
    result = subprocess.run(['docker', *args], input=input, text=True,
                            capture_output=True, timeout=timeout)
    if result.returncode:
        # Only the identity fixture's controlled stage/type labels are safe.
        for line in result.stderr.splitlines():
            if line.startswith('RuntimeError: identity_stage='):
                raise RuntimeError(line.removeprefix('RuntimeError: '))
        # Docker/HTTP diagnostics may contain ephemeral credentials or tickets.
        raise RuntimeError('Docker operation failed: ' + args[0])
    return result.stdout.strip()


def native_path(link, operation):
    parts = urlsplit(link)
    if (parts.scheme != 'http' or parts.netloc != 'cloudfile-smoke.invalid'
            or not parts.path.startswith('/seafhttp/' + operation + '/')
            or parts.fragment):
        raise RuntimeError('Unexpected native link origin or operation')
    return parts.path + ('?' + parts.query if parts.query else '')


def multipart(fields, content):
    boundary = 'cloudfile-' + secrets.token_hex(16)
    chunks = []
    for name, value in fields.items():
        chunks.append(('--' + boundary + '\r\nContent-Disposition: form-data; name="'
                       + name + '"\r\n\r\n' + value + '\r\n').encode())
    chunks.extend([('--' + boundary + '\r\nContent-Disposition: form-data; name="file"; '
                    'filename="probe.txt"\r\nContent-Type: application/octet-stream\r\n\r\n').encode(),
                   content, ('\r\n--' + boundary + '--\r\n').encode()])
    return b''.join(chunks), 'multipart/form-data; boundary=' + boundary


def run(image, native_regression=False, extensions_regression=False, identity_runtime=False,
        identity_scenario='prebound', development_worker_overlay=False):
    if not __debug__:
        raise RuntimeError('Acceptance requires Python assertions enabled')
    prefix = 'cf02-smoke-' + secrets.token_hex(6)
    network = prefix + '-net'
    containers = []
    checks = []
    regression = None
    identity = None
    stage = 'image_identity'
    metadata = json.loads(docker('image', 'inspect', image))[0]
    labels = metadata['Config'].get('Labels') or {}
    digest = labels.get('com.cloudfile.package.sha256', '')
    if len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
        raise RuntimeError('Image lacks verified package digest')
    password = secrets.token_hex(24)
    root_password = secrets.token_hex(24)
    try:
        docker('network', 'create', '--internal', network)

        def start(suffix, alias, container_image, env, mounts):
            name = prefix + '-' + suffix
            containers.append(name)
            args = ['run', '-d', '--name', name, '--network', network,
                    '--network-alias', alias]
            for value in mounts:
                args += ['--tmpfs', value]
            for key, value in env.items():
                args += ['-e', key + '=' + value]
            docker(*args, container_image)
            return name

        stage = 'startup'
        start('db', 'db', 'mariadb:10.11', {'MARIADB_ROOT_PASSWORD': root_password},
              ['/var/lib/mysql:rw,size=1g'])
        start('cache', 'memcached', 'memcached:1.6-alpine', {}, [])
        app = start('app', 'app', image, {
            'SEAFILE_MYSQL_DB_HOST': 'db', 'SEAFILE_MYSQL_DB_PORT': '3306',
            'SEAFILE_MYSQL_DB_USER': 'seafile', 'SEAFILE_MYSQL_DB_PASSWORD': password,
            'INIT_SEAFILE_MYSQL_ROOT_PASSWORD': root_password,
            'SEAFILE_MYSQL_DB_CCNET_DB_NAME': 'ccnet_db',
            'SEAFILE_MYSQL_DB_SEAFILE_DB_NAME': 'seafile_db',
            'SEAFILE_MYSQL_DB_SEAHUB_DB_NAME': 'seahub_db',
            'SEAFILE_SERVER_HOSTNAME': 'cloudfile-smoke.invalid',
            'SEAFILE_SERVER_PROTOCOL': 'http',
            'INIT_SEAFILE_ADMIN_EMAIL': 'admin@smoke.invalid',
            'INIT_SEAFILE_ADMIN_PASSWORD': password,
            'CACHE_PROVIDER': 'memcached', 'MEMCACHED_HOST': 'memcached',
            'MEMCACHED_PORT': '11211', 'JWT_PRIVATE_KEY': secrets.token_hex(32),
            'NON_ROOT': 'false', 'ENABLE_GO_FILESERVER': 'true',
        }, ['/shared:rw,size=1g'])

        def request(path, method='GET', body=None, headers=None):
            spec = {'path': path, 'method': method, 'headers': headers or {}}
            spec['headers']['Host'] = 'cloudfile-smoke.invalid'
            if body is not None:
                spec['body'] = base64.b64encode(body).decode()
            response = json.loads(docker('exec', '-i', app, 'python3', '-c', HTTP_CLIENT,
                                         input=json.dumps(spec), timeout=20))
            response['body'] = base64.b64decode(response['body'])
            return response

        deadline = time.monotonic() + 180
        while True:
            try:
                if request('/api2/ping/')['status'] == 200:
                    break
            except (RuntimeError, ValueError, subprocess.TimeoutExpired):
                pass
            if time.monotonic() >= deadline:
                raise RuntimeError('CE14 startup deadline exceeded')
            time.sleep(2)
        checks.append('startup')
        stage = 'capabilities'
        response = request('/api/v2.1/cloudfile/capabilities/')
        assert response['status'] == 200
        caps = json.loads(response['body'])['capabilities']
        for key in ('auth.oidc', 'search.resources', 'file.lock'):
            assert not caps[key]['enabled']
        checks.append(stage)
        stage = 'local_login'
        response = request('/api2/auth-token/', 'POST', urlencode({
            'username': 'admin@smoke.invalid', 'password': password}).encode(),
            {'Content-Type': 'application/x-www-form-urlencoded'})
        assert response['status'] == 200
        auth = {'Authorization': 'Token ' + json.loads(response['body'])['token']}
        checks.append(stage)
        stage = 'create_library'
        response = request('/api2/repos/', 'POST', urlencode({
            'name': 'Disposable CF02 acceptance', 'desc': 'temporary smoke fixture'}).encode(),
            {**auth, 'Content-Type': 'application/x-www-form-urlencoded'})
        assert response['status'] == 200
        repo = json.loads(response['body'])['repo_id']
        base = '/api2/repos/' + repo
        checks.append(stage)
        content = b'CloudFile CE14 native upload, download and Range acceptance.\n' * 4

        def download():
            response = request(base + '/file/?p=/probe.txt', headers=auth)
            assert response['status'] == 200
            return native_path(json.loads(response['body']), 'files')

        for operation, fields, payload in (
                ('upload', {'parent_dir': '/'}, content),
                ('update', {'target_file': '/probe.txt'}, content + b'Explicit manual update.\n')):
            stage = operation
            response = request(base + '/' + operation + '-link/?p=/', headers=auth)
            assert response['status'] == 200
            path = native_path(json.loads(response['body']), operation + '-api')
            data, content_type = multipart(fields, payload)
            response = request(path, 'POST', data, {'Content-Type': content_type})
            assert response['status'] == 200
            checks.append(stage)
            stage = operation + '_download_bytes'
            path = download()
            response = request(path)
            assert response['status'] == 200 and response['body'] == payload
            checks.append(stage)
            stage = operation + '_range'
            response = request(download(), headers={'Range': 'bytes=7-31'})
            assert response['status'] == 206 and response['body'] == payload[7:32]
            assert response['headers'].get('Content-Range') == 'bytes 7-31/' + str(len(payload))
            checks.append(stage)
        stage = 'anonymous_denied'
        status = request(base + '/file/?p=/probe.txt')['status']
        if status not in (401, 403):
            raise RuntimeError('anonymous_file_status=' + str(status))
        status = request('/seafhttp/cloudfile/read')['status']
        if status != 401:
            raise RuntimeError('secure_read_status=' + str(status))
        checks.append(stage)
        if native_regression or extensions_regression:
            stage = 'native_actor_regression'
            code = '''
import io, json, os, unittest
package = '/opt/seafile/seafile-server-latest'
os.chdir(package + '/seahub')
import sys
sys.path[:0] = [package + '/seahub', package + '/seahub/thirdpart',
               package + '/seafile/lib/python3/site-packages', package + '/pro/python']
os.environ.update(DJANGO_SETTINGS_MODULE='seahub.settings', SEAHUB_DIR=package + '/seahub',
    SEAFES_DIR=package + '/pro/python',
    SEAFILE_DATA_DIR='/shared/seafile/seafile-data',
    SEAFILE_CENTRAL_CONF_DIR='/shared/seafile/conf',
    SEAFILE_RPC_PIPE_PATH=package + '/runtime')
import django
django.setup()
suite = unittest.defaultTestLoader.loadTestsFromName(
    'cloudfile_extensions.tests.test_download_actor')
result = unittest.TextTestRunner(stream=io.StringIO()).run(suite)
if not result.wasSuccessful() or result.skipped or result.testsRun != 1:
    raise SystemExit(1)
print(json.dumps({'tests': result.testsRun, 'skipped': len(result.skipped)}))
'''
            code = ('import json, traceback\ntry:\n' + textwrap.indent(code, '    ') +
                    '\nexcept Exception as error:\n'
                    '    print(json.dumps({"error_type": type(error).__name__, '
                    '"frames": [(item.filename.rsplit("/", 2)[-2:], item.name, item.lineno) for item in traceback.extract_tb(error.__traceback__)]}))\n')
            native = json.loads(docker('exec', app, 'python3', '-c', code, timeout=60))
            if 'error_type' in native:
                raise RuntimeError('native_import=' + json.dumps(native))
            checks.append(stage)
        if extensions_regression:
            stage = 'extensions_regression'
            version = labels.get('com.cloudfile.seafile.version', '')
            if not re.fullmatch(r'\d+\.\d+\.\d+', version):
                raise RuntimeError('Invalid CE version label')
            fixture_dir = '/opt/seafile/seafile-server-' + version + '/eap-cloudfile/contracts'
            docker('exec', app, 'mkdir', '-p', fixture_dir)
            contracts = Path(__file__).resolve().parents[2] / 'eap-cloudfile/contracts'
            for name in ('acceptance-vectors.json', 'schema-examples.json'):
                docker('cp', str(contracts / name), app + ':' + fixture_dir + '/' + name)
            # The existing SQL tests create/drop random schemas as root. Give
            # them their own server, never the initialized application's DB.
            start('test-db', 'test-db', 'mysql:8', {'MYSQL_ALLOW_EMPTY_PASSWORD': 'yes'},
                  ['/var/lib/mysql:rw,size=1g'])
            start('test-redis', 'test-redis', 'redis:7-alpine', {}, ['/data:rw,size=64m'])
            code = '''
import io, json, os, sys, time, unittest
package = '/opt/seafile/seafile-server-latest'
os.chdir(package + '/seahub')
sys.path[:0] = [package + '/seahub', package + '/seahub/thirdpart',
               package + '/seafile/lib/python3/site-packages', package + '/pro/python']
os.environ.update(SEAHUB_DIR=package + '/seahub', SEAFES_DIR=package + '/pro/python',
    PYTHONPATH=':'.join(sys.path[:4]),
    SEAFILE_DATA_DIR='/shared/seafile/seafile-data',
    SEAFILE_CENTRAL_CONF_DIR='/shared/seafile/conf',
    CF_TEST_DB_HOST='test-db', CF_TEST_DB_PORT='3306',
    CF_TEST_REDIS_HOST='test-redis', CF_TEST_REDIS_PORT='6379',
    CF_TEST_ACL_LIBRARY=package + '/seafile/lib/libcloudfile_acl.so.1')
import pymysql
deadline = time.monotonic() + 120
while True:
    try:
        connection = pymysql.connect(host='test-db', user='root', password='', port=3306)
        connection.close()
        break
    except pymysql.MySQLError:
        if time.monotonic() > deadline:
            raise SystemExit(1)
        time.sleep(2)
suite = unittest.defaultTestLoader.discover('cloudfile_extensions/tests', top_level_dir='.')
# This actor needs actual native Django apps; it already ran in its own
# configured process. HTTP unit fixtures intentionally use minimal settings.
actor_id = 'cloudfile_extensions.tests.test_download_actor.DownloadActorTests.test_native_type_and_session_identity_required_before_reload'
def flatten(items):
    for item in items:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item
all_tests = list(flatten(suite))
assert sum(test.id() == actor_id for test in all_tests) == 1
suite = unittest.TestSuite(test for test in all_tests if test.id() != actor_id)
output = io.StringIO()
result = unittest.TextTestRunner(stream=output, verbosity=2).run(suite)
report = {'tests': result.testsRun, 'native_tests_separate': 1, 'skipped': len(result.skipped),
          'failures': [test.id().split(" (", 1)[0] for test, trace in result.failures],
          'errors': [test.id().split(" (", 1)[0] for test, trace in result.errors]}
print(json.dumps(report))
'''
            regression = json.loads(docker('exec', app, 'python3', '-c', code, timeout=600))
            if regression['failures'] or regression['errors'] or regression['skipped']:
                # Test IDs are safe; do not expose exception bodies or tokens.
                raise RuntimeError('regression_tests=' + json.dumps(regression))
            checks.append(stage)
        if identity_runtime:
            stage = 'identity_runtime'
            start('identity-redis', 'identity-redis', 'redis:7-alpine', {}, ['/data:rw,size=64m'])
            fixture = Path(__file__).with_name('probe_identity_runtime.py')
            docker('cp', str(fixture), app + ':/tmp/probe_identity_runtime.py')
            worker_path = '/scripts/cloudfile-jit-worker.py'
            worker_sha = None
            if identity_scenario == 'provisioning':
                fixture = Path(__file__).with_name('identity_provisioning_runtime.py')
                docker('cp', str(fixture), app + ':/tmp/identity_provisioning_runtime.py')
                worker = Path(__file__).resolve().parents[1] / 'scripts/scripts_14.0/cloudfile-jit-worker.py'
                worker_sha = hashlib.sha256(worker.read_bytes()).hexdigest()
                if development_worker_overlay:
                    worker_path = '/tmp/cloudfile-jit-worker.py'
                    docker('cp', str(worker), app + ':' + worker_path)
                actual_sha = docker('exec', app, 'python3', '-c',
                    'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())', worker_path)
                if actual_sha != worker_sha:
                    raise RuntimeError('JIT worker image is stale; rebuild the application image')
            elif identity_scenario == 'transfer':
                fixture = Path(__file__).with_name('delegated_transfer_runtime.py')
                docker('cp', str(fixture), app + ':/tmp/delegated_transfer_runtime.py')
            elif identity_scenario == 'logout':
                fixture = Path(__file__).with_name('identity_logout_runtime.py')
                docker('cp', str(fixture), app + ':/tmp/identity_logout_runtime.py')
            elif identity_scenario == 'backchannel':
                fixture = Path(__file__).with_name('identity_backchannel_runtime.py')
                docker('cp', str(fixture), app + ':/tmp/identity_backchannel_runtime.py')
                for name in ('cloudfile-logout-worker.py', 'cloudfile-jit-worker.py'):
                    source = Path(__file__).resolve().parents[1] / 'scripts/scripts_14.0' / name
                    expected = hashlib.sha256(source.read_bytes()).hexdigest()
                    actual = docker('exec', app, 'python3', '-c',
                        'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())', '/scripts/' + name)
                    if actual != expected:
                        raise RuntimeError('Logout worker image is stale; rebuild the application image')
            identity = json.loads(docker('exec', '-e', 'CF_DISPOSABLE_IDENTITY_PROBE=true',
                '-e', 'CF_IDENTITY_SCENARIO=' + identity_scenario,
                '-e', 'CF_JIT_WORKER_SCRIPT=' + worker_path,
                app, 'python3', '/tmp/probe_identity_runtime.py', timeout=90))
            if worker_sha:
                identity.update(worker_sha256=worker_sha,
                    worker_mode='development-script-overlay' if development_worker_overlay else 'packaged-image-script')
            checks.append(stage)
        return {'result': 'passed', 'scope': 'CE14 local admin/native file baseline; optional identity fixture separately scoped',
                'image_id': metadata['Id'], 'package_sha256': digest,
                'source_seahub': labels.get('com.cloudfile.source.seahub'),
                'source_server': labels.get('com.cloudfile.source.seafile-server'),
                'checks': checks, 'extensions_regression': regression, 'identity_runtime': identity}
    except Exception as error:
        detail = str(error) if str(error).startswith(('anonymous_file_status=', 'secure_read_status=', 'regression_tests=', 'native_import=', 'identity_stage=')) else type(error).__name__
        raise RuntimeError('Isolated runtime acceptance failed at stage: ' + stage + ' (' + detail + ')') from None
    finally:
        failures = []
        for name in reversed(containers):
            try:
                docker('rm', '-f', name)
            except RuntimeError:
                failures.append(name)
        try:
            docker('network', 'rm', network)
        except RuntimeError:
            failures.append(network)
        if failures:
            raise RuntimeError('Disposable runtime cleanup failed: ' + ', '.join(failures))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True)
    parser.add_argument('--native-regression', action='store_true',
                        help='Also run the native actor import regression under real Seahub configuration')
    parser.add_argument('--extensions-regression', action='store_true',
                        help='Run extensions with a separate disposable SQL/Redis fixture')
    parser.add_argument('--identity-runtime', action='store_true',
                        help='Probe real TLS fixture OIDC/directory with actual CE accounts and SQL')
    parser.add_argument('--identity-scenario', choices=['prebound', 'provisioning', 'logout', 'backchannel', 'transfer'], default='prebound')
    parser.add_argument('--development-worker-overlay', action='store_true',
                        help='JIT development only: use host worker script; not packaged release evidence')
    args = parser.parse_args()
    print(json.dumps(run(args.image, args.native_regression, args.extensions_regression,
                         args.identity_runtime, args.identity_scenario, args.development_worker_overlay), indent=2))
