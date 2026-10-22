#!/usr/bin/env python3
"""Disposable CE14 native HTTP acceptance; no host volumes or published ports."""
import argparse
import base64
import hashlib
import json
import os
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
        identity_scenario='prebound', development_worker_overlay=False, migration_runtime=False, annotations_runtime=False,
        cf_import_runtime=False):
    if not __debug__:
        raise RuntimeError('Acceptance requires Python assertions enabled')
    if identity_runtime:
        raise RuntimeError('Retired identity-runtime fixture is not a V2 acceptance test')
    if native_regression or extensions_regression:
        raise RuntimeError(
            'Retired CloudFile extension regression cannot run on V2; '
            'use cloudfile-server/tests/test_cf_v2_acl_native.py with matched C/Go binaries and Hub source')
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
        # Freshly assembled app assets must be served by actual nginx, not just
        # present in a host build directory or mentioned in webpack stats.
        record = json.loads(docker('exec', app, 'cat',
            '/opt/seafile/seafile-server-latest/cloudfile-build.json'))
        assembly = record.get('assembly')
        if assembly and identity_scenario != 'annotations':
            stage = 'packaged_app_assets'
            for name, expected_sha in assembly['frontend']['assets_sha256'].items():
                response = request('/media/assets/frontend/' + name)
                assert response['status'] == 200
                assert hashlib.sha256(response['body']).hexdigest() == expected_sha
            checks.append(stage)
        stage = 'capabilities'
        response = request('/api/v2.1/cloudfile/capabilities/')
        assert response['status'] == 200
        caps = json.loads(response['body'])['capabilities']
        for key in ('auth.oidc', 'search.resources', 'file.lock'):
            assert not caps[key]['enabled']
        checks.append(stage)
        # The V2 schema is installed/checked by cloudfile_schema.py as five
        # tables. Do not re-run the deleted 001–042 legacy SchemaRunner.
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
        if annotations_runtime:
            raise RuntimeError("Retired annotations overlay has no V2 fixture.")
        if migration_runtime:
            stage = 'migration_runtime'
            from migration_runtime import exercise
            migration = exercise(docker=docker, app=app, network=network, prefix=prefix,
                containers=containers, request=request, auth=auth, repo=repo)
            return dict(result='passed', scope='isolated offline small-library import/resume only',
                image_id=metadata['Id'], package_sha256=digest, checks=checks + [stage], migration=migration)
        if cf_import_runtime:
            stage = 'cf_import_runtime'
            from cf_import_runtime import exercise
            imported = exercise(docker=docker, app=app, request=request, auth=auth, repo=repo)
            return dict(result='passed', scope='isolated one-way cf-import HTTP acceptance',
                image_id=metadata['Id'], package_sha256=digest, checks=checks + [stage], cf_import=imported)
        if identity_scenario != 'annotations':
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
                if response['status'] != 200:
                    raise RuntimeError(operation + '_link_status=' + str(response['status']))
                path = native_path(json.loads(response['body']), operation + '-api')
                data, content_type = multipart(fields, payload)
                response = request(path, 'POST', data, {'Content-Type': content_type})
                if response['status'] != 200:
                    raise RuntimeError(operation + '_status=' + str(response['status']))
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
            checks.append(stage)
        return {'result': 'passed', 'scope': 'CE14 local admin/native file baseline; directory ACL acceptance is separate',
                'image_id': metadata['Id'], 'package_sha256': digest,
                'source_seahub': labels.get('com.cloudfile.source.seahub'),
                'source_server': labels.get('com.cloudfile.source.seafile-server'),
                'checks': checks, 'extensions_regression': regression, 'identity_runtime': identity}
    except Exception as error:
        detail = str(error) if str(error).startswith(('anonymous_file_status=', 'secure_read_status=', 'upload_status=', 'update_status=', 'upload_link_status=', 'update_link_status=', 'regression_tests=', 'native_import=', 'identity_stage=', 'migration_check=', 'cf_import_probe=')) else type(error).__name__
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
                        help='Retired option; use current Server V2 native ACL acceptance')
    parser.add_argument('--extensions-regression', action='store_true',
                        help='Retired option; use current Server V2 native ACL acceptance')
    parser.add_argument('--identity-runtime', action='store_true',
                        help='Retired option; unavailable on V2')
    parser.add_argument('--identity-scenario', choices=['prebound', 'provisioning', 'logout', 'backchannel', 'transfer', 'web', 'annotations', 'audit', 'search'], default='prebound')
    parser.add_argument('--development-worker-overlay', action='store_true',
                        help='JIT development only: use host worker script; not packaged release evidence')
    parser.add_argument('--migration-runtime', action='store_true', help='Reuse v0.1 CLI for offline small-directory import and resume only')
    parser.add_argument('--cf-import-runtime', action='store_true', help='Exercise standalone cf-import against a disposable CE14 repository')
    args = parser.parse_args()
    print(json.dumps(run(args.image, args.native_regression, args.extensions_regression,
                         args.identity_runtime, args.identity_scenario, args.development_worker_overlay,
                         args.migration_runtime, cf_import_runtime=args.cf_import_runtime), indent=2))
