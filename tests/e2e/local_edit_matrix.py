#!/usr/bin/env python3
"""本地应用下载—编辑—写回协议的容器验收矩阵。"""

import argparse
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
results = []


def check(area, case, ok, detail=''):
    results.append((area, case, ok, detail))
    print('  %s [%s] %s' % ('✓' if ok else '✗', area, case), flush=True)
    if detail and not ok:
        print('      ' + detail, flush=True)


def request(url, method='GET', token=None, form=None, payload=None, data=None,
            headers=None, raw=False):
    hdrs = dict(headers or {})
    body = None
    if token:
        hdrs['Authorization'] = 'Token ' + token
    if form is not None:
        body = urllib.parse.urlencode(form).encode()
        hdrs['Content-Type'] = 'application/x-www-form-urlencoded'
    elif payload is not None:
        body = json.dumps(payload).encode()
        hdrs['Content-Type'] = 'application/json'
    elif data is not None:
        body = data if isinstance(data, bytes) else data.encode()
    req = urllib.request.Request(url, data=body, method=method, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=120,
                                    context=_SSL_CONTEXT) as response:
            content = response.read()
            return response.status, content if raw else content.decode(errors='replace')
    except urllib.error.HTTPError as error:
        content = error.read()
        return error.code, content if raw else content.decode(errors='replace')
    except Exception as error:
        return 0, str(error)


def jbody(body):
    try:
        return json.loads(body)
    except Exception:
        return {}


def multipart(fields, filename, content):
    boundary = '----CloudFileLocalEdit' + uuid.uuid4().hex
    chunks = []
    for key, value in fields.items():
        chunks.append('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n'
                      % (boundary, key, value))
    chunks.append('--%s\r\nContent-Disposition: form-data; name="file"; '
                  'filename="%s"\r\nContent-Type: application/octet-stream\r\n\r\n'
                  % (boundary, filename))
    body = ''.join(chunks).encode() + content + ('\r\n--%s--\r\n' % boundary).encode()
    return body, 'multipart/form-data; boundary=' + boundary


def upload(base, token, repo_id, path, content):
    parent = os.path.dirname(path) or '/'
    status, body = request(
        base + '/api2/repos/%s/upload-link/?p=%s' %
        (repo_id, urllib.parse.quote(parent)), token=token)
    link = body.strip('"')
    if status != 200 or not link.startswith('http'):
        return 0, 'upload link: %s %s' % (status, body[:160])
    data, content_type = multipart({'parent_dir': parent, 'replace': '1'},
                                   os.path.basename(path), content)
    return request(link, method='POST', token=token, data=data,
                   headers={'Content-Type': content_type})


def update(base, token, repo_id, path, content):
    status, body = request(base + '/api2/repos/%s/update-link/?p=/' % repo_id,
                           token=token)
    link = body.strip('"')
    if status != 200 or not link.startswith('http'):
        return 0, 'update link: %s %s' % (status, body[:160])
    data, content_type = multipart({'target_file': path},
                                   os.path.basename(path), content)
    return request(link, method='POST', token=token, data=data,
                   headers={'Content-Type': content_type})


def issue(base, token, repo_id, path, mode):
    return request(
        base + '/api/v2.1/cloudfile/repos/%s/local-sessions/' % repo_id,
        method='POST', token=token, payload={'path': path, 'mode': mode})


def claim(base, ticket):
    return request(base + '/api/v2.1/cloudfile/agent-sessions/claim/',
                   method='POST', payload={'ticket': ticket})


