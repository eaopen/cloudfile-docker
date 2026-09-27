"""Common delegated download workflow in the owned disposable CE14 fixture."""
import json
import hashlib
from uuid import uuid4
from pathlib import Path
import secrets
import ssl
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def exercise(*, db, user, manager, machine_secret, initiate, complete, require,
             certificate, tls_key, package, web=False):
    import jwt
    import requests
    from django.test import Client
    from seaserv import seafile_api

    checks = []
    browser = Client(enforce_csrf_checks=True)
    if web:
        browser.get('/accounts/login/', secure=True, HTTP_HOST='cloudfile-smoke.invalid')
    require(complete(browser, initiate(browser)).status_code == 302, 'transfer_oidc_login')
    with db.cursor() as cursor:
        cursor.execute('SELECT repo_id FROM RepoOwner WHERE owner_id=%s', (manager.username,))
        repos = cursor.fetchall()
    require(len(repos) == 1, 'single_fixture_library')
    repo = repos[0][0]
    seafile_api.share_repo(repo, manager.username, user.username, 'rw' if web else 'r')
    reference = dict(repo_id=repo, path='/probe.txt', kind='file')
    payload = (b'CloudFile CE14 native upload, download and Range acceptance.\n' * 4
               + b'Explicit manual update.\n')

    # Only this disposable container is changed. Both native components must
    # load the same current subject cache and explicitly trusted local TLS peer.
    config = Path('/shared/seafile/conf/seafile.conf')
    with config.open('a') as out:
        out.write('\n[cloudfile]\nidentity_database = seahub_db\nsubject_redis_host = identity-redis\n'
                  'subject_redis_port = 6379\nsubject_redis_prefix = cf:subjects:\n'
                  'delegation_revocation_prefix = cf:service-revocations:\n'
                  'trusted_tls_proxies = 127.0.0.1/32\n')
    for operation in ('stop', 'start'):
        subprocess.run(['bash', package + '/seafile.sh', operation], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
    deadline = time.monotonic() + 20
    while True:
        try:
            require(seafile_api.get_repo(repo) is not None, 'native_restart')
            response = requests.get('http://127.0.0.1:8082/cloudfile/read', timeout=2)
            if response.status_code == 401:
                break
        except Exception:
            pass
        require(time.monotonic() < deadline, 'native_restart_deadline')
        time.sleep(0.5)

    class ServiceClient(Client):
        def _base_environ(self, **request):
            value = super()._base_environ(**request)
            # Django Client synthesizes Cookie: "" even when the actual HTTPS
            # service sent no Cookie header. Preserve the real wire boundary.
            value.pop('HTTP_COOKIE', None)
            return value

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Never log bearer credentials.

        def do_POST(self):
            length = int(self.headers.get('Content-Length', '0'))
            if self.path not in {
                '/api/v2.1/cloudfile/extensions/authorization/v1/delegations/',
                '/api/v2.1/cloudfile/extensions/transfer/v1/delegated-read-tickets/',
            } or not 0 < length < 8192:
                self.send_error(400)
                return
            response = ServiceClient(enforce_csrf_checks=True).post(self.path,
                data=self.rfile.read(length), content_type='application/json',
                secure=True, HTTP_HOST='cloudfile-smoke.invalid',
                HTTP_AUTHORIZATION=self.headers.get('Authorization', ''))
            self.respond(response.status_code, response.content, dict(response.items()))

        def do_GET(self):
            if self.path != '/seafhttp/cloudfile/read':
                self.send_error(404)
                return
            headers = {'Authorization': self.headers.get('Authorization', ''),
                       'X-Forwarded-Proto': 'https'}
            if 'Range' in self.headers:
                headers['Range'] = self.headers['Range']
            with requests.Session() as transport:
                transport.trust_env = False
                response = transport.get('http://127.0.0.1:8082/cloudfile/read',
                                         headers=headers, timeout=10)
            self.respond(response.status_code, response.content, response.headers)

        def respond(self, status, body, headers):
            self.send_response(status)
            for key in ('Content-Type', 'Content-Range', 'X-Request-ID', 'Cache-Control'):
                if key in headers:
                    self.send_header(key, headers[key])
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(certificate, tls_key)
    server.socket = tls.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = 'https://127.0.0.1:' + str(server.server_port)
    transport = requests.Session()
    transport.trust_env = False
    try:
        issued = int(time.time())
        machine = jwt.encode(dict(iss='etech-login', aud='cloudfile-authorization',
            sub='etech-login', iat=issued, exp=issued + 120, jti=secrets.token_hex(16),
            scope='user.delegation.issue'), machine_secret, algorithm='HS256',
            headers={'kid': 'login-v1', 'typ': 'JWT'})
        response = transport.post(origin + '/api/v2.1/cloudfile/extensions/authorization/v1/delegations/',
            json={'userId': 'fixture-user-1', 'reference': reference},
            headers={'Authorization': 'Bearer ' + machine}, verify=certificate, timeout=10)
        require(response.status_code == 201, 'delegation_issue_' + str(response.status_code))
        delegation = response.json()['delegation']
        checks.append('https_machine_current_user_delegation')

        def ticket():
            response = transport.post(origin + '/api/v2.1/cloudfile/extensions/transfer/v1/delegated-read-tickets/',
                json={'reference': reference}, headers={'Authorization': 'Bearer ' + delegation},
                verify=certificate, timeout=10)
            require(response.status_code == 201, 'native_ticket_' + str(response.status_code))
            return response.json()['ticket']

        def read(value, range_value=None):
            headers = {'Authorization': 'Bearer ' + value}
            if range_value:
                headers['Range'] = range_value
            return transport.get(origin + '/seafhttp/cloudfile/read', headers=headers,
                                 verify=certificate, timeout=10)

        if web:
            from django.conf import settings
            from django.core.files.uploadedfile import SimpleUploadedFile
            prefix = '/api/v2.1/cloudfile/extensions/identity/v1/'
            csrf = browser.cookies[settings.CSRF_COOKIE_NAME].value
            def web_ticket(target=None):
                response = browser.post(prefix + 'read-tickets/', data=json.dumps({'reference': target or reference}),
                    content_type='application/json', secure=True, HTTP_HOST='cloudfile-smoke.invalid',
                    HTTP_ORIGIN='https://cloudfile-smoke.invalid', HTTP_X_CSRFTOKEN=csrf)
                require(response.status_code == 201, 'web_ticket_' + str(response.status_code))
                return response.json()['ticket']
            require(read(web_ticket()).content == payload, 'web_native_original_bytes')
            checks.append('web_oidc_native_read')
            head = seafile_api.get_repo(repo).head_cmmt_id
            updated = payload + b'Controlled OIDC explicit Web replacement.\n'
            def update(expected, csrf_header=True):
                headers = {'HTTP_HOST': 'cloudfile-smoke.invalid', 'HTTP_ORIGIN': 'https://cloudfile-smoke.invalid'}
                if csrf_header:
                    headers['HTTP_X_CSRFTOKEN'] = csrf
                return browser.post(prefix + 'manual-update/', data={'repo_id': repo, 'path': '/probe.txt',
                    'head_id': expected, 'file': SimpleUploadedFile('probe.txt', updated)}, secure=True, **headers)
            require(update(head, False).status_code == 403, 'web_update_csrf')
            require(seafile_api.get_repo(repo).head_cmmt_id == head, 'csrf_no_publication')
            response = update(head)
            require(response.status_code == 200, 'web_update_' + str(response.status_code))
            object_id = response.json()['object_id']
            require(seafile_api.get_file_id_by_path(repo, '/probe.txt') == object_id, 'web_update_current_object')
            require(read(web_ticket()).content == updated, 'web_update_native_bytes')
            current_head = seafile_api.get_repo(repo).head_cmmt_id
            require(current_head != head, 'web_update_current_head')
            require(update(head).status_code in (409, 503), 'web_stale_head_denied')
            require(seafile_api.get_repo(repo).head_cmmt_id == current_head, 'web_stale_no_publication')
            checks.append('web_csrf_explicit_update_and_stale_head')
            # Denied write must preserve both current head and file bytes.
            seafile_api.set_share_permission(repo, manager.username, user.username, 'r')
            require(update(current_head).status_code == 403, 'web_readonly_update_denied')
            require(seafile_api.get_repo(repo).head_cmmt_id == current_head, 'web_readonly_no_publication')
            checks.append('web_current_readonly_update_denied')
            seafile_api.set_share_permission(repo, manager.username, user.username, 'rw')
            new_reference = dict(reference, path='/new-upload.txt')
            new_bytes = b'CloudFile explicit new upload, without overwrite.\n'
            def upload(path, expected):
                return browser.post(prefix + 'manual-upload/', data={'repo_id': repo, 'path': path,
                    'head_id': expected, 'file': SimpleUploadedFile('ignored-client-name.txt', new_bytes)},
                    secure=True, HTTP_HOST='cloudfile-smoke.invalid',
                    HTTP_ORIGIN='https://cloudfile-smoke.invalid', HTTP_X_CSRFTOKEN=csrf)
            created = upload(new_reference['path'], current_head)
            require(created.status_code == 201, 'web_upload_' + str(created.status_code))
            require(seafile_api.get_file_id_by_path(repo, new_reference['path']) == created.json()['object_id'],
                    'web_upload_exact_target')
            require(read(web_ticket(new_reference)).content == new_bytes, 'web_upload_native_bytes')
            current_head = seafile_api.get_repo(repo).head_cmmt_id
            require(upload(new_reference['path'], current_head).status_code in (409, 503), 'web_upload_existing_denied')
            require(seafile_api.get_repo(repo).head_cmmt_id == current_head, 'web_upload_no_overwrite')
            require(read(web_ticket(new_reference)).content == new_bytes, 'web_upload_preserved_bytes')
            checks.append('web_new_file_upload_without_overwrite')
            root_rule = str(uuid4())
            subject = dict(type='user', provider='etech', namespace='user', external_id='fixture-user-1')
            subject_hash = hashlib.sha256(json.dumps(subject, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            with db.cursor() as cursor:
                cursor.execute('INSERT INTO cf_dir_acl(id,repo_id,path,path_hash,kind,subject_type,provider,'
                    'namespace,external_id,subject_hash,permission,inherit,revision) '
                    'VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                    (root_rule, repo, '/', hashlib.sha256(b'/').hexdigest(), 'dir', 'user', 'etech', 'user',
                     'fixture-user-1', subject_hash, 'r', 0, str(uuid4())))
            # Exact-root r leaves the new-file decision writable via CE, so
            # this specifically proves the additional parent requirement.
            require(upload('/parent-denied.txt', current_head).status_code == 403, 'web_upload_parent_denied')
            require(seafile_api.get_repo(repo).head_cmmt_id == current_head, 'web_upload_parent_no_publication')
            require(seafile_api.get_file_id_by_path(repo, '/parent-denied.txt') is None, 'web_upload_parent_no_file')
            with db.cursor() as cursor:
                cursor.execute('DELETE FROM cf_dir_acl WHERE id=%s', (root_rule,))
            checks.append('web_new_file_parent_write_denied')
            payload = updated

        value = ticket()
        response = read(value)
        require(response.status_code == 200 and response.content == payload,
                'native_bytes_' + str(response.status_code))
        full_request = response.headers['X-Request-ID']
        require(read(value).status_code in (401, 403, 503), 'ticket_single_use')
        checks.append('native_ticket_single_use_and_file_bytes')
        response = read(ticket(), 'bytes=7-31')
        require(response.status_code == 206 and response.content == payload[7:32]
                and response.headers['Content-Range'] == 'bytes 7-31/' + str(len(payload)), 'native_range')
        range_request = response.headers['X-Request-ID']
        checks.append('native_range_bytes')
        with db.cursor() as cursor:
            for request_id, size in ((full_request, len(payload)), (range_request, 25)):
                cursor.execute('SELECT event_payload FROM cf_audit_event WHERE request_id=%s '
                               "AND source='fileserver' ORDER BY id", (request_id,))
                events = [json.loads(row[0]) for row in cursor.fetchall()]
                require([event['result'] for event in events] == ['attempted', 'stream_completed'], 'audit_terminal')
                require(all(event['actor_user_id'] == 'fixture-user-1' and event['repo_id'] == repo
                            and event['path'] == '/probe.txt' for event in events)
                        and events[-1]['bytes_sent'] == size, 'audit_native_origin')
        checks.append('native_attempted_terminal_audit')
        pending = ticket()
        rule = str(uuid4())
        subject = dict(type='user', provider='etech', namespace='user', external_id='fixture-user-1')
        # Seed a restrictive fixture row after issuance; no permission solver
        # or native verifier is replaced. Actual C must read this committed deny.
        with db.cursor() as cursor:
            cursor.execute('INSERT INTO cf_dir_acl(id,repo_id,path,path_hash,kind,subject_type,provider,'
                'namespace,external_id,subject_hash,permission,inherit,revision) '
                'VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                (rule, repo, '/probe.txt', hashlib.sha256(b'/probe.txt').hexdigest(), 'file',
                 'user', 'etech', 'user', 'fixture-user-1',
                 hashlib.sha256(json.dumps(subject, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
                 'none', 0, str(uuid4())))
        response = read(pending)
        require(response.status_code in (401, 403, 503) and response.content != payload, 'current_cf_acl_denied')
        if web:
            require(update(current_head).status_code == 403, 'web_cf_acl_update_denied')
            require(seafile_api.get_repo(repo).head_cmmt_id == current_head, 'web_cf_acl_no_publication')
            checks.append('web_current_cf_acl_update_denied')
        with db.cursor() as cursor:
            cursor.execute('DELETE FROM cf_dir_acl WHERE id=%s', (rule,))
        checks.append('native_current_cf_acl_denied')
        pending = ticket()
        seafile_api.remove_share(repo, manager.username, user.username)
        response = read(pending)
        require(response.status_code in (401, 403, 503) and response.content != payload,
                'current_ce_revocation_denied')
        checks.append('native_current_permission_revocation_denied')
        return checks
    finally:
        transport.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
