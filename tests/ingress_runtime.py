#!/usr/bin/env python3
"""Actual nginx/TLS allowlist probe, with a transparent fixture upstream.

No new identity/ACL claim: those use existing packaged Web evidence. Only
routing, method closure and unchanged required headers/body/Range are tested.
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import secrets
import subprocess
import tempfile
import time

from smoke_ce14_runtime import docker

BACKEND = r'''
from datetime import datetime, timedelta, timezone
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'ingress')])
now = datetime.now(timezone.utc)
cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
 .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=1))
 .not_valid_after(now+timedelta(days=1)).add_extension(x509.SubjectAlternativeName([x509.DNSName('ingress')]), False)
 .sign(key, hashes.SHA256()))
Path('/tmp/cloudfile-ingress.crt').write_bytes(cert.public_bytes(serialization.Encoding.PEM))
Path('/tmp/cloudfile-ingress.key').write_bytes(key.private_bytes(serialization.Encoding.PEM,
 serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
Path('/tmp/cloudfile-ingress.key').chmod(0o600)
class Handler(BaseHTTPRequestHandler):
 def log_message(self, *args): pass
 def do_GET(self): self.respond()
 def do_HEAD(self): self.respond()
 def do_POST(self): self.respond()
 def do_DELETE(self): self.respond()
 def respond(self):
  body = self.rfile.read(int(self.headers.get('Content-Length', '0')))
  if self.path == '/seafhttp/cloudfile/read' and self.headers.get('Range') == 'bytes=2-6':
   self.send_response(206); self.send_header('Content-Range', 'bytes 2-6/13')
   data=b'CloudFile-TLS'[2:7]
  else:
   self.send_response(200)
   data=json.dumps(dict(path=self.path, method=self.command, body=body.decode(), headers=dict(self.headers))).encode()
  self.send_header('Content-Length', str(len(data))); self.end_headers()
  if self.command != 'HEAD': self.wfile.write(data)
HTTPServer(('0.0.0.0', 80), Handler).serve_forever()
'''
CLIENT = r'''
import base64, json, ssl, sys, urllib.request, urllib.error
r=json.load(sys.stdin)
request=urllib.request.Request('https://ingress'+r['path'], data=r.get('body', '').encode() if r['method']=='POST' else None,
 headers=r['headers'], method=r['method'])
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self, *args): return None
opener=urllib.request.build_opener(NoRedirect, urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile='/tmp/cloudfile-ingress.crt')))
try: response=opener.open(request, timeout=5)
except urllib.error.HTTPError as error: response=error
with response:
 print(json.dumps(dict(status=response.status, headers=dict(response.headers), body=base64.b64encode(response.read()).decode())))
'''


def run(image):
    root = Path(__file__).resolve().parents[1]
    config = root / 'deploy/v0.2/nginx.conf'
    config_hash = hashlib.sha256(config.read_bytes()).hexdigest()
    prefix = 'cf02-ingress-' + secrets.token_hex(6)
    network, backend, ingress = prefix + '-net', prefix + '-backend', prefix + '-proxy'
    containers = []
    started = time.monotonic()
    checks = []
    docker('network', 'create', '--internal', network)
    try:
        containers.append(backend)
        docker('run', '-d', '--name', backend, '--network', network, '--network-alias', 'cloudfile',
               '--entrypoint', 'python3', image, '-c', BACKEND)
        deadline = time.monotonic() + 10
        while True:
            try:
                docker('exec', backend, 'test', '-s', '/tmp/cloudfile-ingress.crt')
                break
            except RuntimeError:
                if time.monotonic() > deadline:
                    raise RuntimeError('ingress certificate fixture startup failed')
                time.sleep(0.2)
        with tempfile.TemporaryDirectory(prefix='cf02-ingress-tls-') as temporary:
            cert, key = Path(temporary) / 'cert.pem', Path(temporary) / 'key.pem'
            docker('cp', backend + ':/tmp/cloudfile-ingress.crt', str(cert))
            docker('cp', backend + ':/tmp/cloudfile-ingress.key', str(key))
            containers.append(ingress)
            docker('run', '-d', '--name', ingress, '--network', network, '--network-alias', 'ingress',
                '--read-only', '--tmpfs', '/tmp',
                '-v', str(config) + ':/etc/nginx/nginx.conf:ro',
                '-v', str(cert) + ':/run/secrets/cloudfile-ingress.crt:ro',
                '-v', str(key) + ':/run/secrets/cloudfile-ingress.key:ro',
                '--entrypoint', '/usr/sbin/nginx', image, '-e', '/dev/stderr', '-g', 'daemon off;')
            try:
                docker('exec', ingress, '/usr/sbin/nginx', '-e', '/dev/stderr', '-t')
            except RuntimeError:
                # Only this owned fixture nginx logs config errors; no tokens.
                diagnostic = subprocess.run(['docker', 'logs', ingress], capture_output=True, text=True)
                raise RuntimeError('ingress_nginx=' + (diagnostic.stdout + diagnostic.stderr)[-2000:]) from None
            repo='12345678-1234-1234-1234-123456789abc'
            identity='/api/v2.1/cloudfile/extensions/identity/v1/'
            headers={'Authorization':'Bearer fixture-only', 'Cookie':'fixture=private',
                'Origin':'https://ingress', 'X-CSRFToken':'fixture-csrf',
                'X-Forwarded-Proto':'http', 'X-Forwarded-For':'untrusted', 'X-Forwarded-Host':'untrusted'}
            def request(path, method='GET', body='', extra=None):
                result=json.loads(docker('exec', '-i', backend, 'python3', '-c', CLIENT,
                    input=json.dumps(dict(path=path, method=method, body=body, headers={**headers, **(extra or {})}))))
                result['body']=base64.b64decode(result['body'])
                return result
            opened=[('/', 'GET'), ('/libraries/', 'GET'), ('/library/'+repo+'/Fixture/dir/', 'GET'),
                ('/media/assets/frontend/static/js/app.js', 'GET'), ('/api/v2.1/repos/', 'GET'),
                ('/api/v2.1/repos/'+repo+'/dir/?p=%2F', 'GET'), ('/api2/account/info/', 'GET'),
                (identity+'begin/', 'GET'), (identity+'callback/?state=fixture&code=fixture', 'GET'),
                (identity+'pending/', 'GET'), (identity+'pending/', 'POST'),
                (identity+'logout/', 'POST'), (identity+'logout/idp/', 'POST'),
                (identity+'logout/return/', 'GET'), (identity+'logout/backchannel/', 'POST'),
                (identity+'read-tickets/', 'POST'), (identity+'manual-upload/', 'POST'), (identity+'manual-update/', 'POST'),
                ('/api/v2.1/cloudfile/extensions/authorization/v1/delegations/', 'POST'),
                ('/api/v2.1/cloudfile/extensions/transfer/v1/delegated-read-tickets/', 'POST')]
            for path, method in opened:
                response=request(path, method, 'fixture body')
                assert response['status']==200, ('open',path,method,response['status'])
                received=json.loads(response['body'])
                assert received['path']==path and received['method']==method
                observed={k.lower():v for k,v in received['headers'].items()}
                assert observed['x-forwarded-proto']=='https' and observed['x-forwarded-host']=='ingress'
                assert observed['x-forwarded-for']!='untrusted'
                assert observed['authorization']==headers['Authorization'] and observed['cookie']==headers['Cookie']
                assert observed['x-csrftoken']==headers['X-CSRFToken']
                if method=='POST': assert received['body']=='fixture body'
            checks.append('golden_path_routes_methods_body_and_trusted_TLS_headers')
            ranged=request('/seafhttp/cloudfile/read', extra={'Range':'bytes=2-6'})
            assert ranged['status']==206 and ranged['body']==b'oudFi'
            assert ranged['headers']['Content-Range']=='bytes 2-6/13'
            checks.append('enhanced_read_Range_transport')
            login=request('/accounts/login/?next=/untrusted')
            assert login['status']==302 and login['headers']['Location'] in (identity+'begin/', 'https://ingress'+identity+'begin/')
            checks.append('legacy_login_redirects_to_OIDC')
            closed=['/api2/auth-token/', '/api2/repos/', '/api2/repos/'+repo+'/file/?p=/probe.txt',
                '/api/v2.1/repos/'+repo+'/file/', '/api/v2.1/repos/'+repo+'/history/',
                '/api/v2.1/repos/'+repo+'/trash/', '/api/v2.1/share-links/', '/api/v2.1/search/',
                '/seafhttp/files/ordinary/probe.txt', '/seafhttp/upload-api/ordinary', '/seafhttp/update-api/ordinary',
                '/seafhttp/repo/'+repo+'/commit/HEAD', '/seafdav/', '/:dir_browser', '/d/share/', '/f/share/',
                '/api/v2.1/cloudfile/extensions/migration/v1/scan/', '/sys/admin/', '/unknown/',
                '/api/v2.1/repos/'+repo+'/dir/extra', identity+'unknown/']
            for path in closed:
                assert request(path)['status']==403, path
            for path, method in [('/api/v2.1/repos/','POST'),('/api/v2.1/repos/'+repo+'/dir/','DELETE'),
                    (identity+'manual-update/','GET'),(identity+'logout/','GET'),('/media/assets/app.js','POST'),
                    ('/seafhttp/cloudfile/read','POST'),('/accounts/login/','POST')]:
                assert request(path,method)['status']==403, (path,method)
            checks.append('non_main_flow_and_wrong_methods_default_closed')
            return dict(result='passed',scope='actual nginx/TLS routing; transparent fixture backend, not business authorization revalidation',
                config_sha256=config_hash,image_id=json.loads(docker('image','inspect',image))[0]['Id'],
                open_cases=len(opened)+2,closed_cases=len(closed)+7,checks=checks,seconds=round(time.monotonic()-started,3))
    finally:
        for name in reversed(containers): docker('rm','-f',name)
        docker('network','rm',network)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image',default='cloudfile/cloudfile:14.0.8-v0.2-rc-app')
    print(json.dumps(run(parser.parse_args().image),indent=2))
