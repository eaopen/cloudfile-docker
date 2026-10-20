"""Focused canonical-path settings and real nginx proxy checks; no CE retesting."""
import ast
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen


# Archived with the historical V2 launcher it exercises.
BUILD = Path(__file__).resolve().parents[1] / 'v2'
spec = importlib.util.spec_from_file_location('web_paths', BUILD / 'web_paths.py')
paths = importlib.util.module_from_spec(spec)
spec.loader.exec_module(paths)


class SettingsTest(unittest.TestCase):
    def test_seeded_login_settings_are_preserved_without_executing_python(self):
        with tempfile.TemporaryDirectory() as directory:
            filename = Path(directory) / 'seahub_settings.py'
            self.assertEqual(paths.read_settings(filename, {'LOGIN_URL'}), {})
            filename.write_text("OAUTH_OIDC_ISSUER = 'https://idp.example.test/'\n"
                                "OAUTH_CLIENT_ID = 'fixture'\nLOGIN_URL = '/cfile/oidc/login/'\n"
                                "UNRELATED = 1 / 0\n")
            result = paths.read_settings(filename, {'LOGIN_URL'})
            self.assertEqual(result, {'OAUTH_OIDC_ISSUER': 'https://idp.example.test/',
                                      'OAUTH_CLIENT_ID': 'fixture', 'LOGIN_URL': '/cfile/oidc/login/'})
            filename.write_text('OAUTH_CLIENT_ID = get_from_network()')
            with self.assertRaises(ValueError):
                paths.read_settings(filename, set())

    def test_directory_connection_survives_restart_without_new_enable_switch(self):
        # Losing these inputs on restart would disable current-subject TTL proof.
        with tempfile.TemporaryDirectory() as directory:
            filename=Path(directory)/'seahub_settings.py'
            filename.write_text("CF_DIRECTORY_URL = 'https://eap.example.test/eap/cloudDrive/directory'\n"
                                "CF_DIRECTORY_KEY_ID = 'fixture-key'\n"
                                "CF_DIRECTORY_GROUP_OWNER = 'service@auth.local'\n"
                                "UNRELATED = 1 / 0\n")
            result=paths.read_settings(filename,set())
            self.assertEqual(set(result),{'CF_DIRECTORY_URL','CF_DIRECTORY_KEY_ID','CF_DIRECTORY_GROUP_OWNER'})
            self.assertEqual(result['CF_DIRECTORY_GROUP_OWNER'],'service@auth.local')

    def test_native_child_inherits_the_same_canonical_root_as_hub(self):
        # Native C/Go build internal ACL URLs from their process environment,
        # not seahub_settings.py. Execute the real export block for both roots.
        import os
        import sys
        from types import SimpleNamespace
        tree = ast.parse((BUILD / 'start-dev.py').read_text())
        exports = next(node for node in tree.body if isinstance(node, ast.For)
                       and isinstance(node.iter, ast.Call)
                       and isinstance(node.iter.func, ast.Attribute)
                       and isinstance(node.iter.func.value, ast.Dict)
                       and any(isinstance(key, ast.Constant) and key.value == 'SEAFILE_RPC_PIPE_PATH'
                               for key in node.iter.func.value.keys))
        code = compile(ast.Module(body=[exports], type_ignores=[]), '<native-env-export>', 'exec')
        with tempfile.TemporaryDirectory() as directory:
            for canonical in ('/cfile/', '/seafile/'):
                settings = paths.web_settings('https://files.example.test', {'SITE_ROOT': canonical},
                                              existing=canonical == '/seafile/')
                environ = dict(os.environ, SITE_ROOT='/stale-inherited-root/')
                scope = dict(os=SimpleNamespace(environ=environ), host='localhost',
                             user='fixture', password='fixture-only',
                             names={'account':'accounts','files':'files','hub':'hub'},
                             conf=Path(directory), data=Path(directory), ccnet=Path(directory),
                             logs=Path(directory), settings=settings)
                exec(code, scope)
                actual = subprocess.check_output(
                    [sys.executable, '-c', 'import os; print(os.environ["SITE_ROOT"])'],
                    env=environ, text=True).strip()
                self.assertEqual(actual, settings['SITE_ROOT'])

    def test_fresh_defaults_use_cloudfile_paths(self):
        result = paths.web_settings('https://files.example.test/', {}, existing=False)
        self.assertEqual(result['SITE_ROOT'], '/cfile/')
        self.assertEqual(result['FILE_SERVER_ROOT'], 'https://files.example.test/cfhttp')
        self.assertEqual(result['SERVICE_URL'], 'https://files.example.test/cfile')
        self.assertEqual(result['STATIC_URL'], '/cfile/media/assets/')
        self.assertEqual(result['SESSION_COOKIE_PATH'], '/')

    def test_existing_canonical_and_file_path_are_preserved(self):
        for root, file_path in (('/seafile/', '/seafhttp'), ('/cfile/', '/cfhttp')):
            previous = {'SITE_ROOT': root, 'FILE_SERVER_ROOT': 'https://old.example.test' + file_path}
            result = paths.web_settings('https://files.example.test', previous, existing=True)
            self.assertEqual(result['SITE_ROOT'], root)
            self.assertEqual(result['FILE_SERVER_ROOT'], 'https://files.example.test' + file_path)
        self.assertEqual(paths.web_settings('http://files.example.test', {}, existing=True)['SITE_ROOT'], '/seafile/')

    def test_invalid_origin_and_canonical_cannot_enter_nginx(self):
        for origin in ('https://files.example.test/cfile', 'file:///tmp', 'https://user:password@files.example.test'):
            with self.assertRaises(ValueError):
                paths.web_settings(origin, {}, existing=False)
        with self.assertRaises(ValueError):
            paths.nginx_config('__CF_CANONICAL__', '/cfile/; include bad;')


    def test_fileserver_proxies_overwrite_client_real_ip(self):
        # The Go fileserver records X-Real-IP from loopback as the Checkout IP,
        # so every nginx location in front of it must replace the client value.
        root = Path(__file__).resolve().parents[4]
        for name in ('docs/history/storage-build-20261020/v2/nginx-dev.conf', 'services/seafile.nginx.conf',
                     'templates/seafile.nginx.conf.template'):
            for block in (root / name).read_text().split('location')[1:]:
                if 'proxy_pass http://127.0.0.1:8082' in block:
                    self.assertIn('proxy_set_header X-Real-IP $remote_addr;', block, name)


