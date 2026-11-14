"""Real protocol, Branch-race and bounded performance acceptance for a disposable package."""
import hashlib
import io
import json
import os
import statistics
import struct
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

import pymysql
import requests

OWNER = 'owner@protection.test'
HTTP = 'http://127.0.0.1:8082'
PASSWORD = 'isolated-protection-test'


def prepare(api, state, root):
    plain = api.create_repo('protection control', '', OWNER)
    target = api.create_repo('protection destination', '', OWNER)
    state.update(plain=plain, target=target)
    for repo in (state['repo'], plain, target):
        assert api.post_dir(repo, '/', 'acceptance', OWNER) == 0
        local = root / 'matrix-input'
        local.write_bytes(b'original protocol fixture')
        assert api.post_file(repo, str(local), '/acceptance', 'original', OWNER) == 0
    state['virtual'] = api.create_virtual_repo(state['repo'], '/acceptance', 'protection virtual', '', OWNER)
    state['virtual_initial_head'] = api.get_repo(state['virtual']).head_cmmt_id


def connection(autocommit=True):
    return pymysql.connect(host='db', user='root', password=PASSWORD,
        database=os.environ['SEAFILE_MYSQL_DB_SEAFILE_DB_NAME'],
        autocommit=autocommit, charset='utf8mb4', read_timeout=30)


