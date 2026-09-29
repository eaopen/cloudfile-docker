"""Small offline import using the already-built v0.1 CLI and isolated CE14.

Only a new, unexposed, unmanaged library is eligible. This is an operator
workflow, not permission to sync managed libraries or an enabled migration API.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import secrets
import sys
import tempfile
import time
from urllib.parse import urlencode
from uuid import uuid4


def exercise(*, docker, app, network, prefix, containers, request, auth, repo):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'cloudfile-hub'))
    from cloudfile_extensions.migration.scanner import SourceScanner
    from cloudfile_extensions.migration.working_copy import WorkingCopyBuilder
    from cloudfile_extensions.migration.verify_copy import WorkingCopyVerifier

    spec = importlib.util.spec_from_file_location('cf_migration_prepare',
        Path(__file__).resolve().parents[1] / 'tools' / 'prepare-migration.py')
    prepare = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prepare)

    cli_image = 'cloudfile/seaf-cli-migration:9.0.21-cf2'
    cli_id = json.loads(docker('image', 'inspect', cli_image))[0]['Id']
    app_ip = json.loads(docker('inspect', app))[0]['NetworkSettings']['Networks'][network]['IPAddress']
    volume = prefix + '-migration'
    client = prefix + '-migration'
    docker('volume', 'create', volume)
    started = time.monotonic()
    try:
        with tempfile.TemporaryDirectory(prefix='cf02-import-') as temporary:
            root = Path(temporary)
            source, work = root / 'original', root / 'work'
            source.mkdir()
            work.mkdir()
            contents = {'readme.txt': b'CloudFile offline import\n',
                        'drawings/part 01.bin': secrets.token_bytes(4 * 1024 * 1024),
                        'drawings/nested/notes.txt': '小目录导入与恢复\n'.encode(),
                        'zero.dat': b''}
            for name, data in contents.items():
                path = source / 'selected' / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
                path.chmod(0o444)
            (source / 'excluded.txt').write_bytes(b'not selected')
            original = list(SourceScanner(str(source), content_hash=True).scan())
            assert not any('error' in row for row in original)
            copy = WorkingCopyBuilder(sources={'fixture': str(source)}, work_root=str(work)).build(
                'fixture', attempt_id=str(uuid4()), checkpoint=lambda counts: False)
            verified = WorkingCopyVerifier(work_root=str(work)).verify(copy, checkpoint=lambda counts: False)
            assert verified['copy_verified'] is True
            prepared_root = root / 'prepared'
            prepared = prepare.build(str(source), str(prepared_root), [(('selected',), ('History',))])
            expected_contents = {'History/' + name: data for name, data in contents.items()}
            expected = {name: hashlib.sha256(data).hexdigest() for name, data in expected_contents.items()}
            # A reused state volume survives actual container SIGTERM and start.
            # Limit upload only to make the single interruption deterministic.
            command = '''
set -e
while [ ! -s /run/secrets/cf_migration_token ]; do sleep 0.2; done
if [ ! -f /migration/state/prepared ]; then
 mkdir -p /migration/state
 seaf-cli init -c /migration/state/ccnet -d /migration/state >/dev/null
 seaf-cli start -c /migration/state/ccnet >/dev/null
 seaf-cli config -c /migration/state/ccnet -k upload_limit -v 32768
 seaf-cli stop -c /migration/state/ccnet >/dev/null
 touch /migration/state/prepared
fi
exec /usr/local/bin/cf-migration
'''
            containers.append(client)
            docker('run', '-d', '--platform', 'linux/amd64', '--name', client,
                '--network', network, '--add-host', 'cloudfile-smoke.invalid:' + app_ip,
                '--mount', 'type=volume,src=' + volume + ',dst=/migration',
                '-e', 'CF_MIGRATION_SERVER_URL=http://app', '-e', 'CF_MIGRATION_REPO_ID=' + repo,
                '-e', 'CF_MIGRATION_USER=admin@smoke.invalid',
                '-e', 'CF_MIGRATION_SOURCE_HOST=fixture-staging', '-e', 'CF_MIGRATION_STATUS_INTERVAL=1',
                '--entrypoint', '/bin/bash', cli_image, '-c', command)
            docker('exec', client, 'mkdir', '-p', '/migration/source', '/run/secrets')
            docker('cp', str(prepared_root) + '/.', client + ':/migration/source')
            # Private secret goes through stdin, never argv or printed evidence.
            docker('exec', '-i', client, 'sh', '-c', 'umask 077; cat > /run/secrets/cf_migration_token',
                   input=auth['Authorization'].removeprefix('Token '))
            conf = '/migration/state/ccnet'
            def cli(*args):
                return docker('exec', client, 'seaf-cli', *args, '-c', conf, timeout=20)
            def wait_link():
                deadline = time.monotonic() + 35
                while time.monotonic() < deadline:
                    try:
                        linked = json.loads(cli('list', '--json'))
                        if len(linked) == 1 and linked[0]['id'] == repo:
                            return linked
                    except (RuntimeError, ValueError):
                        pass
                    time.sleep(0.3)
                raise RuntimeError('migration_link_deadline')
            linked = wait_link()
            # Native listing proves the interrupted target has not completed.
            def listing(path='/'):
                response = request('/api2/repos/' + repo + '/dir/?' + urlencode({'p': path}), headers=auth)
                assert response['status'] == 200
                return json.loads(response['body'])
            before = listing()
            assert not before, 'migration_check=interrupted_target_not_empty'
            docker('stop', '--time', '10', client)
            first_exit = json.loads(docker('inspect', client))[0]['State']['ExitCode']
            assert first_exit == 143
            docker('start', client)
            resumed = wait_link()
            assert resumed == linked
            cli('config', '-k', 'upload_limit', '-v', '0')
            # The daemon reads rate limits at startup; config persistence alone
            # does not change the active worker. Keep its state and worktree.
            cli('stop')
            cli('start')
            deadline = time.monotonic() + 60
            observed = {}
            directories = []
            while time.monotonic() < deadline:
                observed, directories = {}, []
                pending = ['/']
                while pending:
                    parent = pending.pop()
                    for entry in listing(parent):
                        path = parent + entry['name']
                        if entry['type'] == 'dir':
                            directories.append(path.lstrip('/'))
                            pending.append(path + '/')
                        else:
                            observed[path.lstrip('/')] = entry['size']
                if set(observed) == set(expected):
                    break
                time.sleep(1)
            assert set(observed) == set(expected), 'migration_check=native_target_file_set'
            status = json.loads(cli('status', '--json'))
            assert not status['sync_errors'], 'migration_check=sync_errors'
            # Status is an observation; success comes only from native bytes.
            report = []
            for name in sorted(expected):
                response = request('/api2/repos/' + repo + '/file/?' + urlencode({'p': '/' + name}), headers=auth)
                assert response['status'] == 200
                from smoke_ce14_runtime import native_path
                target = request(native_path(json.loads(response['body']), 'files'))
                assert target['status'] == 200
                digest = hashlib.sha256(target['body']).hexdigest()
                assert digest == expected[name] and observed[name] == len(expected_contents[name])
                report.append(dict(path=name, bytes=len(target['body']), sha256=digest, result='verified'))
            assert set(directories) == {'History', 'History/drawings', 'History/drawings/nested'}
            assert 'excluded.txt' not in observed
            docker('stop', '--time', '10', client)
            assert list(SourceScanner(str(source), content_hash=True).scan()) == original
            return dict(result='passed', mode='offline-admin-empty-unmanaged-library-before-enrollment',
                cli_image_id=cli_id, reused_from='v0.1 a963c177e9e6e5e122c2e088620b2cc2bb63c2b1',
                checks=['source_scan', 'isolated_working_copy', 'copy_content_verify', 'selected_directory_map',
                        'native_import_interrupted_before_publish', 'SIGTERM_143',
                        'same_volume_same_repo_same_worktree_resume', 'native_download_all_sha256', 'source_unchanged'],
                files=prepared['files'], directories=prepared['directories'], bytes=prepared['bytes'],
                manifest_sha256=prepared['manifest_sha256'], report=report,
                report_sha256=hashlib.sha256(json.dumps(report, sort_keys=True).encode()).hexdigest(),
                import_verified=True, native_status_not_completion_proof=True,
                seconds=round(time.monotonic() - started, 3))
    finally:
        docker('rm', '-f', client)
        containers.remove(client)
        docker('volume', 'rm', volume)
