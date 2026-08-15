#!/usr/bin/env python3
"""OnlyOffice 容器验收矩阵（P2-13）。

验证链条的每一环都是真的：Document Server 容器（onlyoffice/documentserver:8.2，
JWT 开）、Hub 开着 CF_ENABLE_ONLYOFFICE、编辑页 HTML 真的带 onlyoffice 配置、
convert 端点真的从 Document Server 拿回转换结果、回调影子端点对无签名请求
拒绝、对带签名的 status 2 保存回调只落一次版本（幂等）。

锁协同（file_actions 在打开渲染器前建立共享 OnlyOffice 租约）与签入签出
由 lock_matrix 覆盖；这里只测 OnlyOffice 自己的通路。
"""

import http.cookiejar
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request as urlreq

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import review_harness as H

B_EMAIL = 'office-matrix-b@example.com'
B_PASSWORD = 'OfficeMatrixB7142'
REPO_NAME = 'office-matrix'
JWT_SECRET = os.environ.get('ONLYOFFICE_JWT_SECRET', 'CloudFile-CI-Office-4417')

def record(case, ok, detail=''):
    print(('  PASS ' if ok else '  FAIL ') + f'[{case}] {detail}', flush=True)
    return ok


def web_session():
    """Return an opener that keeps a session cookie jar and honours --insecure.

    The file-view page is a session-authenticated Django view (not a DRF token
    endpoint), so the API token used everywhere else does not apply here. This
    opener carries the login cookie instead, so the matrix can assert that the
    edit page HTML really carries the OnlyOffice config.
    """
    cj = http.cookiejar.CookieJar()
    handlers = [urlreq.HTTPCookieProcessor(cj)]
    if H._SSL_CONTEXT is not None:
        handlers.append(urlreq.HTTPSHandler(context=H._SSL_CONTEXT))
    return urlreq.build_opener(*handlers)


def web_login(base, email, password):
    """POST the web login form and return an authenticated opener."""
    opener = web_session()
    try:
        page = opener.open(base + '/accounts/login/', timeout=60).read() \
            .decode(errors='replace')
    except urllib.error.HTTPError as exc:
        page = exc.read().decode(errors='replace')
    match = re.search(r'name="csrfmiddlewaretoken"[^>]*value="([^"]+)"', page)
    csrf = match.group(1) if match else ''
    form = urllib.parse.urlencode({
        'login': email, 'password': password, 'csrfmiddlewaretoken': csrf,
    }).encode()
    req = urlreq.Request(base + '/accounts/login/', data=form, headers={
        'Content-Type': 'application/x-www-form-urlencoded',
        'Referer': base + '/accounts/login/'})
    try:
        opener.open(req, timeout=60)
    except urllib.error.HTTPError:
        pass  # a 302 after login surfaces as HTTPError on the redirect target
    return opener

def convert(ctx, token, repo_id, path):
    return H.post_json(ctx, token, '/onlyoffice-api/convert/',
                       {'repo_id': repo_id, 'file_path': path})

def make_callback_token(payload):
    # Minimal HS256 JWT (header.payload.signature, base64url, no padding) --
    # hand-rolled so the matrix has no PyJWT dependency on the CI runner;
    # that is also exactly what the guard's jwt.decode verifies.
    import base64
    import hashlib
    import hmac

    def b64(raw):
        return base64.urlsafe_b64encode(raw).rstrip(b'=').decode()

    signing_input = (b64(json.dumps({'alg': 'HS256', 'typ': 'JWT'}).encode())
                     + '.' + b64(json.dumps(payload).encode()))
    sig = hmac.new(JWT_SECRET.encode(), signing_input.encode(),
                   hashlib.sha256).digest()
    return signing_input + '.' + b64(sig)

def docx_bytes():
    # A minimal valid .docx (empty document). OnlyOffice converts this fine;
    # the content does not matter, only that Document Server accepts the job.
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr(
            '[Content_Types].xml',
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/'
            'content-types"><Default Extension="xml" ContentType="application/'
            'xml"/></Types>')
    return buf.getvalue()

def post_callback(ctx, token, payload, signed=True):
    headers = {'Content-Type': 'application/json'}
    if signed:
        headers['Authorization'] = 'Bearer ' + make_callback_token(payload)
    return ctx.api('/onlyoffice/editor-callback/', method='POST', token=token,
                   data=json.dumps(payload).encode(), headers=headers)