class Matrix:
    def __init__(self, api, state, root, protection, admin):
        self.api, self.state, self.root = api, state, root
        self.p, self.admin = protection, admin
        self.passed, self.metrics = [], {}
        self.repo = state['repo']
        self.path = '/acceptance/original'

    def mark(self, name):
        self.passed.append(name)
        print('PASS ' + name, flush=True)

    def head(self, repo=None):
        return self.api.get_repo(repo or self.repo).head_cmmt_id

    def file(self, path=None, repo=None):
        return self.api.get_file_id_by_path(repo or self.repo, path or self.path)

    def change(self, protect, path=None):
        path = path or self.path
        deadline = time.monotonic() + 10
        while True:
            result = self.p._state_change(self.admin, {'repo_id': self.repo, 'path': path,
                'expected_file_id': self.file(path)}, protect)
            if result.data.get('code') != 'VIRTUAL_REPO_SYNC_PENDING' or time.monotonic() >= deadline:
                return result
            time.sleep(.05)

    def upload(self, repo, path, content, update=False):
        parent, name = path.rsplit('/', 1)
        parent = parent or '/'
        if update:
            token = self.api.get_fileserver_access_token(repo, '0' * 40, 'update', OWNER, False)
            route, data = 'update-api', {'target_file': path}
        else:
            token = self.api.get_scoped_upload_token(repo, parent, OWNER, False)
            route, data = 'upload-api', {'parent_dir': parent, 'replace': '1'}
        return requests.post(HTTP + '/' + route + '/' + token, data=data,
            files={'file': (name, content)}, timeout=30)

    def assert_unchanged(self, before):
        assert (self.head(), self.file()) == before, 'protected native head/file changed'

    def protocols(self):
        assert self.change(True).status_code == 200
        before = self.head(), self.file()
        for update in (False, True):
            denied = self.upload(self.repo, self.path, b'blocked protocol write', update)
            assert denied.status_code == 423 and denied.json()["error"] == "FILE_PROTECTED", (update, denied.status_code, denied.text)
            self.assert_unchanged(before)
            control = self.upload(self.state['plain'], self.path, uuid4().bytes, update)
            assert control.status_code == 200, (control.status_code, control.text)
            self.mark(('update-api' if update else 'upload-api replace') + ': protected denied, ordinary control succeeds')
        token = self.api.get_scoped_upload_token(self.repo, '/acceptance', OWNER, False)
        reply = requests.post(HTTP + '/upload-api/' + token, data={'parent_dir': '/acceptance', 'replace': '1'},
            files=[('file', ('original', b'mixed overwrite')), ('file', ('must-not-exist', b'new'))], timeout=30)
        assert reply.status_code == 423 and reply.json()["error"] == "FILE_PROTECTED"
        self.assert_unchanged(before)
        assert not self.file('/acceptance/must-not-exist')
        self.mark('mixed multipart batch containing protected original is atomic')
        self.sync()
        self.cross_repo()
        self.webdav()
        assert self.change(False).status_code == 200

    def sync_attempt(self, repo, target_root):
        token = self.api.generate_repo_token(repo, OWNER)
        headers = {'Seafile-Repo-Token': token}
        old = self.head(repo)
        response = requests.get(f'{HTTP}/repo/{repo}/commit/{old}', headers=headers, timeout=15)
        assert response.status_code == 200, response.text
        commit = response.json()
        commit.update(root_id=target_root, parent_id=old, second_parent_id=None,
                      description='isolated sync protection ' + uuid4().hex, ctime=int(time.time()))
        raw = (commit['root_id'] + commit['creator'] + commit.get('creator_name', '') + commit['description']).encode()
        commit['commit_id'] = hashlib.sha1(raw + struct.pack('>Q', commit['ctime'])).hexdigest()
        response = requests.put(f"{HTTP}/repo/{repo}/commit/{commit['commit_id']}", headers=headers, json=commit, timeout=15)
        assert response.status_code == 200, response.text
        return requests.put(f'{HTTP}/repo/{repo}/commit/HEAD', params={'head': commit['commit_id']}, headers=headers, timeout=30)

    def sync(self):
        before = self.head(), self.file()
        # A previously valid tree with no protected path exists in this repo's history.
        old = self.api.get_commit(self.repo, 1, self.state['old_head'])
        response = self.sync_attempt(self.repo, old.root_id)
        assert response.status_code == 423 and response.json()["error"] == "FILE_PROTECTED", response.text
        self.assert_unchanged(before)
        plain = self.state['plain']
        oldhead = self.head(plain)
        oldroot = self.api.get_commit(plain, 1, oldhead).root_id
        assert self.upload(plain, '/acceptance/sync-control', b'new').status_code == 200
        response = self.sync_attempt(plain, oldroot)
        assert response.status_code == 200, (response.status_code, response.text)
        assert not self.file('/acceptance/sync-control', plain)
        self.mark('real sync object PUT + HEAD publication: protected denied, ordinary succeeds')

    def cross_repo(self):
        api, target = self.api, self.state['target']
        before = self.head(), self.file()
        api.copy_file(self.repo, '/acceptance', json.dumps(['original']), target, '/acceptance', json.dumps(['copied']), OWNER, 0, synchronous=1)
        assert self.file('/acceptance/copied', target) == before[1]
        assert self.upload(target, '/acceptance/copied', b'editable copy', True).status_code == 200
        self.assert_unchanged(before)
        target_head = self.head(target)
        for synchronous in (0, 1):
            try:
                api.move_file(self.repo, '/acceptance', json.dumps(['original']), target, '/acceptance',
                              json.dumps(['moved']), 0, OWNER, 1, synchronous=synchronous)
            except Exception as exc:
                assert 'CROSS_REPO_MOVE_DISABLED' in str(exc), str(exc)
            else:
                raise AssertionError('cross-repo move was accepted')
            self.assert_unchanged(before)
            assert self.head(target) == target_head and not self.file('/acceptance/moved', target)
        self.mark('cross-repository copy editable; sync and queued moves rejected before destination write')

    def wait_virtual(self):
        virtual = self.state['virtual']
        deadline = time.monotonic() + 10
        db = connection()
        try:
            while time.monotonic() < deadline:
                with db.cursor() as c:
                    c.execute('SELECT base_commit FROM VirtualRepo WHERE repo_id=%s', [virtual])
                    base = c.fetchone()[0]
                origin_root = self.api.get_dir_id_by_path(self.repo, '/acceptance')
                if (self.api.get_dir_id_by_path(virtual, '/') == origin_root and
                    self.api.get_dir_id_by_commit_and_path(self.repo, base, '/acceptance') == origin_root):
                    return
                time.sleep(.05)
        finally:
            db.close()
        raise AssertionError('virtual view and merge base did not converge')

    def virtual(self):
        virtual = self.state['virtual']
        local = self.root / 'virtual-input'
        local.write_bytes(b'virtual C overwrite')
        assert self.api.post_dir(self.repo, '/acceptance', 'nested', OWNER) == 0
        assert self.api.post_file(self.repo, str(local), '/acceptance/nested', 'child', OWNER) == 0
        assert self.change(True, '/acceptance/nested/child').status_code == 200
        self.wait_virtual()
        before = self.head(), self.file()
        virtual_before = self.head(virtual), self.file('/original', virtual)
        response = self.upload(virtual, '/original', b'virtual bypass attempt', True)
        self.metrics['virtual_write'] = {'status': response.status_code, 'origin_before': before,
            'origin_after': (self.head(), self.file()), 'virtual_before': virtual_before,
            'virtual_after': (self.head(virtual), self.file('/original', virtual))}
        assert response.status_code >= 400, ('virtual write accepted', response.status_code, response.text)
        self.assert_unchanged(before)
        assert (self.head(virtual), self.file('/original', virtual)) == virtual_before
        local = self.root / 'virtual-input'
        local.write_bytes(b'virtual C overwrite')
        for name, action in (
            ('overwrite', lambda: self.api.put_file(virtual, str(local), '/', 'original', OWNER, None)),
            ('delete', lambda: self.api.del_file(virtual, '/', json.dumps(['original']), OWNER)),
            ('rename', lambda: self.api.rename_file(virtual, '/', 'original', 'renamed', OWNER)),
            ('move', lambda: self.api.move_file(virtual, '/', json.dumps(['original']), virtual, '/', json.dumps(['moved']), 0, OWNER, 0, synchronous=1)),
            ('history restore', lambda: self.api.revert_repo(virtual, self.state['virtual_initial_head'], OWNER)),
            ('parent delete', lambda: self.api.del_file(virtual, '/', json.dumps(['nested']), OWNER)),
            ('parent rename', lambda: self.api.rename_file(virtual, '/', 'nested', 'renamed-dir', OWNER)),
        ):
            failed = False
            try:
                result = action()
                failed = result == -1
            except Exception:
                failed = True
            assert failed, name + ' returned success'
            self.assert_unchanged(before)
            assert (self.head(virtual), self.file('/original', virtual)) == virtual_before
        old_root = self.api.get_commit(virtual, 1, self.state['virtual_initial_head']).root_id
        response = self.sync_attempt(virtual, old_root)
        assert response.status_code >= 400, response.text
        self.assert_unchanged(before)
        assert (self.head(virtual), self.file('/original', virtual)) == virtual_before
        self.api.copy_file(virtual, '/', json.dumps(['original']), virtual, '/', json.dumps(['virtual-copy']), OWNER, 0, synchronous=1)
        assert self.api.put_file(virtual, str(local), '/', 'virtual-copy', OWNER, None)
        assert self.upload(virtual, '/virtual-copy', b'editable virtual copy', True).status_code == 200
        self.wait_virtual()
        assert self.file('/acceptance/virtual-copy') != before[1]
        assert self.file() == before[1]
        self.mark('virtual Go/C/sync and parent mutations denied; copied file editable and merges')
        self.virtual_races()

    def virtual_races(self):
        from django.db import connections, connection as django_connection, transaction
        from types import SimpleNamespace
        virtual = self.state['virtual']
        observer = connection()
        def protect(body):
            try:
                return self.p._state_change(self.admin, body, True)
            finally:
                connections.close_all()
        try:
            for i in range(6):
                def write(repo, path, content, update=True):
                    if i < 3:
                        return self.upload(repo, path, content, update)
                    local = self.root / ('virtual-race-' + uuid4().hex)
                    local.write_bytes(content)
                    parent, name = path.rsplit('/', 1)
                    try:
                        result = self.api.put_file(repo, str(local), parent or '/', name, OWNER, None)
                        return SimpleNamespace(status_code=200 if result else 500, text=str(result))
                    except Exception as error:
                        return SimpleNamespace(status_code=403, text=str(error))
                    finally:
                        local.unlink()
                path = f'/virtual-race-{i}'
                origin_path = '/acceptance' + path
                assert self.upload(virtual, path, b'initial').status_code == 200
                self.wait_virtual()
                body = {'repo_id': self.repo, 'path': origin_path, 'expected_file_id': self.file(origin_path)}
                virtual_before = self.head(virtual), self.file(path, virtual)
                with ThreadPoolExecutor(max_workers=1) as pool:
                    with transaction.atomic():
                        with django_connection.cursor() as c:
                            c.execute("SELECT commit_id FROM Branch WHERE repo_id=%s AND name='master' FOR UPDATE", [self.repo]); c.fetchone()
                        assert self.p._state_change(self.admin, body, True).status_code == 200
                        pending = pool.submit(write, virtual, path, b'protection commits first', True)
                        self.wait_branch(observer, 1, [pending])
                    assert pending.result(timeout=30).status_code >= 400
                assert (self.head(virtual), self.file(path, virtual)) == virtual_before
                assert self.file(origin_path) == body['expected_file_id']
                assert self.change(False, origin_path).status_code == 200
                blocker = connection(False)
                try:
                    with blocker.cursor() as c:
                        c.execute("SELECT commit_id FROM Branch WHERE repo_id=%s AND name='master' FOR UPDATE", [self.repo]); c.fetchone()
                    with ThreadPoolExecutor(max_workers=2) as pool:
                        try:
                            upload = pool.submit(write, virtual, path, b'virtual upload wins', True)
                            self.wait_branch(observer, 1, [upload])
                            guarded = pool.submit(protect, body)
                            self.wait_branch(observer, 2, [upload, guarded])
                        finally:
                            blocker.commit()
                        response, decision = upload.result(timeout=30), guarded.result(timeout=30)
                    assert response.status_code == 200, response.text
                    assert decision.status_code == 409 and decision.data['code'] in ('VIRTUAL_REPO_SYNC_PENDING', 'FILE_VERSION_CHANGED'), decision.data
                    assert not self.p.read_batch(self.repo, [origin_path])
                    self.wait_virtual()
                    assert self.change(True, origin_path).status_code == 200
                    head, file_id = self.head(virtual), self.file(path, virtual)
                    response = self.upload(virtual, path, b'protection wins', True)
                    assert response.status_code >= 400
                    assert (self.head(virtual), self.file(path, virtual)) == (head, file_id)
                    assert self.change(False, origin_path).status_code == 200
                finally:
                    blocker.rollback(); blocker.close()
            self.mark('twelve virtual Go/C publish-protect races: both orders, pending origin versions refused')
        finally:
            observer.close()

    def webdav(self):
        from wsgidav.wsgidav_app import WsgiDAVApp
        from wsgidav.dc.simple_dc import SimpleDomainController
        class NativeTestLogin(SimpleDomainController):
            def basic_auth_user(self, realm, user_name, password, environ):
                allowed = super().basic_auth_user(realm, user_name, password, environ)
                if allowed:
                    environ["http_authenticator.username"] = user_name
                return allowed
        from wsgidav.seafile_dav_provider import SeafileProvider
        from wsgiref.simple_server import make_server, WSGIRequestHandler
        class Quiet(WSGIRequestHandler):
            def log_message(self, *args):
                pass
        # Only Basic login is a test adapter. The packaged DAV provider/HTTP methods are real.
        app = WsgiDAVApp({'provider_mapping': {'/': SeafileProvider(show_repo_id=False)},
            'http_authenticator': {'domain_controller': NativeTestLogin, 'accept_basic': True, 'accept_digest': False, 'default_to_digest': False},
            'simple_dc': {'user_mapping': {'*': {OWNER: {'password': PASSWORD}}}},
            'verbose': 0, 'logging': {'enable': False}})
        def bounded_input(environ, start_response):
            # wsgiref exposes the socket stream; emulate production's bounded body.
            length = int(environ.get('CONTENT_LENGTH') or 0)
            environ['wsgi.input'] = io.BytesIO(environ['wsgi.input'].read(length))
            return app(environ, start_response)
        server = make_server('127.0.0.1', 0, bounded_input, handler_class=Quiet)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = 'http://127.0.0.1:' + str(server.server_port)
        path = '/' + quote(self.api.get_repo(self.repo).name) + self.path
        control = '/' + quote(self.api.get_repo(self.state['plain']).name) + self.path
        auth = (OWNER, PASSWORD)
        try:
            read = requests.get(base + path, auth=auth, timeout=15)
            assert read.status_code == 200, read.text
            before = self.head(), self.file()
            for method in ('PUT', 'DELETE', 'MOVE'):
                kwargs = {'data': b'DAV overwrite'} if method == 'PUT' else {}
                if method == 'MOVE': kwargs['headers'] = {'Destination': base + path + '-moved'}
                response = requests.request(method, base + path, auth=auth, timeout=15, **kwargs)
                assert response.status_code >= 400, (method, response.status_code)
                self.assert_unchanged(before)
            response = requests.put(base + control, auth=auth, data=b'DAV control', timeout=15)
            assert response.status_code in (200, 201, 204), (response.status_code, response.text)
            response = requests.request('COPY', base + path, auth=auth, headers={'Destination': base + path + '-copy'}, timeout=15)
            assert response.status_code in (201, 204), (response.status_code, response.text)
            response = requests.put(base + path + '-copy', auth=auth, data=b'DAV editable copy', timeout=15)
            assert response.status_code in (200, 201, 204), (response.status_code, response.text)
            self.mark('packaged WebDAV GET/COPY allowed; original PUT/DELETE/MOVE denied; ordinary PUT works')
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=5)

    def wait_branch(self, observer, count, futures):
        schema = os.environ['SEAFILE_MYSQL_DB_SEAFILE_DB_NAME']
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            with observer.cursor() as c:
                c.execute('SHOW ENGINE INNODB STATUS')
                status = c.fetchone()[2]
            waits = [segment for segment in status.split('---TRANSACTION') if 'LOCK WAIT' in segment
                and f'of table `{schema}`.`Branch`' in segment and 'waiting' in segment]
            if len(waits) >= count:
                return len(waits)
            for future in futures:
                if future.done():
                    result = future.result()
                    raise AssertionError(('request ended before observed Branch wait', getattr(result, 'status_code', result), getattr(result, 'text', '')))
            time.sleep(.02)
        Path(os.environ['CF_PROTECTION_REPORT']).with_name('innodb-wait.txt').write_text(status)
        raise AssertionError('missing actual Branch record lock evidence')

    def races(self):
        from django.db import connection as django_connection, connections, transaction
        payload = b'race payload ' * 100000
        observer = connection()
        def protect(body):
            try:
                return self.p._state_change(self.admin, body, True)
            finally:
                connections.close_all()
        try:
            for iteration in range(3):
                path = f'/acceptance/race-{iteration}'
                assert self.upload(self.repo, path, b'initial').status_code == 200
                self.wait_virtual()
                body = {'repo_id': self.repo, 'path': path, 'expected_file_id': self.file(path)}
                before = self.head(), self.file(path)
                with ThreadPoolExecutor(max_workers=2) as pool:
                    with transaction.atomic():
                        with django_connection.cursor() as c:
                            c.execute("SELECT commit_id FROM Branch WHERE repo_id=%s AND name='master' FOR UPDATE", [self.repo])
                            c.fetchone()
                        assert self.p._state_change(self.admin, body, True).status_code == 200
                        pending = pool.submit(self.upload, self.repo, path, payload, True)
                        self.wait_branch(observer, 1, [pending])
                    response = pending.result(timeout=30)
                    assert response.status_code >= 400, response.text
                assert (self.head(), self.file(path)) == before
                assert self.change(False, path).status_code == 200
                blocker = connection(False)
                try:
                    with blocker.cursor() as c:
                        c.execute("SELECT commit_id FROM Branch WHERE repo_id=%s AND name='master' FOR UPDATE", [self.repo]); c.fetchone()
                    with ThreadPoolExecutor(max_workers=2) as pool:
                        try:
                            upload = pool.submit(self.upload, self.repo, path, payload + str(iteration).encode(), True)
                            self.wait_branch(observer, 1, [upload])
                            protect_future = pool.submit(protect, body)
                            self.wait_branch(observer, 2, [upload, protect_future])
                        finally:
                            blocker.commit()
                        response, guarded = upload.result(timeout=30), protect_future.result(timeout=30)
                    assert response.status_code == 200, response.text
                    assert guarded.status_code == 409 and guarded.data['code'] == 'FILE_VERSION_CHANGED', guarded.data
                    assert not self.p.read_batch(self.repo, [path])
                finally:
                    blocker.rollback(); blocker.close()
            self.mark('six real update-api/protect races: both orderings, observed Branch locks, no stale protection')
        finally:
            observer.close()

    def performance(self):
        self.wait_virtual()
        plain = self.state['plain']
        # Capture only a native ordinary-library write, with no Hub protection query.
        db = connection()
        try:
            with db.cursor() as c:
                c.execute("SET GLOBAL log_output='TABLE'")
                c.execute('SET GLOBAL general_log=ON')
                c.execute('SELECT NOW(6)'); since = c.fetchone()[0]
            response = self.upload(plain, '/acceptance/zero-sql', b'zero extra SQL')
            assert response.status_code == 200, response.text
            with db.cursor() as c:
                c.execute('SET GLOBAL general_log=OFF')
                c.execute("SELECT COUNT(*) FROM mysql.general_log WHERE event_time>=%s AND command_type IN ('Query','Prepare','Execute') AND argument LIKE '%%cf_file_protection%%'", [since])
                count = c.fetchone()[0]
                if count:
                    c.execute("SELECT argument FROM mysql.general_log WHERE event_time>=%s AND argument LIKE '%%cf_file_protection%%' LIMIT 20", [since])
                    self.metrics['unexpected_protection_sql'] = [row[0] for row in c.fetchall()]
                assert count == 0, 'ordinary library issued protection SQL'
            self.mark('ordinary HTTP upload issues zero Protection SQL (MariaDB general log)')
            rows = int(os.environ.get('CF_PROTECTION_PERF_ROWS', '1000'))
            assert 100 <= rows <= 10000
            for start in range(0, rows, 100):
                files = [('file', (f'protected-{i}', b'benchmark')) for i in range(start, min(start+100, rows))]
                token = self.api.get_scoped_upload_token(self.repo, '/acceptance', OWNER, False)
                response = requests.post(HTTP + '/upload-api/' + token, data={'parent_dir': '/acceptance'}, files=files, timeout=30)
                assert response.status_code == 200, response.text
                for i in range(start, min(start+100, rows)):
                    assert self.change(True, f'/acceptance/protected-{i}').status_code == 200
            timings = {}
            for name, repo in (('ordinary', plain), ('selected', self.repo)):
                path = '/acceptance/perf'
                assert self.upload(repo, path, b'warmup').status_code == 200
                samples = []
                for i in range(23):
                    begin = time.perf_counter()
                    response = self.upload(repo, path, (str(i).encode() + b'x') * 16384, True)
                    elapsed = (time.perf_counter() - begin) * 1000
                    assert response.status_code == 200, response.text
                    if i >= 3: samples.append(elapsed)
                timings[name] = {'median_ms': statistics.median(samples), 'p95_ms': sorted(samples)[18], 'max_ms': max(samples)}
            batch = 500
            token = self.api.get_scoped_upload_token(self.repo, '/acceptance', OWNER, False)
            begin = time.perf_counter()
            response = requests.post(HTTP + '/upload-api/' + token, data={'parent_dir': '/acceptance'},
                files=[('file', (f'batch-{i}', b'bulk')) for i in range(batch)], timeout=30)
            elapsed = (time.perf_counter() - begin) * 1000
            assert response.status_code == 200, response.text
            names = {entry.obj_name for entry in self.api.list_dir_by_path(self.repo, '/acceptance')}
            assert all(f'batch-{i}' in names for i in range(batch))
            budget = max(timings['ordinary']['p95_ms'] * 3, timings['ordinary']['p95_ms'] + 100)
            self.metrics['performance'] = {'protected_native_files': rows, 'update': timings,
                'batch_files': batch, 'batch_ms': elapsed, 'selected_p95_budget_ms': budget,
                'batch_budget_ms': 10000, 'scope': 'isolated engineering regression budgets, not a business SLA'}
            assert timings['selected']['p95_ms'] <= budget, self.metrics
            assert elapsed <= 10000, self.metrics
            self.mark(f'{rows} actual protected files: ordinary/selected p95 and 500-file native upload budgets')
        finally:
            with db.cursor() as c: c.execute('SET GLOBAL general_log=OFF')
            db.close()


def run(api, state, root, protection, admin):
    matrix = Matrix(api, state, root, protection, admin)
    try:
        matrix.protocols()
        matrix.races()
        matrix.performance()
        assert matrix.change(True).status_code == 200
        matrix.virtual()
        result = {'status': 'passed', 'passed': matrix.passed, 'metrics': matrix.metrics}
    except Exception as error:
        result = {'status': 'failed', 'passed': matrix.passed, 'metrics': matrix.metrics,
                  'failure': str(error), 'type': type(error).__name__}
        raise
    finally:
        output = Path(os.environ.get('CF_PROTECTION_REPORT', str(root / 'acceptance.json')))
        output.write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps(result, indent=2), flush=True)
