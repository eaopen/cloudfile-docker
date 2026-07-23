#!/usr/bin/env python3
"""原生 CE 冒烟测试。

P0 的核心验收项：**所有 CF_ENABLE_* 关闭时，行为必须与原生 Seafile CE 一致**。
这是升级成本可控的前提——一旦扩展在关闭状态下仍然改变了行为，跟随上游就会
变成无休止的回归排查。

覆盖最基本的一条链路：登录 → 建库 → 上传 → 列举 → 下载 → 分享链接 →
WebDAV → 删除。不追求全面，只要求这些在开关全关时和原生 CE 没有差别。

只用标准库。

    python3 smoke.py --url http://localhost --admin me@example.com \\
        --admin-password xxx
"""

import argparse
import base64
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

results = []


def record(case, ok, detail=''):
    results.append((case, ok, detail))
    print(f'  {"✓" if ok else "✗"} {case}' + (f'\n      {detail}' if detail and not ok else ''),
          flush=True)


def request(url, method='GET', token=None, data=None, form=None, basic=None,
            headers=None, raw=False):
    hdrs = dict(headers or {})
    body = None
    if token:
        hdrs['Authorization'] = f'Token {token}'
    if basic:
        hdrs['Authorization'] = 'Basic ' + base64.b64encode(basic.encode()).decode()
    if form is not None:
        body = urllib.parse.urlencode(form).encode()
        hdrs['Content-Type'] = 'application/x-www-form-urlencoded'
    elif data is not None:
        body = data if isinstance(data, bytes) else data.encode()

    req = urllib.request.Request(url, data=body, method=method, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = resp.read()
            return resp.status, payload if raw else payload.decode(errors='replace')
    except urllib.error.HTTPError as e:
        payload = e.read()
        return e.code, payload if raw else payload.decode(errors='replace')
    except Exception as e:
        return 0, str(e)


def jbody(body):
    try:
        return json.loads(body)
    except Exception:
        return None


def multipart(fields, filename, content):
    """手工拼 multipart，避免为一个上传引入 requests 依赖。"""
    boundary = '----CloudFileSmoke' + uuid.uuid4().hex
    out = []
    for k, v in fields.items():
        out.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n')
    out.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
        f'filename="{filename}"\r\nContent-Type: application/octet-stream\r\n\r\n')
    body = ''.join(out).encode() + content + f'\r\n--{boundary}--\r\n'.encode()
    return body, f'multipart/form-data; boundary={boundary}'


def wait_ready(base, timeout):
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--url', default='http://localhost')
    ap.add_argument('--admin', required=True)
    ap.add_argument('--admin-password', required=True)
    ap.add_argument('--timeout', type=int, default=600)
    args = ap.parse_args()

    base = args.url.rstrip('/')
    if not wait_ready(base, args.timeout):
        sys.exit('服务未就绪')

    print('\n原生 CE 冒烟…', flush=True)

    status, body = request(base + '/api2/auth-token/', method='POST',
                           form={'username': args.admin,
                                 'password': args.admin_password})
    token = (jbody(body) or {}).get('token')
    record('登录取得 token', bool(token), f'status={status} {body[:160]}')
    if not token:
        sys.exit(1)

    def api(path, **kw):
        return request(base + path, token=token, **kw)

    status, body = api('/api2/account/info/')
    record('读取账号信息', status == 200, f'status={status} {body[:120]}')

    repo_name = 'smoke-' + uuid.uuid4().hex[:8]
    status, body = api('/api2/repos/', method='POST', form={'name': repo_name})
    repo_id = (jbody(body) or {}).get('repo_id')
    record('建库', bool(repo_id), f'status={status} {body[:160]}')
    if not repo_id:
        sys.exit(1)

    status, body = api(f'/api2/repos/{repo_id}/dir/?p=/folder', method='POST',
                       form={'operation': 'mkdir'})
    record('建目录', status in (200, 201), f'status={status} {body[:120]}')

    # 上传
    status, body = api(f'/api2/repos/{repo_id}/upload-link/?p=/')
    upload_url = (body or '').strip('"')
    record('取上传链接', status == 200 and upload_url.startswith('http'),
           f'status={status} {body[:160]}')

    content = b'cloudfile smoke test payload\n'
    if upload_url.startswith('http'):
        data, ctype = multipart(
            {'parent_dir': '/', 'replace': '1'}, 'smoke.txt', content)
        status, body = request(upload_url, method='POST', data=data,
                               token=token, headers={'Content-Type': ctype})
        record('上传文件', status == 200, f'status={status} {body[:160]}')

    status, body = api(f'/api2/repos/{repo_id}/dir/?p=/')
    names = [e.get('name') for e in (jbody(body) or [])]
    record('列举目录包含上传的文件', 'smoke.txt' in names, f'实际: {names}')

    # 下载
    status, body = api(f'/api2/repos/{repo_id}/file/?p=/smoke.txt')
    dl = (body or '').strip('"')
    ok = status == 200 and dl.startswith('http')
    if ok:
        status, payload = request(dl, raw=True)
        ok = status == 200 and payload == content
        record('下载文件内容一致', ok, f'status={status} len={len(payload)}')
    else:
        record('下载文件内容一致', False, f'取下载链接失败 status={status} {body[:120]}')

    # 分享链接
    status, body = api('/api/v2.1/share-links/', method='POST',
                       form={'repo_id': repo_id, 'path': '/smoke.txt'})
    link = (jbody(body) or {}).get('link')
    record('创建分享链接', bool(link), f'status={status} {body[:160]}')

    # WebDAV
    cred = f'{args.admin}:{args.admin_password}'
    status, body = request(f'{base}/seafdav/', method='PROPFIND', basic=cred,
                           headers={'Depth': '1'})
    record('WebDAV 可列举', status in (207, 200), f'status={status} {body[:120]}')

    # 同步入口（开关全关时必须可同步）
    status, body = api(f'/api2/repos/{repo_id}/download-info/')
    record('库可同步（开关全关）', status == 200, f'status={status} {body[:160]}')

    # 清理
    status, _ = api(f'/api2/repos/{repo_id}/', method='DELETE')
    record('删库', status == 200, f'status={status}')

    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print(f'\n════════ {passed}/{total} 通过 ════════')
    if passed != total:
        print('\n失败项：')
        for case, ok, detail in results:
            if not ok:
                print(f'  {case}\n      {detail}')
        sys.exit(1)


if __name__ == '__main__':
    main()