class DefaultCapabilitySourceTest(unittest.TestCase):
    def test_no_manual_enable_flags_or_native_guard_toggle(self):
        startup = (BUILD / 'start-dev.py').read_text()
        for legacy in ('CF_V2_CHECKOUT_ENABLED', 'CF_V2_AGENT_EDIT_ENABLED',
                       'CF_ENABLE_SEARCH', 'CF_PROVIDER_SEARCH', 'v2_edit_enabled'):
            self.assertNotIn(legacy, startup)

    def test_fresh_checkout_schema_and_reused_guard_verify(self):
        startup = (BUILD / 'start-dev.py').read_text()
        self.assertIn("if guard_installed:", startup)
        self.assertIn(").verify()", startup)
        self.assertIn(").install()", startup)
        self.assertIn("if settings.get('CF_MEILISEARCH_URL'):", startup)



class Echo(BaseHTTPRequestHandler):
    def do_GET(self):
        body = self.rfile.read(int(self.headers.get('Content-Length', '0')))
        payload = json.dumps({'path': self.path, 'method': self.command,
                              'body': body.decode(), 'cookie': self.headers.get('Cookie'),
                              'csrf': self.headers.get('X-CSRFToken')}).encode()
        self.send_response(206 if self.headers.get('Range') else 200)
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    do_POST = do_PUT = do_DELETE = do_GET

    def log_message(self, *unused):
        pass


@unittest.skipUnless(shutil.which('nginx'), 'real nginx required (available in the V2 build base)')
class ProxyTest(unittest.TestCase):
    def test_aliases_preserve_methods_bodies_query_cookies_and_range(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media = root / 'media'
            media.mkdir()
            (media / 'asset.txt').write_text('static asset')
            servers = [ThreadingHTTPServer(('127.0.0.1', port), Echo) for port in (8000, 8082)]
            for server in servers:
                threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                for canonical in ('/cfile/', '/seafile/'):
                    with self.subTest(canonical=canonical):
                        config = paths.nginx_config((BUILD / 'nginx-dev.conf').read_text(), canonical)
                        config = config.replace('listen 80;', 'listen 18880;')
                        config = config.replace('/run/nginx.pid', str(root / 'nginx.pid'))
                        config = config.replace('/opt/cloudfile-v2/source/seahub/media', str(media))
                        # CI runs as an ordinary user; keep all nginx scratch
                        # paths inside this test's disposable directory.
                        scratch = '\n'.join(f'{kind}_temp_path {root / kind};'
                                            for kind in ('client_body', 'proxy', 'fastcgi', 'uwsgi', 'scgi'))
                        config = config.replace('http {', 'http {\n' + scratch)
                        filename = root / 'nginx.conf'
                        filename.write_text(config)
                        subprocess.run(['nginx', '-t', '-e', 'stderr', '-c', str(filename)], check=True, capture_output=True)
                        process = subprocess.Popen(['nginx', '-e', 'stderr', '-c', str(filename), '-g', 'daemon off;'],
                                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        try:
                            for attempt in range(40):
                                try:
                                    with urlopen('http://127.0.0.1:18880/cfile/ready', timeout=1):
                                        break
                                except OSError:
                                    if process.poll() is not None or attempt == 39:
                                        raise
                                    time.sleep(.05)
                            for prefix in ('cfile', 'seafile'):
                                for method in ('POST', 'PUT', 'DELETE'):
                                    request = Request('http://127.0.0.1:18880/' + prefix + '/api/write/?a=one%20two',
                                                      data=b'payload', method=method,
                                                      headers={'Cookie': 'sessionid=same', 'X-CSRFToken': 'csrf'})
                                    with urlopen(request, timeout=3) as response:
                                        self.assertEqual(response.status, 200)
                                        self.assertEqual(json.load(response), {
                                            'path': canonical + 'api/write/?a=one%20two', 'method': method,
                                            'body': 'payload', 'cookie': 'sessionid=same', 'csrf': 'csrf'})
                                with urlopen('http://127.0.0.1:18880/' + prefix + '/media/asset.txt', timeout=3) as response:
                                    self.assertEqual(response.read(), b'static asset')
                            for prefix in ('cfhttp', 'seafhttp'):
                                request = Request('http://127.0.0.1:18880/' + prefix + '/files/token/name?a=1',
                                                  headers={'Range': 'bytes=0-3'})
                                with urlopen(request, timeout=3) as response:
                                    self.assertEqual(response.status, 206)
                                    self.assertEqual(json.load(response)['path'], '/files/token/name?a=1')
                        finally:
                            process.terminate()
                            process.wait(timeout=5)
            finally:
                for server in servers:
                    server.shutdown()
                    server.server_close()
