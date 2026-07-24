#!/usr/bin/env python3
"""操作日志端到端门禁：文件/目录变更必须可审计、可筛选。

不在 Hub 的 HTTP 入口重复埋点。Server 对每次资料库提交发出 repo-update，
seafevents 将提交差异归一化并持久化为 Activity；本用例从不同对象操作出发，
验证 CloudFile 的管理员查询 API 能列出并筛选这些记录。
"""

import argparse
import json
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid


def request(url, method='GET', token=None, form=None, data=None, headers=None,
            context=None):
    request_headers = dict(headers or {})
    body = None
    if token:
        request_headers['Authorization'] = 'Token ' + token
    if form is not None:
        body = urllib.parse.urlencode(form).encode()
        request_headers['Content-Type'] = 'application/x-www-form-urlencoded'
    elif data is not None:
        body = data if isinstance(data, bytes) else data.encode()
    req = urllib.request.Request(url, data=body, method=method,
                                 headers=request_headers)
    try:
        with urllib.request.urlopen(req, timeout=60, context=context) as response:
            return response.status, response.read().decode(errors='replace')
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode(errors='replace')
    except Exception as error:
        return 0, str(error)


def json_body(body):
    try:
        return json.loads(body)
    except ValueError:
        return {}


def multipart(fields, filename, content):
    boundary = '----CloudFileAudit' + uuid.uuid4().hex
    chunks = []
    for key, value in fields.items():
        chunks.append('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n'
                      % (boundary, key, value))
    chunks.append('--%s\r\nContent-Disposition: form-data; name="file"; '
                  'filename="%s"\r\nContent-Type: application/octet-stream\r\n\r\n'
                  % (boundary, filename))
    body = ''.join(chunks).encode() + content + ('\r\n--%s--\r\n' % boundary).encode()
    return body, 'multipart/form-data; boundary=' + boundary


def check(name, passed, detail=''):
    print('  %s %s%s' % ('✓' if passed else '✗', name,
                         ('\n      ' + detail) if detail and not passed else ''),
          flush=True)
    return passed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', required=True)
    parser.add_argument('--admin', required=True)
    parser.add_argument('--admin-password', required=True)
    parser.add_argument('--insecure', action='store_true')
    args = parser.parse_args()

    context = ssl._create_unverified_context() if args.insecure else None
    base = args.url.rstrip('/')
    status, body = request(base + '/api2/auth-token/', method='POST',
                           form={'username': args.admin,
                                 'password': args.admin_password}, context=context)
    token = json_body(body).get('token')
    if not check('管理员登录', bool(token), 'status=%s %s' % (status, body[:200])):
        return 1

    status, body = request(base + '/api2/repos/', method='POST', token=token,
                           form={'name': 'audit-' + uuid.uuid4().hex[:8]},
                           context=context)
    repo_id = json_body(body).get('repo_id')
    if not check('创建资料库', bool(repo_id), 'status=%s %s' % (status, body[:200])):
        return 1

    passed = True
    status, body = request(base + '/api2/repos/%s/dir/?p=/audit-dir' % repo_id,
                           method='POST', token=token, form={'operation': 'mkdir'},
                           context=context)
    passed &= check('创建目录', status in (200, 201), 'status=%s %s' % (status, body[:200]))

    status, body = request(base + '/api2/repos/%s/upload-link/?p=/audit-dir' % repo_id,
                           token=token, context=context)
    upload_url = body.strip('"')
    if status == 200 and upload_url.startswith('http'):
        content, content_type = multipart({'parent_dir': '/audit-dir', 'replace': '1'},
                                           'audit.txt', b'CloudFile audit matrix\n')
        status, body = request(upload_url, method='POST', token=token, data=content,
                               headers={'Content-Type': content_type}, context=context)
    passed &= check('上传文件', status == 200, 'status=%s %s' % (status, body[:200]))

    move_payload = json.dumps({
        'src_repo_id': repo_id, 'dst_repo_id': repo_id,
        'paths': [{'src_path': '/audit-dir/audit.txt', 'dst_path': '/audit-dir/audited.txt'}],
    })
    status, body = request(base + '/api/v2.1/repos/batch-move-item/', method='POST',
                           token=token, data=move_payload,
                           headers={'Content-Type': 'application/json'}, context=context)
    move_result = json_body(body)
    passed &= check('重命名文件', status == 200 and len(move_result.get('success') or []) == 1,
                    'status=%s %s' % (status, body[:300]))

    events = []
    deadline = time.time() + 75
    while time.time() < deadline:
        query = urllib.parse.urlencode({'repo_id': repo_id, 'per_page': 200})
        status, body = request(base + '/api/v2.1/cloudfile/audit/?' + query,
                               token=token, context=context)
        events = json_body(body).get('events') or []
        has_file = any(event.get('object_type') == 'file' and
                       event.get('path') == '/audit-dir/audited.txt' for event in events)
        has_dir = any(event.get('object_type') == 'dir' and
                      event.get('path') == '/audit-dir' for event in events)
        if status == 200 and has_file and has_dir:
            break
        time.sleep(3)
    passed &= check('API 列出文件与目录操作', status == 200 and has_file and has_dir,
                    'status=%s events=%s %s' % (status, len(events), body[:500]))

    status, body = request(base + '/api/v2.1/cloudfile/audit/?' +
                           urllib.parse.urlencode({'repo_id': repo_id, 'obj_type': 'file'}),
                           token=token, context=context)
    file_events = json_body(body).get('events') or []
    passed &= check('按文件类型筛选', status == 200 and file_events and
                    all(event.get('object_type') == 'file' for event in file_events),
                    'status=%s %s' % (status, body[:500]))

    status, body = request(base + '/api/v2.1/cloudfile/audit/?' +
                           urllib.parse.urlencode({'repo_id': repo_id, 'op_type': 'rename'}),
                           token=token, context=context)
    rename_events = json_body(body).get('events') or []
    passed &= check('按操作筛选且保留旧路径', status == 200 and
                    any(event.get('old_path') == '/audit-dir/audit.txt' and
                        event.get('path') == '/audit-dir/audited.txt'
                        for event in rename_events),
                    'status=%s %s' % (status, body[:500]))

    request(base + '/api2/repos/%s/' % repo_id, method='DELETE', token=token,
            context=context)
    print('\n════════ %s ════════' % ('通过' if passed else '失败'))
    return 0 if passed else 1


if __name__ == '__main__':
    sys.exit(main())
