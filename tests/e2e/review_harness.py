#!/usr/bin/env python3
"""Shared plumbing for the P2-02 review-checklist E2E matrices.

Each `tests/e2e/review_<module>_matrix.py` imports this module so the nine
matrices don't each re-implement the same HTTP boilerplate. Cases live in
`docs/review-<module>-cases.json`; a matrix registers one executor per
api-channel case id and lets `run_cases()` do the counting and pass/fail
reporting.

Design notes:

* `channel` splits the contract into `api` (assertable over HTTP by the
  matrix) and `ui` (browser-only; reported as skipped here and deferred to a
  future browser suite). The matrix never invents an assertion for a ui case.
* Cases are expected to be RED in this phase: P2-02 writes the contract first,
  P2-03/P2-06/P2-07 turn them green. A failing assertion is a result, not a bug
  in this harness.
* Standard library only, like the other matrices.
"""

import argparse
import base64
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

#: set by `allow_insecure()`; mirrors the other matrices.
_SSL_CONTEXT = None

results = []


def allow_insecure():
    global _SSL_CONTEXT
    _SSL_CONTEXT = ssl._create_unverified_context()


def record(case_id, ok, detail=''):
    results.append((case_id, ok, detail))
    mark = '✓' if ok else '✗'
    line = f'  {mark} [{case_id}]'
    if not ok and detail:
        line += f'  {detail}'
    print(line, flush=True)


def request(url, method='GET', token=None, data=None, form=None,
            basic=None, headers=None, raw=False):
    """Return (status, body). HTTP errors do not raise — matrices assert 403s."""
    hdrs = dict(headers or {})
    body = None

    if token:
        hdrs['Authorization'] = f'Token {token}'
    if basic:
        cred = base64.b64encode(basic.encode()).decode()
        hdrs['Authorization'] = f'Basic {cred}'
    if form is not None:
        body = urllib.parse.urlencode(form).encode()
        hdrs['Content-Type'] = 'application/x-www-form-urlencoded'
    elif data is not None:
        body = data if isinstance(data, bytes) else data.encode()

    req = urllib.request.Request(url, data=body, method=method, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=60,
                                    context=_SSL_CONTEXT) as resp:
            payload = resp.read()
            return resp.status, payload if raw else payload.decode(errors='replace')
    except urllib.error.HTTPError as e:
        payload = e.read()
        return e.code, payload if raw else payload.decode(errors='replace')
    except Exception as e:                      # connection errors etc.
        return 0, str(e)


def json_body(body):
    try:
        return json.loads(body)
    except Exception:
        return None


class Context:
    """Runtime state shared by the setup and the executors of one matrix."""

    def __init__(self, base, admin_email, admin_password):
        self.base = base.rstrip('/')
        self.admin_email = admin_email
        self.admin_password = admin_password
        self.tokens = {}

    def api(self, path, method='GET', **kw):
        return request(self.base + path, method=method, **kw)

    def token(self, email, password):
        key = (email, password)
        if key not in self.tokens:
            token, _, _ = get_token(self.base, email, password)
            self.tokens[key] = token
        return self.tokens[key]


def wait_ready(base, timeout=600):
    print(f'等待 {base} 就绪（最多 {timeout}s）…', flush=True)
    deadline = time.time() + timeout
    last = ''
    while time.time() < deadline:
        status, body = request(base + '/api2/ping/')
        if status == 200 and 'pong' in body:
            print('  服务已就绪', flush=True)
            return True
        last = f'status={status} {body[:120]}'
        time.sleep(5)
    print(f'  超时：{last}', file=sys.stderr)
    return False


def get_token(base, email, password):
    status, body = request(base + '/api2/auth-token/', method='POST',
                           form={'username': email, 'password': password})
    data = json_body(body) or {}
    return data.get('token'), status, body


def resolve_identity(ctx, email):
    """Map a login email to the opaque Seafile identity used by share APIs."""
    status, body = ctx.api('/api/v2.1/admin/users/', token=ctx.token(
        ctx.admin_email, ctx.admin_password))
    for user in (json_body(body) or {}).get('data', []):
        if email in (user.get('email'), user.get('contact_email'),
                     user.get('login_id')):
            return user.get('email')
        if user.get('name') == email.split('@')[0]:
            return user.get('email')
    sys.exit(f'在用户列表里找不到 {email}: {status} {body[:200]}')


def create_user(ctx, email, password):
    """Create a user via the admin API; tolerate 'already exists'."""
    status, body = ctx.api('/api/v2.1/admin/users/', method='POST',
                           form={'email': email, 'password': password},
                           token=ctx.token(ctx.admin_email, ctx.admin_password))
    if status not in (200, 201) and 'exist' not in body.lower():
        sys.exit(f'建用户 {email} 失败: {status} {body}')
    token = ctx.token(email, password)
    if not token:
        sys.exit(f'无法取得 {email} 的 token')
    return token


def create_repo(ctx, token, name):
    status, body = ctx.api('/api2/repos/', method='POST',
                           form={'name': name}, token=token)
    repo_id = (json_body(body) or {}).get('repo_id')
    if not repo_id:
        sys.exit(f'建库失败: {status} {body}')
    return repo_id


def mkdir(ctx, token, repo_id, folder):
    status, body = ctx.api(f'/api2/repos/{repo_id}/dir/?p=/{folder}',
                           method='POST', form={'operation': 'mkdir'}, token=token)
    return status, body


