"""Run only inside smoke_ce14_runtime's disposable, initialized CE14 container.

Actual TLS OIDC/directory fixture, SQL/native RPC and full Django request chain.
This is not an Authentik deployment or real browser/TLS ingress acceptance.
"""
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import secrets
import ssl
import sys
import tempfile
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlsplit


def require(condition, label):
    if not condition:
        raise RuntimeError('identity_check=' + label)


def run():
    require(os.environ.get('CF_DISPOSABLE_IDENTITY_PROBE') == 'true', 'disposable_marker')
    scenario = os.environ.get('CF_IDENTITY_SCENARIO', 'prebound')
    require(scenario in {'prebound', 'provisioning', 'logout', 'backchannel', 'transfer', 'web', 'annotations', 'audit'}, 'identity_scenario')
    package = '/opt/seafile/seafile-server-latest'
    os.chdir(package + '/seahub')
    sys.path[:0] = [package + '/seahub', package + '/seahub/thirdpart',
                   package + '/seafile/lib/python3/site-packages', package + '/pro/python']
    os.environ.update(DJANGO_SETTINGS_MODULE='seahub.settings', SEAHUB_DIR=package + '/seahub',
        SEAFES_DIR=package + '/pro/python', SEAFILE_DATA_DIR='/shared/seafile/seafile-data',
        SEAFILE_CENTRAL_CONF_DIR='/shared/seafile/conf',
        SEAFILE_RPC_PIPE_PATH=package + '/runtime')
    import django
    django.setup()
    from django.conf import settings
    from django.contrib.sessions.models import Session
    from django.test import Client
    from django.urls import clear_url_caches
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    import jwt
    import pymysql
    import redis
    import requests
    from seaserv import ccnet_api
    from seahub.base.accounts import User
    from seahub.profile.models import Profile
    from seahub.auth import SESSION_KEY, BACKEND_SESSION_KEY
    from cloudfile_extensions.authorization import gunicorn
    from cloudfile_extensions.identity.configuration import configure_oidc_host, LOGIN_PREFIX
    from cloudfile_extensions.identity.management import IdentityManagement
    from cloudfile_extensions.identity.native_session import BACKEND
    from cloudfile_extensions.schema.runner import SchemaRunner

    checks = []
    stage = 'schema'
    db = pymysql.connect(host='db', user=os.environ['SEAFILE_MYSQL_DB_USER'],
        password=os.environ['SEAFILE_MYSQL_DB_PASSWORD'], database='seafile_db',
        autocommit=True, charset='utf8mb4')
    cache = redis.Redis(host='identity-redis', port=6379, socket_timeout=2)
    server = None
    schema_failure = None
    try:
        runner = SchemaRunner(db)
        original_query = runner._query
        def diagnostic_query(sql, parameters=()):
            nonlocal schema_failure
            try:
                return original_query(sql, parameters)
            except Exception as failure:
                schema_failure = (type(failure).__name__, failure.args[0] if failure.args and isinstance(failure.args[0], int) else None)
                raise
        runner._query = diagnostic_query
        runner.apply()
        SchemaRunner(db).require_current()
        checks.append(stage)
        stage = 'native_fixture'
        manager = User.objects.get(email='admin@smoke.invalid')
        Profile.objects.add_or_update(manager.username, login_id='fixture-manager')
        user = User.objects.create_user('oidc-user@smoke.invalid', password=secrets.token_hex(24),
                                       is_active=True, is_staff=False)
        # Seed real native groups through existing RPC; only mapping ownership
        # is fixture data. The normal projection owns its SQL effects.
        dept = ccnet_api.create_group('Fixture department', manager.username, parent_group_id=-1)
        role = ccnet_api.create_group('Fixture role', manager.username)
        manual = ccnet_api.create_group('Fixture manual group', manager.username)
        ccnet_api.group_add_member(manual, manager.username, user.username)
        with db.cursor() as cursor:
            for kind, namespace, external_id, group in (
                    ('dept', 'directory', 'dept-1', dept), ('group', 'role', 'role-1', role)):
                cursor.execute('INSERT INTO cf_sso_group_map(provider,subject_type,namespace,external_id,group_id,name) '
                               'VALUES(%s,%s,%s,%s,%s,%s)', ('etech', kind, namespace, external_id, group, external_id))
        checks.append(stage)
        stage = 'tls_fixture'
        signing_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        tls_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'CloudFile disposable IdP')])
        now = datetime.now(timezone.utc)
        certificate = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(tls_key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(hours=1))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]),
                           critical=False).sign(tls_key, hashes.SHA256()))
        with tempfile.TemporaryDirectory(prefix='cf-identity-') as temporary:
            ca_file = Path(temporary) / 'ca.pem'
            key_file = Path(temporary) / 'tls.pem'
            ca_file.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
            key_file.write_bytes(tls_key.private_bytes(serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
            key_file.chmod(0o600)
            codes, tokens = {}, {}
            fixture = {'mode': 'active', 'claim_user': 'fixture-user-1',
                'claim_sub': 'fixture-subject-1', 'directory_calls': 0, 'calls_by_user': {},
                'issued_ids': set(), 'rp_requests': 0, 'rp_mode': 'active'}
            origin = ''
            redirect_uri = 'https://cloudfile-smoke.invalid/' + LOGIN_PREFIX + 'callback/'
            client_secret = secrets.token_hex(32)
            directory_secret = secrets.token_hex(32)

            class Handler(BaseHTTPRequestHandler):
                def log_message(self, *args):
                    pass  # Codes, bearer tokens and credentials never go to diagnostics.

                def respond(self, value, status=200):
                    body = json.dumps(value).encode()
                    self.send_response(status)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Content-Length', str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)

                def do_GET(self):
                    path = urlsplit(self.path)
                    if path.path == '/authorize':
                        params = parse_qs(path.query)
                        required = {'state', 'nonce', 'code_challenge', 'code_challenge_method',
                                    'redirect_uri', 'client_id', 'response_type', 'scope'}
                        if (set(params) != required or any(len(v) != 1 for v in params.values())
                                or params['code_challenge_method'] != ['S256']
                                or params['redirect_uri'] != [redirect_uri]
                                or params['client_id'] != ['fixture-client']
                                or params['response_type'] != ['code']):
                            return self.respond({}, 400)
                        code = secrets.token_urlsafe(32)
                        codes[code] = {key: value[0] for key, value in params.items()}
                        self.send_response(302)
                        self.send_header('Location', redirect_uri + '?' + urlencode({
                            'state': params['state'][0], 'code': code}))
                        self.send_header('Content-Length', '0')
                        self.end_headers()
                    elif path.path == '/jwks':
                        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(signing_key.public_key()))
                        self.respond({'keys': [{**jwk, 'kid': 'fixture-key', 'use': 'sig', 'alg': 'RS256'}]})
                    elif path.path == '/userinfo':
                        token = self.headers.get('Authorization', '').removeprefix('Bearer ')
                        if token not in tokens:
                            return self.respond({}, 401)
                        self.respond(tokens[token])
                    elif (path.path.startswith('/directory/users/') and path.path.endswith('/context')
                            and path.path.count('/') == 4):
                        user_id = path.path.split('/')[3]
                        fixture['directory_calls'] += 1
                        count = fixture['calls_by_user'].get(user_id, 0) + 1
                        fixture['calls_by_user'][user_id] = count
                        if self.headers.get('Authorization') != 'Bearer ' + directory_secret:
                            return self.respond({}, 401)
                        if fixture['mode'] == 'outage' or count == fixture.get('fail_fetch'):
                            return self.respond({}, 503)
                        disabled = fixture['mode'] == 'disabled'
                        self.respond({'userId': user_id,
                            'status': 'disabled' if disabled else 'active', 'attributes': {},
                            'organizations': [] if disabled else [{'namespace': 'directory',
                                'external_id': 'dept-1', 'is_primary': True}],
                            'organization_ancestors': [],
                            'roles': [] if disabled else [{'namespace': 'role', 'external_id': 'role-1'}],
                            'revision': '1', 'etag': 'fixture-v1',
                            'generated_at': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')})
                    else:
                        self.respond({}, 404)

                def do_POST(self):
                    if self.path == '/logout':
                        length = int(self.headers.get('Content-Length', '0'))
                        if not 0 < length <= 65536:
                            return self.respond({}, 400)
                        params = parse_qs(self.rfile.read(length).decode())
                        if (set(params) != {'id_token_hint', 'post_logout_redirect_uri', 'state'}
                                or any(len(value) != 1 for value in params.values())
                                or params['id_token_hint'][0] not in fixture['issued_ids']
                                or params['post_logout_redirect_uri'] != [
                                    'https://cloudfile-smoke.invalid/' + LOGIN_PREFIX + 'logout/return/']):
                            return self.respond({}, 400)
                        jwt.decode(params['id_token_hint'][0], signing_key.public_key(),
                            algorithms=['RS256'], issuer=origin, audience='fixture-client')
                        fixture['rp_requests'] += 1
                        if fixture['rp_mode'] == 'outage':
                            return self.respond({}, 503)
                        self.send_response(302)
                        self.send_header('Location', params['post_logout_redirect_uri'][0] + '?' + urlencode({
                            'state': params['state'][0]}))
                        self.send_header('Content-Length', '0')
                        self.end_headers()
                        return
                    if self.path != '/token':
                        return self.respond({}, 404)
                    length = int(self.headers.get('Content-Length', '0'))
                    if not 0 < length <= 8192:
                        return self.respond({}, 400)
                    params = parse_qs(self.rfile.read(length).decode())
                    code = params.get('code', [''])[0]
                    transaction = codes.pop(code, None)
                    basic = 'Basic ' + base64.b64encode(('fixture-client:' + client_secret).encode()).decode()
                    verifier = params.get('code_verifier', [''])[0]
                    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
                    if (transaction is None or self.headers.get('Authorization') != basic
                            or challenge != transaction['code_challenge']
                            or params.get('redirect_uri') != [redirect_uri]
                            or params.get('grant_type') != ['authorization_code']):
                        return self.respond({}, 400)
                    token = secrets.token_urlsafe(32)
                    tokens[token] = {'sub': fixture['claim_sub'], 'userId': fixture['claim_user']}
                    issued = int(time.time())
                    id_token = jwt.encode({'iss': origin, 'aud': 'fixture-client',
                        'sub': fixture['claim_sub'], 'userId': fixture['claim_user'],
                        'iat': issued, 'exp': issued + 300, 'nonce': transaction['nonce'],
                        'sid': fixture.get('session_sid') or secrets.token_urlsafe(16)}, signing_key, algorithm='RS256',
                        headers={'kid': 'fixture-key'})
                    fixture['issued_ids'].add(id_token)
                    self.respond({'access_token': token, 'token_type': 'Bearer',
                                  'expires_in': 300, 'id_token': id_token})

            server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
            origin = 'https://127.0.0.1:' + str(server.server_port)
            tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            tls.load_cert_chain(str(ca_file), str(key_file))
            server.socket = tls.wrap_socket(server.socket, server_side=True)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            settings.CLOUDFILE_POLICY_CONFIG = {'database': {'host': 'db',
                'user': os.environ['SEAFILE_MYSQL_DB_USER'], 'name': 'seafile_db',
                'password': os.environ['SEAFILE_MYSQL_DB_PASSWORD']},
                'redis': {'host': 'identity-redis', 'port': 6379, 'password': ''},
                'provider': 'etech', 'native_schema': 'ccnet_db', 'identity_schema': 'seahub_db',
                'directory_url': origin + '/directory', 'directory_ca_bundle': str(ca_file),
                'directory_bearer_token': directory_secret, 'attribute_allowlist': [],
                'core_library': package + '/seafile/lib/libcloudfile_acl.so.1', 'cloud_mode': False}
            settings.CLOUDFILE_OIDC_ENABLED = True
            settings.CLOUDFILE_OIDC_JIT_ENABLED = scenario == 'provisioning'
            settings.CLOUDFILE_OIDC_CONFIG = {'issuer': origin, 'client_id': 'fixture-client',
                'client_secret': client_secret, 'redirect_uri': redirect_uri,
                'authorization_url': origin + '/authorize', 'token_url': origin + '/token',
                'userinfo_url': origin + '/userinfo', 'jwks_url': origin + '/jwks',
                'ca_bundle': str(ca_file)}
            if scenario in {'logout', 'backchannel'}:
                settings.CLOUDFILE_OIDC_CONFIG.update(end_session_url=origin + '/logout',
                    post_logout_redirect_uri='https://cloudfile-smoke.invalid/' + LOGIN_PREFIX + 'logout/return/')
            settings.CLOUDFILE_OIDC_BACKCHANNEL_ENABLED = scenario == 'backchannel'
            settings.ENABLE_OAUTH = False
            configure_oidc_host(settings)
            if scenario in {'transfer', 'web', 'audit'}:
                machine_secret, delegation_secret = secrets.token_hex(32), secrets.token_hex(32)
                settings.CLOUDFILE_POLICY_CONFIG.update(
                    service_credentials={'login-v1': {'service_id': 'etech-login',
                        'issuer': 'etech-login', 'audience': 'cloudfile-authorization',
                        'secret': machine_secret, 'scopes': ['subject.refresh', 'user.delegation.issue'],
                        'maximum_ttl': 120}}, refresh_provider_grants={'etech-login': ['etech']},
                    delegation_signing_keys={'etech-login': {'kid': 'delegation-v1',
                        'issuer': 'cloudfile', 'audience': 'cloudfile-download', 'secret': delegation_secret}})
                settings.CLOUDFILE_AUTHORIZATION_ENABLED = True
                settings.CLOUDFILE_TRANSFER_ENABLED = scenario in {'transfer', 'web'}
            if scenario == 'annotations':
                from seaserv import seafile_api
                from cloudfile_extensions.resources.native import NativeResourceReader
                settings.CLOUDFILE_ANNOTATIONS_ENABLED = True
                # The base fixture explicitly disables OIDC discovery; opt in
                # here without weakening the production explicit-disable rule.
                settings.CLOUDFILE_CAPABILITIES = dict(settings.CLOUDFILE_CAPABILITIES, **{'auth.oidc': True})
                settings.CLOUDFILE_SYSTEM_TAG_PROVIDER_ENABLED = True
                from cloudfile_extensions.identity.service_tokens import ServiceCredential
                settings.CLOUDFILE_SYSTEM_TAG_PROVIDER_CREDENTIALS = {'tags-v1': ServiceCredential(
                    'etech-tags', 'etech-tags', 'cloudfile-tags', secrets.token_bytes(32),
                    frozenset({'tags.system.write'}))}
                settings.CLOUDFILE_SYSTEM_TAG_PROVIDER_GRANTS = {'etech-tags': dict(
                    provider='etech', namespaces=['etech:project'])}
                settings.CLOUDFILE_RESOURCE_SECRET = secrets.token_bytes(32)
                settings.CLOUDFILE_RESOURCE_LIFECYCLE_READER = NativeResourceReader(seafile_api)
            if scenario == 'audit':
                result_root = Path(temporary) / 'audit-results'
                result_root.mkdir(mode=0o700)
                settings.CLOUDFILE_AUTHORIZATION_ENABLED = True
                settings.CLOUDFILE_AUDIT_QUERY_ENABLED = True
                settings.CLOUDFILE_AUDIT_EXPORT_ENABLED = True
                settings.CLOUDFILE_AUDIT_CURSOR_SECRET = secrets.token_bytes(32)
                settings.CLOUDFILE_AUDIT_RESULT_ROOT = str(result_root)
            gunicorn.post_worker_init(None)
            clear_url_caches()
            management = IdentityManagement(db, native_schema='ccnet_db', identity_schema='seahub_db',
                directory_provider='etech', actor_user_id='fixture-manager', request_id='fixture-prebind')
            stage = 'authorized_prebind'
            management.prebind(issuer=origin, subject='fixture-subject-1', user_id='fixture-user-1',
                username=user.username, reason='Disposable identity runtime fixture')
            checks.append(stage)
            prefix = '/' + LOGIN_PREFIX

            def initiate(browser):
                begin = browser.get(prefix + 'begin/', secure=True, HTTP_HOST='cloudfile-smoke.invalid')
                require(begin.status_code == 302, 'begin_status_' + str(begin.status_code))
                with requests.Session() as transport:
                    transport.trust_env = False
                    authorize = transport.get(begin['Location'], verify=str(ca_file),
                                              allow_redirects=False, timeout=10)
                require(authorize.status_code == 302, 'authorize')
                callback = urlsplit(authorize.headers['Location'])
                return callback.path + '?' + callback.query

            def complete(browser, callback):
                response = browser.get(callback, secure=True, HTTP_HOST='cloudfile-smoke.invalid')
                # Django Client retains expired cookies; an actual browser
                # removes them. Model deletion without changing host guards.
                for name, cookie in response.cookies.items():
                    if str(cookie['max-age']) == '0' and name in browser.cookies:
                        del browser.cookies[name]
                return response

            if scenario == 'annotations':
                stage = 'annotations_http'
                from annotations_http_runtime import exercise
                checks.extend(exercise(db=db, user=user, manager=manager,
                    initiate=initiate, complete=complete, require=require))
                return dict(result='passed', checks=checks,
                    scope='Actual OIDC TLS fixture/session, shared native qualification/C Policy Core, native resource history and HTTP/SQL; no external eTech or deployment acceptance')

            if scenario == 'audit':
                stage = 'audit_export_http'
                from audit_export_runtime import exercise
                checks.extend(exercise(db=db, user=user, initiate=initiate, complete=complete,
                    require=require, configuration_dir=temporary))
                return dict(result='passed', checks=checks,
                    scope='Controlled OIDC/native policy, audit HTTP, standalone worker and private CSV delivery; no external eTech or browser acceptance')

            if scenario == 'provisioning':
                stage = 'jit_provisioning'
                from identity_provisioning_runtime import exercise
                checks.extend(exercise(db=db, fixture=fixture, origin=origin, prefix=prefix,
                    initiate=initiate, complete=complete, require=require, groups={dept, role},
                    configuration_dir=temporary))
                return {'result': 'passed', 'checks': checks,
                    'scope': 'TLS fixture JIT worker, real native SQL/RPC, pending proofs and fresh OIDC login; no external IdP/eTech/ingress claim'}

            if scenario == 'logout':
                stage = 'rp_logout'
                from identity_logout_runtime import exercise
                checks.extend(exercise(db=db, fixture=fixture, origin=origin, prefix=prefix,
                    initiate=initiate, complete=complete, require=require, ca_bundle=str(ca_file)))
                return {'result': 'passed', 'checks': checks,
                    'scope': 'Actual RP logout form/HTTPS fixture/return and native session SQL; Django Client, no real IdP/global logout/browser ingress claim'}

            if scenario == 'backchannel':
                stage = 'backchannel_logout'
                from identity_backchannel_runtime import exercise
                def claims(token):
                    return jwt.decode(token, signing_key.public_key(), algorithms=['RS256'],
                        issuer=origin, audience='fixture-client')
                def notification(values):
                    issued = int(time.time())
                    value = {'iss': origin, 'aud': 'fixture-client', 'iat': issued, 'exp': issued + 300,
                        'jti': secrets.token_urlsafe(24),
                        'events': {'http://schemas.openid.net/event/backchannel-logout': {}}, **values}
                    return jwt.encode(value, signing_key, algorithm='RS256',
                        headers={'kid': 'fixture-key', 'typ': 'logout+jwt'})
                checks.extend(exercise(db=db, fixture=fixture, prefix=prefix,
                    initiate=initiate, complete=complete, require=require, configuration_dir=temporary,
                    claims=claims, notification=notification))
                return {'result': 'passed', 'checks': checks,
                    'scope': 'Hosted cookie-free backchannel, real JWT/JWKS TLS, native SQL/session fences and standalone deletion process; Django Client, no external IdP/eTech/ingress claim'}

            if scenario in {'transfer', 'web'}:
                stage = 'delegated_transfer'
                from delegated_transfer_runtime import exercise
                checks.extend(exercise(db=db, user=user, manager=manager, machine_secret=machine_secret,
                    initiate=initiate, complete=complete, require=require,
                    certificate=str(ca_file), tls_key=str(key_file), package=package, web=scenario == 'web'))
                return {'result': 'passed', 'checks': checks,
                    'scope': ('OIDC Web read/manual replacement via full Django Client plus actual C/Go bytes/Range; ' if scenario == 'web' else '') + 'controlled HTTPS service delegation; no actual browser/external eTech/production ingress claim'}

            stage = 'cold_cache_login'
            browser = Client(enforce_csrf_checks=True)
            browser.get('/accounts/login/', secure=True, HTTP_HOST='cloudfile-smoke.invalid')
            callback = initiate(browser)
            response = complete(browser, callback)
            require(response.status_code == 302, 'callback_status_' + str(response.status_code))
            session = browser.session
            require(session[SESSION_KEY] == user.username and session[BACKEND_SESSION_KEY] == BACKEND,
                    'native_session_identity')
            require(Session.objects.filter(session_key=session.session_key).exists(), 'persisted_session')
            with db.cursor() as cursor:
                cursor.execute('SELECT group_id FROM ccnet_db.GroupUser WHERE user_name=%s', (user.username,))
                require({row[0] for row in cursor.fetchall()} == {dept, role, manual}, 'owned_projection')
                cursor.execute('SELECT COUNT(*) FROM cf_oidc_session')
                require(cursor.fetchone()[0] == 1, 'session_index')
            require(fixture['directory_calls'] == 1, 'cold_directory_fetch')
            checks.append(stage)
            stage = 'session_reload'
            require(browser.get('/api2/account/info/', secure=True,
                    HTTP_HOST='cloudfile-smoke.invalid').status_code == 200, 'guarded_native_account')
            checks.append(stage)
            stage = 'callback_replay'
            require(complete(Client(), callback).status_code == 401, 'browser_proof_replay')
            checks.append(stage)
            stage = 'local_logout'
            old_key = session.session_key
            # Existing CE login page supplies the browser's CSRF cookie.
            csrf = browser.cookies[settings.CSRF_COOKIE_NAME].value
            response = browser.post(prefix + 'logout/', data='', content_type='application/octet-stream',
                secure=True, HTTP_HOST='cloudfile-smoke.invalid',
                HTTP_ORIGIN='https://cloudfile-smoke.invalid', HTTP_X_CSRFTOKEN=csrf)
            require(response.status_code == 200, 'logout_status_' + str(response.status_code))
            require(not Session.objects.filter(session_key=old_key).exists(), 'session_deleted')
            with db.cursor() as cursor:
                cursor.execute('SELECT COUNT(*) FROM cf_oidc_session')
                require(cursor.fetchone()[0] == 0, 'index_deleted')
            checks.append(stage)
            for mode, claim, active, expected in (
                    ('active', 'conflicting-user', True, 409),
                    ('active', 'fixture-user-1', False, 403),
                    ('disabled', 'fixture-user-1', True, 403),
                    ('outage', 'fixture-user-1', True, 503)):
                stage = 'reject_' + ('claim_conflict' if claim != 'fixture-user-1' else
                    'native_disabled' if not active else mode)
                fixture.update(mode=mode, claim_user=claim)
                user.is_active = active
                user.save()
                cache.flushdb()  # Dedicated disposable Redis only.
                other = Client(enforce_csrf_checks=True)
                response = complete(other, initiate(other))
                require(response.status_code == expected, stage + '_status_' + str(response.status_code))
                require(not other.session.get(SESSION_KEY), stage + '_no_session')
                checks.append(stage)
            return {'result': 'passed', 'checks': checks,
                'scope': 'TLS test IdP/directory; actual CE SQL/RPC and Django client, no Authentik/eTech or ingress claim'}
    except Exception as error:
        label = str(error) if str(error).startswith('identity_check=') else (type(error).__name__ + ';frames=' + json.dumps([(item.filename.rsplit('/', 1)[-1], item.name, item.lineno) for item in traceback.extract_tb(error.__traceback__)]))
        if stage == 'schema':
            label += ';sql_failure=' + json.dumps(schema_failure)
            try:
                label += ';ledger=' + json.dumps([
                    {key: row[key] for key in ('version', 'state', 'step', 'error_code')}
                    for row in SchemaRunner(db).status() if row['state'] != 'applied'])
            except Exception:
                label += ';ledger_unavailable'
        raise RuntimeError('identity_stage=' + stage + ';' + label) from None
    finally:
        if gunicorn._host is not None:
            gunicorn.worker_exit(None, None)
        if server is not None:
            server.shutdown()
            server.server_close()
        cache.close()
        db.close()


if __name__ == '__main__':
    print(json.dumps(run()))
