#!/usr/bin/env python3
"""目录 ACL 六入口验收矩阵。

这是 P1 的验收门禁。单元测试证明求解器算得对，这份脚本证明**算出来的结果真的
被每个入口执行了**——两者不能互相替代：ACL 最容易出的问题不是算错，而是某个
入口压根没走校验。

场景（对齐 docs/acl-semantics.md）：

    库 acl-matrix，owner 建立，共享给 B 且为 rw
    /public       无规则           B 应为 rw
    /restricted   B -> r           B 只读
    /secret       B -> invisible   B 完全不可见

只用标准库，容器与 CI 都不需要额外安装。

    python3 acl_matrix.py --url http://localhost --admin me@example.com \\
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

B_EMAIL = 'acl-matrix-b@example.com'
B_PASSWORD = 'AclMatrix-B-9271'
REPO_NAME = 'acl-matrix'

results = []


def record(entry, case, ok, detail=''):
    results.append((entry, case, ok, detail))
    mark = '✓' if ok else '✗'
    line = f'  {mark} [{entry}] {case}'
    if detail and not ok:
        line += f'\n      {detail}'
    print(line, flush=True)


def request(url, method='GET', token=None, data=None, form=None,
            basic=None, headers=None, raw=False):
    """返回 (status, body)。HTTP 错误不抛异常——本脚本大量断言 403。"""
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
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = resp.read()
            return resp.status, payload if raw else payload.decode(errors='replace')
    except urllib.error.HTTPError as e:
        payload = e.read()
        return e.code, payload if raw else payload.decode(errors='replace')
    except Exception as e:                      # 连接错误等
        return 0, str(e)


def json_body(body):
    try:
        return json.loads(body)
    except Exception:
        return None


class Client:
    def __init__(self, base, token=None):
        self.base = base.rstrip('/')
        self.token = token

    def api(self, path, method='GET', **kw):
        return request(self.base + path, method=method, token=self.token, **kw)


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


def setup(admin, base):
    """建用户、建库、建目录、共享、下 ACL 规则。返回 (repo_id, b_token)。"""
    print('\n准备场景…', flush=True)

    # 用户 B —— 已存在则忽略
    admin.api('/api/v2.1/admin/users/', method='POST',
              form={'email': B_EMAIL, 'password': B_PASSWORD})

    b_token, status, body = get_token(base, B_EMAIL, B_PASSWORD)
    if not b_token:
        sys.exit(f'无法取得用户 B 的 token: {status} {body}')

    # 库
    status, body = admin.api('/api2/repos/', method='POST',
                             form={'name': REPO_NAME})
    repo_id = (json_body(body) or {}).get('repo_id')
    if not repo_id:
        sys.exit(f'建库失败: {status} {body}')
    print(f'  repo_id = {repo_id}', flush=True)

    for folder in ('public', 'restricted', 'secret'):
        admin.api(f'/api2/repos/{repo_id}/dir/?p=/{folder}', method='POST',
                  form={'operation': 'mkdir'})

    # 放一个文件，用于验证读取与打包下载
    admin.api(f'/api2/repos/{repo_id}/dir/?p=/restricted/sub', method='POST',
              form={'operation': 'mkdir'})

    # 共享给 B（rw）——ACL 只能在此基础上收紧
    admin.api(f'/api2/repos/{repo_id}/dir/shared_items/?p=/',
              method='PUT',
              form={'share_type': 'user', 'username': B_EMAIL,
                    'permission': 'rw'})

    # ACL 规则
    for path, perm in (('/restricted', 'r'), ('/secret', 'invisible')):
        status, body = admin.api(
            f'/api/v2.1/cloudfile/repos/{repo_id}/dir-acl/', method='POST',
            form={'path': path, 'subject_type': 'user', 'subject': B_EMAIL,
                  'permission': perm, 'inherit': 'true'})
        if status != 200:
            sys.exit(f'下发 ACL 规则失败 ({path} -> {perm}): {status} {body}')
        print(f'  规则 {path} -> B = {perm}', flush=True)

    return repo_id, b_token


def check_rest(b, repo_id):
    entry = 'REST API'

    status, body = b.api(f'/api2/repos/{repo_id}/dir/?p=/')
    names = [e.get('name') for e in (json_body(body) or [])]
    record(entry, '/secret 不出现在目录列举中', 'secret' not in names,
           f'实际列举: {names}')
    record(entry, '/public 正常可见', 'public' in names, f'实际列举: {names}')

    status, _ = b.api(f'/api2/repos/{repo_id}/dir/?p=/restricted')
    record(entry, '/restricted 可读 (200)', status == 200, f'status={status}')

    status, _ = b.api(f'/api2/repos/{repo_id}/dir/?p=/secret')
    record(entry, '/secret 读取被拒 (403/404)', status in (403, 404),
           f'status={status}')

    status, _ = b.api(f'/api2/repos/{repo_id}/dir/?p=/restricted/new',
                      method='POST', form={'operation': 'mkdir'})
    record(entry, '/restricted 内建目录被拒', status == 403, f'status={status}')

    status, _ = b.api(f'/api2/repos/{repo_id}/dir/?p=/restricted/sub',
                      method='DELETE')
    record(entry, '/restricted 内删除被拒', status == 403, f'status={status}')

    status, _ = b.api(f'/api2/repos/{repo_id}/dir/?p=/public/ok',
                      method='POST', form={'operation': 'mkdir'})
    record(entry, '/public 内建目录允许', status in (200, 201),
           f'status={status}')


def check_upload_link(b, repo_id):
    entry = '上传/下载'

    status, body = b.api(f'/api2/repos/{repo_id}/upload-link/?p=/restricted')
    record(entry, '/restricted 取上传链接被拒', status == 403,
           f'status={status} {body[:80]}')

    status, body = b.api(f'/api2/repos/{repo_id}/upload-link/?p=/public')
    record(entry, '/public 取上传链接允许', status == 200,
           f'status={status} {body[:80]}')

    status, body = b.api(f'/api2/repos/{repo_id}/download-link/?p=/secret')
    record(entry, '/secret 取下载链接被拒', status in (403, 404),
           f'status={status} {body[:80]}')


def check_zip_download(b, repo_id):
    entry = '打包下载'
    status, body = b.api(
        '/api/v2.1/repos/%s/zip-task/?parent_dir=/&dirents=secret' % repo_id)
    record(entry, '含不可读子树的打包下载被拒', status in (403, 404),
           f'status={status} {body[:120]}')

    status, body = b.api(
        '/api/v2.1/repos/%s/zip-task/?parent_dir=/&dirents=public' % repo_id)
    record(entry, '可读目录打包下载允许', status == 200,
           f'status={status} {body[:120]}')


def check_sync(b, repo_id):
    entry = '同步客户端'
    status, body = b.api(f'/api2/repos/{repo_id}/download-info/')
    data = json_body(body) or {}
    # is_repo_syncable 为 false 时 seahub 返回 403
    blocked = status == 403 or data.get('is_syncable') is False
    record(entry, '含不可读内容的库拒绝同步', blocked,
           f'status={status} {body[:160]}')


def check_webdav(base, repo_id):
    entry = 'WebDAV'
    cred = f'{B_EMAIL}:{B_PASSWORD}'
    root = base.rstrip('/') + '/seafdav'

    status, _ = request(f'{root}/{REPO_NAME}/restricted/x.txt', method='PUT',
                        data=b'x', basic=cred)
    record(entry, '/restricted 写入被拒', status in (403, 401),
           f'status={status}')

    status, _ = request(f'{root}/{REPO_NAME}/public/x.txt', method='PUT',
                        data=b'x', basic=cred)
    record(entry, '/public 写入允许', status in (200, 201, 204),
           f'status={status}')

    status, _ = request(f'{root}/{REPO_NAME}/secret/x.txt', method='PUT',
                        data=b'x', basic=cred)
    record(entry, '/secret 写入被拒', status in (403, 401), f'status={status}')


def check_move(b, repo_id):
    entry = '移动/复制/重命名'

    status, body = b.api(
        f'/api/v2.1/repos/{repo_id}/dir/?p=/public/ok', method='POST',
        form={'operation': 'move', 'dst_repo_id': repo_id,
              'dst_parent_dir': '/restricted'})
    record(entry, '移动到 /restricted 被拒', status == 403,
           f'status={status} {body[:120]}')

    status, body = b.api(
        f'/api/v2.1/repos/{repo_id}/dir/?p=/restricted/sub', method='POST',
        form={'operation': 'move', 'dst_repo_id': repo_id,
              'dst_parent_dir': '/public'})
    record(entry, '从 /restricted 移出被拒', status == 403,
           f'status={status} {body[:120]}')


def check_invariant(admin, b, repo_id):
    """扩展只能收紧：CF 结果必须 ⊆ 原生权限。"""
    entry = '安全不变量'
    for path in ('/', '/public', '/restricted', '/secret'):
        status, body = admin.api(
            f'/api/v2.1/cloudfile/repos/{repo_id}/dir-acl/effective/'
            f'?path={urllib.parse.quote(path)}&user={B_EMAIL}')
        data = json_body(body) or {}
        native = data.get('native_permission')
        eff = data.get('effective_permission')
        order = {None: 0, 'invisible': 0, 'none': 0, 'r': 1, 'rw': 2}
        ok = order.get(eff, 99) <= order.get(native, 99)
        record(entry, f'{path}: {native} → {eff} 未放宽', ok,
               f'status={status} {body[:120]}')


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

    token, status, body = get_token(base, args.admin, args.admin_password)
    if not token:
        sys.exit(f'管理员登录失败: {status} {body}')
    admin = Client(base, token)

    repo_id, b_token = setup(admin, base)
    b = Client(base, b_token)

    print('\n验收矩阵…', flush=True)
    check_rest(b, repo_id)
    check_upload_link(b, repo_id)
    check_zip_download(b, repo_id)
    check_sync(b, repo_id)
    check_webdav(base, repo_id)
    check_move(b, repo_id)
    check_invariant(admin, b, repo_id)

    passed = sum(1 for *_, ok, _ in results if ok)
    total = len(results)
    print(f'\n════════ {passed}/{total} 通过 ════════')

    if passed != total:
        print('\n失败项：')
        for entry, case, ok, detail in results:
            if not ok:
                print(f'  [{entry}] {case}\n      {detail}')
        sys.exit(1)


if __name__ == '__main__':
    main()