def run(base, token):
    status, body = request(base + '/api2/repos/', method='POST', token=token,
                           form={'name': 'local-edit-' + uuid.uuid4().hex[:8]})
    repo_id = jbody(body).get('repo_id')
    if not repo_id:
        sys.exit('建库失败: %s %s' % (status, body))
    path = '/professional.dwg'
    original = b'local-edit version one\n'
    status, body = upload(base, token, repo_id, path, original)
    if status != 200:
        sys.exit('上传失败: %s %s' % (status, body))

    status, body = issue(base, token, repo_id, path, 'local-view')
    descriptor = jbody(body)
    check('描述符', 'v2 查看会话只暴露一次性 ticket',
          status == 201 and descriptor.get('protocol') == 'cloudfile-local/v2'
          and descriptor.get('mode') == 'local-view'
          and descriptor.get('file', {}).get('name') == os.path.basename(path)
          and descriptor.get('ticket') and 'content_url' not in body,
          'status=%s %s' % (status, body[:300]))
    status, body = claim(base, descriptor.get('ticket', ''))
    viewing = jbody(body)
    check('查看', 'Agent 领取后获得短时下载 URL 且无写回权',
          status == 200 and viewing.get('mode') == 'local-view'
          and viewing.get('file', {}).get('content_url')
          and 'writeback' not in viewing,
          'status=%s %s' % (status, body[:300]))
    status, content = request(viewing.get('file', {}).get('content_url', ''), raw=True)
    check('查看', '下载内容一致', status == 200 and content == original,
          'status=%s content=%r' % (status, content[:100] if isinstance(content, bytes) else content))
    status, body = claim(base, descriptor.get('ticket', ''))
    check('一次性', '同一 ticket 不能二次领取', status == 410,
          'status=%s %s' % (status, body[:200]))

    status, body = issue(base, token, repo_id, path, 'local-edit')
    descriptor = jbody(body)
    check('描述符', 'v2 编辑会话包含模式与安全文件名',
          status == 201 and descriptor.get('mode') == 'local-edit'
          and descriptor.get('file', {}).get('name') == os.path.basename(path),
          'status=%s %s' % (status, body[:300]))
    status, body = claim(base, descriptor.get('ticket', ''))
    editing = jbody(body)
    writeback = editing.get('writeback') or {}
    capability = writeback.get('capability', '')
    check('编辑', '领取时才获得下载、心跳和写回权',
          status == 200 and editing.get('mode') == 'local-edit'
          and editing.get('file', {}).get('content_url')
          and writeback.get('content_url') and writeback.get('heartbeat_url')
          and capability,
          'status=%s %s' % (status, body[:400]))
    status, body = request(writeback.get('heartbeat_url', ''), method='PATCH',
                           headers={'Authorization': 'Bearer wrong'})
    check('权限', '错误 capability 不能续租', status == 410,
          'status=%s %s' % (status, body[:200]))
    status, body = request(writeback.get('heartbeat_url', ''), method='PATCH',
                           headers={'Authorization': 'Bearer ' + capability})
    check('心跳', '有效 capability 续租成功', status == 200,
          'status=%s %s' % (status, body[:200]))

    edited = b'local-edit version two\n'
    data, content_type = multipart({}, os.path.basename(path), edited)
    status, body = request(writeback.get('content_url', ''), method='PUT',
                           data=data, headers={
                               'Authorization': 'Bearer ' + capability,
                               'Content-Type': content_type,
                           })
    check('写回', '完整内容按围栏会话写回', status == 204,
          'status=%s %s' % (status, body[:200]))
    status, body = issue(base, token, repo_id, path, 'local-view')
    status, body = claim(base, jbody(body).get('ticket', ''))
    content_url = jbody(body).get('file', {}).get('content_url', '')
    status, content = request(content_url, raw=True)
    check('写回', '重新领取后读到编辑结果', status == 200 and content == edited,
          'status=%s content=%r' % (status, content[:100] if isinstance(content, bytes) else content))
    status, body = request(writeback.get('heartbeat_url', ''), method='PATCH',
                           headers={'Authorization': 'Bearer ' + capability})
    check('会话关闭', '成功写回后 capability 立即失效', status == 410,
          'status=%s %s' % (status, body[:200]))

    # 同一持有者在其他入口改动文件时，锁不会拒绝本人；base_file_id
    # 是防止旧编辑结果覆盖新版本的第二道代际围栏。
    status, body = issue(base, token, repo_id, path, 'local-edit')
    status, body = claim(base, jbody(body).get('ticket', ''))
    stale = jbody(body)
    stale_writeback = stale.get('writeback') or {}
    status, body = update(base, token, repo_id, path, b'concurrent version\n')
    check('并发', '持有者其他入口可提交更新', status == 200,
          'status=%s %s' % (status, body[:200]))
    data, content_type = multipart({}, os.path.basename(path), b'stale editor\n')
    status, body = request(stale_writeback.get('content_url', ''), method='PUT',
                           data=data, headers={
                               'Authorization': 'Bearer ' + stale_writeback.get('capability', ''),
                               'Content-Type': content_type,
                           })
    check('并发', '源文件变化后旧编辑结果被拒绝', status == 409,
          'status=%s %s' % (status, body[:200]))

    lock_url = '/api/v2.1/cloudfile/repos/%s/file-lock/?path=%s' % (
        repo_id, urllib.parse.quote(path))
    status, body = request(base + lock_url, token=token)
    generation = jbody(body).get('generation')
    force = '/api/v2.1/admin/cloudfile/repos/%s/file-lock/force-release/' % repo_id
    status, body = request(base + force, method='POST', token=token,
                           payload={'path': path, 'generation': generation,
                                    'reason': 'local edit conflict recovery'})
    check('恢复', '并发冲突后管理员可按代际恢复', status == 204,
          'status=%s %s' % (status, body[:200]))

    request(base + '/api2/repos/%s/' % repo_id, method='DELETE', token=token)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', required=True)
    parser.add_argument('--admin', required=True)
    parser.add_argument('--admin-password', required=True)
    parser.add_argument('--insecure', action='store_true')
    args = parser.parse_args()
    if args.insecure:
        global _SSL_CONTEXT
        _SSL_CONTEXT = ssl._create_unverified_context()
    base = args.url.rstrip('/')
    deadline = time.time() + 600
    token = None
    status, body = 0, ''
    while time.time() < deadline and not token:
        status, body = request(base + '/api2/auth-token/', method='POST',
                               form={'username': args.admin,
                                     'password': args.admin_password})
        token = jbody(body).get('token')
        if not token:
            time.sleep(5)
    if not token:
        sys.exit('管理员登录失败: %s %s' % (status, body))
    run(base, token)
    passed = sum(1 for _, _, ok, _ in results if ok)
    print('\n════════ %s/%s 通过 ════════' % (passed, len(results)))
    return 0 if passed == len(results) else 1


if __name__ == '__main__':
    sys.exit(main())