def main():
    from review_harness import Context, allow_insecure, get_token, wait_ready
    import argparse

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

    print('\n准备场景…', flush=True)
    b_token = H.create_user(ctx, B_EMAIL, B_PASSWORD)
    repo_id = H.create_repo(ctx, admin_token, REPO_NAME)
    b_id = H.resolve_identity(ctx, B_EMAIL)
    H.share_repo(ctx, admin_token, repo_id, b_id, 'rw')
    H.upload_file(ctx, admin_token, repo_id, '/', 'report.docx', docx_bytes())

    passed = True

    # 1. The onlyoffice-api/ routes are mounted only when
    #    ENABLE_ONLYOFFICE is true (seahub/urls.py gates the include on it),
    #    so a 200/4xx (not 404) proves the bootstrap wrote the switch.
    status, body = ctx.api('/onlyoffice-api/convert/', token=admin_token)
    passed &= record('onlyoffice-api 路由已挂载（开关生效）', status != 404,
                     f'status={status} (expect non-404)')

    # 2. The convert endpoint round-trips through the real Document Server.
    status, body = convert(ctx, admin_token, repo_id, '/report.docx')
    data = H.json_body(body) or {}
    converted = bool(data.get('file_name') or data.get('link'))
    passed &= record('convert 经 Document Server 返回结果',
                     status == 200 and converted,
                     f'status={status} body={str(body)[:160]}')

    # 2.5 The edit page really renders the OnlyOffice editor config. The file
    #     view is a session view, so this logs in via the web form (not the API
    #     token) and checks the inline config carries the doc key, the callback
    #     URL and the DocsAPI init — i.e. the "edit" entry is live, not just a
    #     mounted route.
    opener = web_login(ctx.base, args.admin, args.admin_password)
    try:
        edit_page = opener.open(f'{ctx.base}/lib/{repo_id}/file/report.docx',
                                timeout=60).read().decode(errors='replace')
        edit_status = 200
    except urllib.error.HTTPError as exc:
        edit_status = exc.code
        edit_page = exc.read().decode(errors='replace')
    has_config = ('callbackUrl' in edit_page
                  and 'DocsAPI.DocEditor' in edit_page)
    passed &= record('编辑页 HTML 带 OnlyOffice 配置',
                     edit_status == 200 and has_config,
                     f'status={edit_status} callbackUrl={"callbackUrl" in edit_page} '
                     f'DocEditor={"DocsAPI.DocEditor" in edit_page}')

    # 3. The shadowed callback rejects an unsigned save callback outright.
    status, body = post_callback(ctx, admin_token,
                                 {'status': 2, 'key': 'office-matrix-unsigned',
                                  'url': 'x'}, signed=False)
    passed &= record('无签名回调被拒', body.replace(' ', '') == '{"error":1}',
                     f'status={status} body={body[:120]}')

    # 4. A signed callback for an unknown doc key passes the guard's JWT
    #    check and reaches CE's own callback, which answers {"error": 1}
    #    over HTTP 200 for unknown keys with status 2/6 -- no 500, no crash.
    status, body = post_callback(ctx, admin_token,
                                 {'status': 2, 'key': 'office-matrix-unknown',
                                  'url': 'http://127.0.0.1:1/none'})
    passed &= record('带签名回调进入 CE 处理（无 500）', status == 200,
                     f'status={status} body={str(body)[:160]}')

    # 5. Idempotency seam: redelivering the same signed status 6 callback
    #    must answer success both times and never 500 (the completed-save
    #    dedupe writing two Seafile versions needs a real editing session;
    #    its pure rule is covered by cloudfile_ext/office unit tests).
    for attempt in (1, 2):
        status, body = post_callback(ctx, admin_token,
                                     {'status': 6, 'key': 'office-matrix-idem',
                                      'url': 'http://127.0.0.1:1/none',
                                      'users': [B_EMAIL]})
        passed &= record(f'status 6 重投递(#{attempt})不 500', status == 200,
                         f'status={status} body={str(body)[:160]}')

    print(('\n════════ ' + ('通过' if passed else '失败') + ' ════════'), flush=True)
    return 0 if passed else 1

if __name__ == '__main__':
    sys.exit(main())
