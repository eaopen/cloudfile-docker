#!/usr/bin/env python3
"""操作日志端到端门禁：文件/目录变更必须可审计、可筛选。

不在 Hub 的 HTTP 入口重复埋点。Server 对每次资料库提交发出 repo-update，
seafevents 将提交差异归一化并持久化为 Activity；本用例从不同对象操作出发，
验证 CloudFile 的管理员查询 API 能列出并筛选这些记录。
"""

import argparse
import http.cookiejar
import json
import re
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


def load_audit_page(base, email, password, context):
    """Log in through the browser flow and return the rendered audit page."""
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(jar),
        urllib.request.HTTPSHandler(context=context))
    login_url = base + '/accounts/login/?next=/cloudfile/audit/'
    try:
        with opener.open(login_url, timeout=60) as response:
            login = response.read().decode(errors='replace')
        token = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', login)
        if not token:
            return 0, 'login CSRF token missing'
        form = urllib.parse.urlencode({
            'csrfmiddlewaretoken': token.group(1), 'login': email,
            'password': password, 'next': '/cloudfile/audit/',
        }).encode()
        req = urllib.request.Request(login_url, data=form, method='POST', headers={
            'Content-Type': 'application/x-www-form-urlencoded', 'Referer': login_url,
        })
        with opener.open(req, timeout=60) as response:
            return response.status, response.read().decode(errors='replace')
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode(errors='replace')
    except Exception as error:
        return 0, str(error)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', required=True)
    parser.add_argument('--admin', required=True)
    parser.add_argument('--admin-password', required=True)
    parser.add_argument('--insecure', action='store_true')
    args = parser.parse_args()

    context = ssl._create_unverified_context() if args.insecure else None
    base = args.url.rstrip('/')

    # The stack can answer /api2/ping/ before seahub finishes initializing;
    # auth-token would then 502. Block on readiness first (review audit gate).
    import time as _time
    deadline = _time.time() + 600
    ready = False
    while _time.time() < deadline:
        s, b = request(base + '/api2/ping/', context=context)
        if s == 200 and 'pong' in b:
            ready = True
            break
        _time.sleep(5)
    if not check('服务就绪', ready):
        return 1

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

    # 目录重命名走资料库目录端点；batch-move-item 的 dst_path 是目标目录而非
    # 新名称，传完整路径会得到一条看似正常的 200 failed 响应。
    status, body = request(base + '/api2/repos/%s/dir/?p=/audit-dir' % repo_id,
                           method='POST', token=token,
                           form={'operation': 'rename', 'newname': 'audited-dir'},
                           context=context)
    passed &= check('重命名目录', status == 200,
                    'status=%s %s' % (status, body[:300]))

    status, body = request(base + '/api2/repos/%s/dir/?p=/destination' % repo_id,
                           method='POST', token=token, form={'operation': 'mkdir'},
                           context=context)
    passed &= check('创建移动目标目录', status in (200, 201),
                    'status=%s %s' % (status, body[:200]))

    move_payload = json.dumps({
        'src_repo_id': repo_id, 'dst_repo_id': repo_id,
        'paths': [{'src_path': '/audited-dir/audit.txt',
                   'dst_path': '/destination'}],
    })
    status, body = request(base + '/api/v2.1/repos/batch-move-item/',
                           method='POST', token=token, data=move_payload,
                           headers={'Content-Type': 'application/json'},
                           context=context)
    move_result = json_body(body)
    passed &= check('移动文件', status == 200 and
                    bool(move_result.get('success')) and
                    not move_result.get('failed'),
                    'status=%s %s' % (status, body[:300]))

    moved_path = '/destination/audit.txt'
    status, body = request(base + '/api2/repos/%s/file/?p=%s' % (
        repo_id, urllib.parse.quote(moved_path)), method='DELETE', token=token,
        context=context)
    passed &= check('删除文件', status == 200,
                    'status=%s %s' % (status, body[:300]))

    trash_item = None
    deadline = time.time() + 75
    while time.time() < deadline:
        status, body = request(
            base + '/api/v2.1/repos/%s/trash2/?per_page=100' % repo_id,
            token=token, context=context)
        for item in json_body(body).get('items') or []:
            full_path = (item.get('parent_dir') or '/').rstrip('/') + '/' + \
                        (item.get('obj_name') or '')
            if full_path == moved_path:
                trash_item = item
                break
        if trash_item:
            break
        time.sleep(3)
    passed &= check('回收站可找到删除项', bool(trash_item),
                    'status=%s %s' % (status, body[:500]))

    if trash_item:
        recover_payload = json.dumps({trash_item['commit_id']: [moved_path]})
        status, body = request(
            base + '/api/v2.1/repos/%s/trash2/revert/' % repo_id,
            method='POST', token=token, data=recover_payload,
            headers={'Content-Type': 'application/json'}, context=context)
        recover_result = json_body(body)
        passed &= check('从回收站恢复文件', status == 200 and
                        bool(recover_result.get('success')) and
                        not recover_result.get('failed'),
                        'status=%s %s' % (status, body[:300]))

    events = []
    deadline = time.time() + 75
    while time.time() < deadline:
        query = urllib.parse.urlencode({'repo_id': repo_id, 'per_page': 200})
        status, body = request(base + '/api/v2.1/cloudfile/audit/?' + query,
                               token=token, context=context)
        events = json_body(body).get('events') or []
        has_file = any(event.get('object_type') == 'file' and
                       event.get('path') in ('/audit-dir/audit.txt', moved_path)
                       for event in events)
        has_dir = any(event.get('object_type') == 'dir' and
                      event.get('path') == '/audited-dir' for event in events)
        operations = {event.get('operation') for event in events}
        if status == 200 and has_file and has_dir and \
                {'move', 'delete', 'recover'} <= operations:
            break
        time.sleep(3)
    passed &= check('API 列出创建、重命名、移动、删除与恢复',
                    status == 200 and has_file and has_dir and
                    {'move', 'delete', 'recover'} <= operations,
                    'status=%s operations=%s events=%s %s' %
                    (status, sorted(operations), len(events), body[:500]))

    # 目录/文件级视图：Seafile 原生日志只有库级列表，这里的 path 筛选就是
    # 「这一个目录/文件发生过什么」的入口——子串匹配，子目录事件一并命中。
    status, body = request(base + '/api/v2.1/cloudfile/audit/?' +
                           urllib.parse.urlencode({'repo_id': repo_id,
                                                   'path': 'audit-dir'}),
                           token=token, context=context)
    path_events = json_body(body).get('events') or []
    path_ok = (status == 200 and path_events and
               all('audit-dir' in (event.get('path') or '') or
                   'audit-dir' in (event.get('old_path') or '')
                   for event in path_events))
    passed &= check('按目录路径筛选（目录级操作日志）', path_ok,
                    'status=%s events=%s %s' %
                    (status, len(path_events), body[:500]))

    status, body = request(base + '/api/v2.1/cloudfile/audit/?' +
                           urllib.parse.urlencode({'repo_id': repo_id,
                                                   'path': moved_path}),
                           token=token, context=context)
    file_events = json_body(body).get('events') or []
    file_ok = (status == 200 and file_events and
               any(event.get('operation') == 'move' for event in file_events))
    passed &= check('按文件路径筛选（文件级操作日志，含移动后路径）', file_ok,
                    'status=%s events=%s %s' %
                    (status, len(file_events), body[:500]))

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
                    any(event.get('old_path') == '/audit-dir' and
                        event.get('path') == '/audited-dir'
                        for event in rename_events),
                    'status=%s %s' % (status, body[:500]))

    for operation in ('move', 'delete', 'recover'):
        status, body = request(base + '/api/v2.1/cloudfile/audit/?' +
                               urllib.parse.urlencode({
                                   'repo_id': repo_id, 'op_type': operation}),
                               token=token, context=context)
        selected = json_body(body).get('events') or []
        passed &= check('按 %s 操作筛选' % operation,
                        status == 200 and selected and
                        all(event.get('operation') == operation
                            for event in selected),
                        'status=%s %s' % (status, body[:500]))

    # P2-08: tag add/rename/delete must surface as audit events carrying the
    # before/after values of each change.
    tag_name = 'audit-tag-' + uuid.uuid4().hex[:6]
    status, body = request(base + '/api/v2.1/repos/%s/repo-tags/' % repo_id,
                           method='POST', token=token,
                           data=json.dumps({'name': tag_name, 'color': '#ff0000'}),
                           headers={'Content-Type': 'application/json'},
                           context=context)
    tag_id = (json_body(body).get('repo_tag') or {}).get('repo_tag_id')
    passed &= check('创建标签', status in (200, 201) and bool(tag_id),
                    'status=%s %s' % (status, body[:300]))

    renamed = tag_name + '-renamed'
    status, body = request(
        base + '/api/v2.1/repos/%s/repo-tags/%s/' % (repo_id, tag_id),
        method='PUT', token=token,
        data=json.dumps({'name': renamed, 'color': '#00ff00'}),
        headers={'Content-Type': 'application/json'}, context=context)
    passed &= check('重命名标签', status == 200,
                    'status=%s %s' % (status, body[:300]))

    status, body = request(
        base + '/api/v2.1/repos/%s/repo-tags/%s/' % (repo_id, tag_id),
        method='DELETE', token=token, context=context)
    passed &= check('删除标签', status == 200,
                    'status=%s %s' % (status, body[:300]))

    tag_events = []
    deadline = time.time() + 60
    while time.time() < deadline:
        status, body = request(base + '/api/v2.1/cloudfile/audit/?' +
                               urllib.parse.urlencode({
                                   'repo_id': repo_id, 'obj_type': 'tag',
                                   'per_page': 200}),
                               token=token, context=context)
        tag_events = json_body(body).get('events') or []
        has_create = any(e.get('operation') == 'create' and
                         (e.get('after') or {}).get('tag_name') == tag_name
                         for e in tag_events)
        has_update = any(e.get('operation') == 'update' and
                         (e.get('before') or {}).get('tag_name') == tag_name and
                         (e.get('after') or {}).get('tag_name') == renamed
                         for e in tag_events)
        has_delete = any(e.get('operation') == 'delete' and
                         (e.get('before') or {}).get('tag_name') == renamed and
                         e.get('after') is None
                         for e in tag_events)
        if status == 200 and has_create and has_update and has_delete:
            break
        time.sleep(3)
    passed &= check('标签增删与系统标签变化记录 before/after',
                    status == 200 and has_create and has_update and has_delete,
                    'status=%s events=%s %s' %
                    (status, len(tag_events), body[:600]))

    status, body = request(base + '/api/v2.1/cloudfile/audit/?' +
                           urllib.parse.urlencode({
                               'repo_id': repo_id, 'source': 'api'}),
                           token=token, context=context)
    src_events = json_body(body).get('events') or []
    passed &= check('按来源筛选（api → 标签事件）', status == 200 and src_events and
                    all(e.get('source') == 'api' for e in src_events),
                    'status=%s %s' % (status, body[:400]))

    status, body = request(base + '/api/v2.1/cloudfile/audit/?' +
                           urllib.parse.urlencode({
                               'repo_id': repo_id, 'source': 'commit'}),
                           token=token, context=context)
    commit_events = json_body(body).get('events') or []
    passed &= check('按来源筛选（commit → 提交事件）', status == 200 and commit_events and
                    all(e.get('source') == 'commit' for e in commit_events),
                    'status=%s %s' % (status, body[:400]))

    status, body = request(base + '/api/v2.1/cloudfile/audit/export/?' +
                           urllib.parse.urlencode({'repo_id': repo_id}),
                           token=token, context=context)
    passed &= check('导出 CSV', status == 200 and
                    body.lstrip('\ufeff').startswith('event_id,time,user'),
                    'status=%s %s' % (status, body[:200]))

    status, page = load_audit_page(base, args.admin, args.admin_password, context)
    passed &= check('管理员可打开操作日志清单 UI', status == 200 and
                    'audit-filters' in page and 'audit-events' in page,
                    'status=%s %s' % (status, page[:300]))

    request(base + '/api2/repos/%s/' % repo_id, method='DELETE', token=token,
            context=context)
    print('\n════════ %s ════════' % ('通过' if passed else '失败'))
    return 0 if passed else 1


if __name__ == '__main__':
    sys.exit(main())
