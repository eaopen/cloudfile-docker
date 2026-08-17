#!/usr/bin/env python3
"""文件锁与签入签出生产提供器的容器验收矩阵。

验证同一个 ``cf_lock_lease`` 代际同时约束 Hub、Go fileserver 和 WebDAV，
并覆盖续租、陈旧代际、管理员恢复以及关闭开关后的原生透传。
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
import uuid


_SSL_CONTEXT = None
B_EMAIL = 'lock-matrix-b@example.com'
B_PASSWORD = 'LockMatrix-B-5821'
results = []


def record(area, case, ok, detail=''):
    results.append((area, case, ok, detail))
    mark = '✓' if ok else '✗'
    print(f'  {mark} [{area}] {case}', flush=True)
    if detail and not ok:
        print(f'      {detail}', flush=True)


def request(url, method='GET', token=None, data=None, form=None, basic=None,
            headers=None):
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
        with urllib.request.urlopen(req, timeout=120,
                                    context=_SSL_CONTEXT) as response:
            return response.status, response.read().decode(errors='replace')
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode(errors='replace')
    except Exception as error:
        return 0, str(error)


def jbody(body):
    try:
        return json.loads(body)
    except Exception:
        return {}


class Client:
    def __init__(self, base, token):
        self.base = base.rstrip('/')
        self.token = token

    def api(self, path, method='GET', **kwargs):
        return request(self.base + path, method=method, token=self.token,
                       **kwargs)


def wait_ready(base, timeout):
    deadline = time.time() + timeout
    last = ''
    while time.time() < deadline:
        status, body = request(base + '/api2/ping/')
        if status == 200 and 'pong' in body:
            return True
        last = f'status={status} {body[:120]}'
        time.sleep(5)
    print(f'服务未就绪：{last}', file=sys.stderr)
    return False


def get_token(base, email, password):
    status, body = request(base + '/api2/auth-token/', method='POST',
                           form={'username': email, 'password': password})
    return (jbody(body).get('token'), status, body)


def resolve_identity(admin, email):
    status, body = admin.api('/api/v2.1/admin/users/')
    for user in jbody(body).get('data', []):
        if email in (user.get('email'), user.get('contact_email'),
                     user.get('login_id')):
            return user.get('email')
        if user.get('name') == email.split('@')[0]:
            return user.get('email')
    sys.exit(f'找不到用户 {email}: {status} {body[:200]}')


def multipart(fields, filename, content):
    boundary = '----CloudFileLock' + uuid.uuid4().hex
    parts = []
    for key, value in fields.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; '
            f'name="{key}"\r\n\r\n{value}\r\n')
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
        f'filename="{filename}"\r\nContent-Type: application/octet-stream\r\n\r\n')
    body = ''.join(parts).encode() + content + f'\r\n--{boundary}--\r\n'.encode()
    return body, f'multipart/form-data; boundary={boundary}'


def upload(client, base, repo_id, parent, name, content):
    status, body = client.api(
        f'/api2/repos/{repo_id}/upload-link/?p={urllib.parse.quote(parent)}')
    link = body.strip('"')
    if status != 200 or not link.startswith('http'):
        return 0, f'取上传链接失败: {status} {body[:160]}'
    data, content_type = multipart({'parent_dir': parent, 'replace': '0'},
                                   name, content)
    return request(link, method='POST', token=client.token, data=data,
                   headers={'Content-Type': content_type})


def update(client, repo_id, path, content):
    status, body = client.api(f'/api2/repos/{repo_id}/update-link/?p=/')
    link = body.strip('"')
    if status != 200 or not link.startswith('http'):
        return 0, f'取更新链接失败: {status} {body[:160]}'
    data, content_type = multipart({'target_file': path},
                                   os.path.basename(path), content)
    return request(link, method='POST', token=client.token, data=data,
                   headers={'Content-Type': content_type})


def expect_refused(area, case, status, body, allowed=(403, 409, 423, 502, 520)):
    record(area, case, status in allowed and status != 500,
           f'status={status} {body[:200]}')


def lock_endpoint(repo_id):
    return f'/api/v2.1/cloudfile/repos/{repo_id}/file-lock/'


def release(client, repo_id, path, generation):
    return client.api(lock_endpoint(repo_id), method='DELETE',
                      form={'path': path, 'generation': generation})


def run_matrix(base, admin, admin_email, admin_password):
    status, body = admin.api('/api/v2.1/admin/users/', method='POST',
                             form={'email': B_EMAIL, 'password': B_PASSWORD})
    if status not in (200, 201) and 'exist' not in body.lower():
        sys.exit(f'建用户 B 失败: {status} {body}')
    b_token, status, body = get_token(base, B_EMAIL, B_PASSWORD)
    if not b_token:
        sys.exit(f'用户 B 登录失败: {status} {body}')
    user_b = Client(base, b_token)
    b_id = resolve_identity(admin, B_EMAIL)

    repo_name = 'lock-matrix-' + uuid.uuid4().hex[:8]
    status, body = admin.api('/api2/repos/', method='POST',
                             form={'name': repo_name})
    repo_id = jbody(body).get('repo_id')
    if not repo_id:
        sys.exit(f'建库失败: {status} {body}')
    admin.api(f'/api2/repos/{repo_id}/dir/?p=/docs', method='POST',
              form={'operation': 'mkdir'})
    status, body = upload(admin, base, repo_id, '/docs', 'plan.docx', b'v1\n')
    if status != 200:
        sys.exit(f'上传失败: {status} {body}')
    status, body = admin.api(f'/api2/repos/{repo_id}/dir/shared_items/?p=/',
                             method='PUT',
                             form={'share_type': 'user', 'username': b_id,
                                   'permission': 'rw'})
    if status != 200 or jbody(body).get('failed'):
        sys.exit(f'共享失败: {status} {body}')

    path = '/docs/plan.docx'
    endpoint = lock_endpoint(repo_id)
    status, body = admin.api(endpoint + '?path=' + urllib.parse.quote(path))
    state = jbody(body)
    record('提供器', '无锁时状态可用',
           status == 200 and state.get('ok') is True and not state.get('locked'),
           f'status={status} {body[:200]}')

    status, body = admin.api(endpoint, method='PUT', form={'path': path})
    lease = jbody(body)
    generation = lease.get('generation')
    record('锁定', '持有者获得带 generation 的租约',
           status == 200 and lease.get('ok') is True and bool(generation),
           f'status={status} {body[:200]}')

    status, body = admin.api(endpoint, method='PUT', form={'path': path})
    retry = jbody(body)
    record('锁定', '丢包重试幂等',
           status == 200 and retry.get('generation') == generation,
           f'status={status} {body[:200]}')
    status, body = user_b.api(endpoint, method='PUT', form={'path': path})
    record('锁定', '其他用户不能抢锁', status == 423,
           f'status={status} {body[:200]}')

    status, body = user_b.api(endpoint + '?path=' + urllib.parse.quote(path))
    state = jbody(body)
    record('状态', '其他用户看到同一租约且非本人持有',
           status == 200 and state.get('locked') is True
           and state.get('generation') == generation
           and state.get('locked_by_me') is False,
           f'status={status} {body[:200]}')

    status, body = admin.api(endpoint, method='PATCH',
                             form={'path': path, 'generation': 'stale'})
    record('代际围栏', '陈旧 generation 不能续租', status == 409,
           f'status={status} {body[:200]}')
    status, body = admin.api(endpoint, method='PATCH',
                             form={'path': path, 'generation': generation})
    refreshed = jbody(body)
    record('代际围栏', '当前 generation 可续租',
           status == 200 and refreshed.get('generation') == generation,
           f'status={status} {body[:200]}')

    status, body = update(user_b, repo_id, path, b'b-go\n')
    expect_refused('Go fileserver', '其他用户更新被统一终判拒绝',
                   status, body)
    dav = (f'{base}/seafdav/{urllib.parse.quote(repo_name)}/docs/plan.docx')
    status, body = request(dav, method='PUT', data=b'b-dav\n',
                           basic=f'{B_EMAIL}:{B_PASSWORD}')
    expect_refused('WebDAV', '其他用户 PUT 被统一终判拒绝',
                   status, body)
    status, body = user_b.api(f'/api2/repos/{repo_id}/file/?p={urllib.parse.quote(path)}',
                              method='POST',
                              form={'operation': 'rename', 'newname': 'stolen.docx'})
    expect_refused('REST', '其他用户不能重命名已锁文件', status, body)
    status, body = update(admin, repo_id, path, b'owner\n')
    record('持有者', '持有者写入继续允许', status == 200,
           f'status={status} {body[:200]}')

    status, body = release(user_b, repo_id, path, generation)
    record('代际围栏', '非持有者不能释放', status == 409,
           f'status={status} {body[:200]}')
    status, body = release(admin, repo_id, path, generation)
    record('释放', '持有者按 generation 释放', status == 204,
           f'status={status} {body[:200]}')
    status, body = release(admin, repo_id, path, generation)
    record('代际围栏', '陈旧 generation 不能重复释放', status == 409,
           f'status={status} {body[:200]}')
    status, body = update(user_b, repo_id, path, b'after-release\n')
    record('释放', '释放后其他用户立即可写', status == 200,
           f'status={status} {body[:200]}')

    checkout = f'/api/v2.1/cloudfile/repos/{repo_id}/checkout/'
    status, body = admin.api(checkout, method='POST',
                             form={'path': path, 'source': 'manual'})
    checkout_generation = jbody(body).get('generation')
    record('签出', '手工签出建立权威租约',
           status == 201 and bool(checkout_generation),
           f'status={status} {body[:200]}')
    status, body = update(user_b, repo_id, path, b'while-checkout\n')
    expect_refused('签出', '签出期间其他用户写入被拒绝', status, body)
    status, body = admin.api(checkout, method='DELETE',
                             form={'path': path,
                                   'generation': checkout_generation})
    record('签入', '签入按 generation 关闭租约', status == 204,
           f'status={status} {body[:200]}')

    status, body = admin.api(endpoint, method='PUT', form={'path': path})
    recovery_generation = jbody(body).get('generation')
    force = (f'/api/v2.1/admin/cloudfile/repos/{repo_id}/file-lock/'
             'force-release/')
    status, body = admin.api(force, method='POST',
                             form={'path': path,
                                   'generation': recovery_generation,
                                   'reason': 'lock-matrix recovery'})
    record('管理员恢复', '审核后强制释放当前代际', status == 204,
           f'status={status} {body[:200]}')
    status, body = admin.api(force, method='POST',
                             form={'path': path,
                                   'generation': recovery_generation,
                                   'reason': 'stale retry'})
    record('管理员恢复', '强制释放也拒绝陈旧代际', status == 409,
           f'status={status} {body[:200]}')

    status, body = admin.api(endpoint, method='PUT', form={'path': path})
    descendant_generation = jbody(body).get('generation')
    status, body = user_b.api(f'/api2/repos/{repo_id}/dir/?p=/docs',
                              method='DELETE')
    expect_refused('目录操作', '目录删除不能绕过子文件锁', status, body)
    release(admin, repo_id, path, descendant_generation)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', required=True)
    parser.add_argument('--admin', required=True)
    parser.add_argument('--admin-password', required=True)
    parser.add_argument('--timeout', type=int, default=600)
    parser.add_argument('--insecure', action='store_true')
    args = parser.parse_args()

    if args.insecure:
        global _SSL_CONTEXT
        _SSL_CONTEXT = ssl._create_unverified_context()
    base = args.url.rstrip('/')
    if not wait_ready(base, args.timeout):
        sys.exit(1)
    token, status, body = get_token(base, args.admin, args.admin_password)
    if not token:
        sys.exit(f'管理员登录失败: {status} {body}')
    run_matrix(base, Client(base, token), args.admin, args.admin_password)

    passed = sum(1 for _, _, ok, _ in results if ok)
    total = len(results)
    print(f'\n════════ {passed}/{total} 通过 ════════')
    if passed != total:
        sys.exit(1)


if __name__ == '__main__':
    main()
