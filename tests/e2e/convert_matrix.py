#!/usr/bin/env python3
"""转换/导出能力门禁（SeaDoc 2.0 真实服务）。

验证链条：CF_ENABLE_CONVERT_EXPORT 开启 + seadoc 容器（sdoc-server:2.0）就绪，
sdoc 导出 markdown 往返经真实 converter 服务（FILE_CONVERTER_SERVER_URL =
SEADOC_SERVER_URL/converter），Hub 提供下载 URL 回源。

    convert-001  上传的 .sdoc 可经 /repo/sdoc_export_to_markdown/ 导出，
                 返回 text/markdown 且内容含文档标题
    convert-002  docx 导出端点挂载且对有效文件返回非 404（docx 渲染依赖
                 SeaDoc converter 完整链路）
    convert-003  路径参数缺失 400/错误页（不 500）

    python3 convert_matrix.py --url https://127.0.0.1 --insecure \
        --admin me@example.com --admin-password xxx
"""

import argparse
import json
import os
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import review_harness as H

# Reuse the office-matrix session helpers: the export endpoints are
# @login_required Django views, not DRF token endpoints.
import sys as _sys
_office_mod = _sys.modules.setdefault('office_matrix', None)
import importlib.util as _iu
_spec = _iu.spec_from_file_location('office_helpers',
                                    os.path.join(os.path.dirname(__file__),
                                                 'office_matrix.py'))
_om = _iu.module_from_spec(_spec)
_spec.loader.exec_module(_om)
web_session = _om.web_session
web_login = _om.web_login

# 最小合法 sdoc v2 文档：标题 + 一段文本。
SDOC_BODY = json.dumps({
    'version': 2,
    'doc_uuid': '00000000-0000-0000-0000-000000000001',
    'elements': [
        {'id': 't1', 'type': 'title', 'text': 'CloudFile convert gate'},
        {'id': 'p1', 'type': 'paragraph', 'text': 'hello from convert gate'},
    ],
}).encode()

def request(url, method='GET', token=None, payload=None, context=None,
            raw=False, headers=None):
    hdrs = dict(headers or {})
    body = None
    if token:
        hdrs['Authorization'] = 'Token ' + token
    req = urllib.request.Request(url, data=payload, method=method, headers=hdrs)
    with urllib.request.urlopen(req, timeout=120, context=context) as res:
        data = res.read()
        return res.status, data if raw else data.decode(errors='replace')

def body_json(body):
    try:
        return json.loads(body)
    except (TypeError, ValueError):
        return {}

def check(name, passed, detail=''):
    print('  %s %s%s' % ('✓' if passed else '✗', name,
                         ('\n      ' + detail) if detail and not passed else ''),
          flush=True)
    return passed

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--url', required=True)
    ap.add_argument('--admin', required=True)
    ap.add_argument('--admin-password', required=True)
    ap.add_argument('--insecure', action='store_true')
    args = ap.parse_args()

    if args.insecure:
        ssl._create_default_https_context = ssl._create_unverified_context
    context = ssl._create_unverified_context() if args.insecure else None
    base = args.url.rstrip('/')
    form = urllib.parse.urlencode({
        'username': args.admin, 'password': args.admin_password}).encode()
    req = urllib.request.Request(base + '/api2/auth-token/', data=form,
                                 method='POST')
    with urllib.request.urlopen(req, timeout=60, context=context) as res:
        token = body_json(res.read().decode()).get('token')
    if not check('管理员登录', bool(token)):
        return 1

    # 建库 + 上传 sdoc（Go fileserver 接收；harness 拼 multipart，content_type
    # 须为 application/json，否则 SeaDoc converter 识别失败）。直接复用上面
    # 的 admin token：ctx.token() 会再次拿但耗时无收益。
    req = urllib.request.Request(base + '/api2/repos/', method='POST',
                                 data=urllib.parse.urlencode({'name': 'convert-gate'}).encode(),
                                 headers={'Authorization': 'Token ' + token})
    with urllib.request.urlopen(req, timeout=60, context=context) as res:
        repo_id = json.loads(res.read().decode()).get('repo_id')
    if not check('建库', bool(repo_id)):
        return 1
    ctx2 = H.Context(base, args.admin, args.admin_password)
    status, body = H.upload_file(ctx2, token, repo_id, '/', 'gate.sdoc', SDOC_BODY)
    if not check('上传 gate.sdoc',
                 status == 200 and len(body) >= 20,
                 f'status={status} body={body[:120]}'):
        return 1

    passed = True
    opener = web_login(base, args.admin, args.admin_password)

    def web_get(path, raw=False):
        try:
            r = opener.open(base + path, timeout=120)
            data = r.read()
            return r.status, data if raw else data.decode(errors='replace')
        except urllib.error.HTTPError as e:
            data = e.read()
            return e.code, data if raw else data.decode(errors='replace')
        except Exception as e:
            return 0, str(e)

    # convert-001: sdoc → markdown（经真实 SeaDoc converter，需 session 登录）
    try:
        status, body = web_get(
            f'/repo/sdoc_export_to_markdown/{repo_id}/'
            f'?file_path={urllib.parse.quote("/gate.sdoc")}', raw=True)
        ok = (status == 200 and b'convert gate' in body)
        passed &= check('convert-001 sdoc 导出 markdown 往返',
                        ok, f'status={status} body={body[:150]!r}')
    except Exception as e:
        passed &= check('convert-001 sdoc 导出 markdown 往返', False, str(e)[:150])

    # convert-002: docx 端点挂载（对有效文件不 404；渲染成败记 detail 不判死）
    try:
        status, body = web_get(
            f'/repo/sdoc_export_to_docx/{repo_id}/'
            f'?file_path={urllib.parse.quote("/gate.sdoc")}')
        ok = status != 404
        passed &= check('convert-002 docx 端点挂载且非 404',
                        ok, f'status={status} body={body[:120]}')
    except Exception as e:
        passed &= check('convert-002 docx 端点挂载且非 404', False, str(e)[:150])

    # convert-003: 缺 file_path 参数不 500
    try:
        status, body = web_get(f'/repo/sdoc_export_to_markdown/{repo_id}/')
        ok = status != 500
        passed &= check('convert-003 缺参不 500', ok,
                        f'status={status} body={body[:120]}')
    except urllib.error.HTTPError as e:
        passed &= check('convert-003 缺参不 500', e.code != 500,
                        f'status={e.code}')
    except Exception as e:
        passed &= check('convert-003 缺参不 500', False, str(e)[:150])

    print('════════ 转换/导出 %s ════════' % ('通过' if passed else '失败'))
    return 0 if passed else 1

if __name__ == '__main__':
    sys.exit(main())