def share_repo(ctx, admin_token, repo_id, user_id, perm):
    """Share a repo to a user. NOTE: this endpoint reports failures in the body
    with a static 200 — always inspect `failed`."""
    status, body = ctx.api(f'/api2/repos/{repo_id}/dir/shared_items/?p=/',
                           method='PUT',
                           form={'share_type': 'user', 'username': user_id,
                                 'permission': perm}, token=admin_token)
    failed = (json_body(body) or {}).get('failed') or []
    if status != 200 or failed:
        sys.exit(f'共享 {repo_id} 给 {user_id} ({perm}) 失败: {status} {body}')
    return True


def set_user_quota(ctx, admin_token, email, quota_mb):
    """Set a user's total quota in MB via the admin API (0 = unlimited)."""
    status, body = ctx.api(f'/api/v2.1/admin/users/{urllib.parse.quote(email)}/',
                           method='PUT',
                           form={'quota_total': str(quota_mb)}, token=admin_token)
    if status != 200:
        sys.exit(f'设置 {email} 配额 {quota_mb}MB 失败: {status} {body}')
    return True


def multipart(fields, filename, content):
    """Hand-build multipart so uploads don't pull in the requests dependency."""
    import uuid
    boundary = '----CloudFileReview' + uuid.uuid4().hex
    out = []
    for k, v in fields.items():
        out.append(f'--{boundary}\r\nContent-Disposition: form-data; '
                   f'name="{k}"\r\n\r\n{v}\r\n')
    out.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
               f'filename="{filename}"\r\n'
               f'Content-Type: application/octet-stream\r\n\r\n')
    body = ''.join(out).encode() + content + f'\r\n--{boundary}--\r\n'.encode()
    return body, f'multipart/form-data; boundary={boundary}'


def upload_file(ctx, token, repo_id, parent_dir, name, content=b'x',
                replace='0'):
    """Upload a small file via the Go fileserver upload-link.

    ``replace`` defaults to '0' (do not overwrite); pass '1' to create a new
    revision of an existing file (needed by the history matrix).
    """
    status, body = ctx.api(
        f'/api2/repos/{repo_id}/upload-link/?p={urllib.parse.quote(parent_dir)}',
        token=token)
    url = (body or '').strip('"')
    if status != 200 or not url.startswith('http'):
        return 0, f'取上传链接失败 status={status} {body[:160]}'
    data, ctype = multipart(
        {'parent_dir': parent_dir, 'replace': replace}, name, content)
    return request(url, method='POST', data=data, token=token,
                   headers={'Content-Type': ctype})


def update_file(ctx, token, repo_id, path, content):
    """Update an existing file via the Go fileserver update-link.

    Unlike upload-link replace=1 (which keeps an 'Added' commit desc), this
    produces a proper 'Modified' commit — needed by the history matrix to
    assert keyword search and operator filtering.
    """
    status, body = ctx.api(
        f'/api2/repos/{repo_id}/update-link/?p=/', token=token)
    url = (body or '').strip('"')
    if status != 200 or not url.startswith('http'):
        return 0, f'取更新链接失败 status={status} {body[:160]}'
    name = os.path.basename(path.rstrip('/'))
    data, ctype = multipart({'target_file': path}, name, content)
    return request(url, method='POST', data=data, token=token,
                   headers={'Content-Type': ctype})


def post_json(ctx, token, path, payload):
    """POST a JSON body (DRF endpoints like fileops/copy use request.data)."""
    return ctx.api(path, method='POST', token=token,
                   data=json.dumps(payload).encode(),
                   headers={'Content-Type': 'application/json'})


def load_cases(rel_path):
    """Load a `docs/review-<module>-cases.json` file from the repo root."""
    import os
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    with open(os.path.join(repo_root, rel_path), encoding='utf-8') as fh:
        return json.load(fh)


def run_cases(cases, executors):
    """Run api-channel cases via `executors` (id -> callable -> (ok, detail)).
    ui-channel cases are reported as skipped. Returns the failure count."""
    failures = 0
    api_count = ui_count = 0
    for case in cases:
        cid = case['id']
        if case.get('channel') == 'ui':
            ui_count += 1
            print(f'  - [{cid}] {case["name"]}  (ui: browser suite, skipped)')
            continue
        api_count += 1
        executor = executors.get(cid)
        if executor is None:
            record(cid, False, f'no executor registered for {cid}')
            failures += 1
            continue
        try:
            ok, detail = executor()
        except Exception as exc:                       # infrastructure error
            ok, detail = False, f'{type(exc).__name__}: {exc}'
        record(cid, ok, detail)
        if not ok:
            failures += 1
    print(f'  api={api_count} ui={ui_count}(skipped) failures={failures}', flush=True)
    return failures


def matrix_main(setup_fn, executors_fn, case_file):
    """Common argparse + run flow for the review matrices."""
    ap = argparse.ArgumentParser()
    ap.add_argument('--url', required=True)
    ap.add_argument('--insecure', action='store_true')
    ap.add_argument('--admin', required=True)
    ap.add_argument('--admin-password', required=True)
    args = ap.parse_args()

    if args.insecure:
        allow_insecure()

    ctx = Context(args.url, args.admin, args.admin_password)
    if not wait_ready(ctx.base):
        return 1
    admin_token = get_token(ctx.base, args.admin, args.admin_password)[0]
    if not admin_token:
        print('无法取得管理员 token', file=sys.stderr)
        return 1

    fix = setup_fn(ctx, admin_token)
    doc = load_cases(case_file)
    failures = run_cases(doc['cases'], executors_fn(ctx, fix))
    return 1 if failures else 0
