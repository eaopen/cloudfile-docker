#!/usr/bin/env python3
"""元数据服务端到端门禁：启用属性、标签表与标签写读。

这验证的是 CloudFile 的部署接线，而不是重写上游功能：CE 自带 Hub REST API
和前端，官方 metadata-server 处理存储。若 JWT、共享卷、Redis/MySQL、服务 URL
或上游 API 版本有任一处不兼容，PUT metadata 或标签读写都会直接失败。
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


def request(url, method='GET', token=None, form=None, payload=None, data=None,
            headers=None, context=None):
    headers = dict(headers or {})
    body = None
    if token:
        headers['Authorization'] = 'Token ' + token
    if form is not None:
        body = urllib.parse.urlencode(form).encode()
        headers['Content-Type'] = 'application/x-www-form-urlencoded'
    elif payload is not None:
        body = json.dumps(payload).encode()
        headers['Content-Type'] = 'application/json'
    elif data is not None:
        body = data if isinstance(data, bytes) else data.encode()
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60, context=context) as response:
            return response.status, response.read().decode(errors='replace')
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode(errors='replace')
    except Exception as error:
        return 0, str(error)


def body_json(body):
    try:
        return json.loads(body)
    except ValueError:
        return {}


def multipart(fields, filename, content):
    boundary = '----CloudFileMetadata' + uuid.uuid4().hex
    chunks = []
    for key, value in fields.items():
        chunks.append('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n'
                      % (boundary, key, value))
    chunks.append('--%s\r\nContent-Disposition: form-data; name="file"; '
                  'filename="%s"\r\nContent-Type: text/plain\r\n\r\n'
                  % (boundary, filename))
    body = ''.join(chunks).encode() + content + ('\r\n--%s--\r\n' % boundary).encode()
    return body, 'multipart/form-data; boundary=' + boundary


def upload(base, token, repo_id, parent_dir, filename, content, context):
    status, body = request(
        base + '/api2/repos/%s/upload-link/?p=%s' %
        (repo_id, urllib.parse.quote(parent_dir)), token=token, context=context)
    upload_url = body.strip('"')
    if status != 200 or not upload_url.startswith('http'):
        return status, body
    data, content_type = multipart({'parent_dir': parent_dir, 'replace': '1'},
                                   filename, content)
    return request(upload_url, method='POST', token=token, data=data,
                   headers={'Content-Type': content_type}, context=context)


def metadata_record(root, token, parent_dir, filename, context):
    query = urllib.parse.urlencode({'parent_dir': parent_dir,
                                    'file_name': filename})
    return request(root + 'record/?' + query, token=token, context=context)


def wait_record(root, token, parent_dir, filename, context, timeout=75):
    deadline = time.time() + timeout
    status, body = 0, ''
    while time.time() < deadline:
        status, body = metadata_record(root, token, parent_dir, filename, context)
        rows = body_json(body).get('results') or []
        if status == 200 and rows:
            return status, body, rows[0]
        time.sleep(3)
    return status, body, None


def wait_tag_file(root, token, tag_id, parent_dir, filename, context,
                  timeout=75):
    deadline = time.time() + timeout
    status, body = 0, ''
    while time.time() < deadline:
        status, body = request(root + 'tag-files/%s/' % tag_id,
                               token=token, context=context)
        rows = body_json(body).get('results') or []
        if status == 200 and any(
                row.get('_parent_dir') == parent_dir and
                row.get('_name') == filename for row in rows):
            return status, body, rows
        time.sleep(3)
    return status, body, []


def check(name, ok, detail=''):
    print('  %s %s%s' % ('✓' if ok else '✗', name,
                         ('\n      ' + detail) if detail and not ok else ''),
          flush=True)
    return ok


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
                                 'password': args.admin_password},
                           context=context)
    token = body_json(body).get('token')
    if not check('管理员登录', bool(token), 'status=%s %s' % (status, body[:200])):
        return 1

    status, body = request(base + '/api2/repos/', method='POST', token=token,
                           form={'name': 'metadata-' + uuid.uuid4().hex[:8]},
                           context=context)
    repo_id = body_json(body).get('repo_id')
    if not check('创建资料库', bool(repo_id), 'status=%s %s' % (status, body[:200])):
        return 1

    root = base + '/api/v2.1/repos/%s/metadata/' % repo_id
    passed = True
    status, body = request(root, token=token, context=context)
    initial = body_json(body)
    passed &= check('新库初始未启用元数据', status == 200 and not initial.get('enabled'),
                    'status=%s %s' % (status, body[:200]))

    status, body = request(root, method='PUT', token=token, context=context)
    passed &= check('启用属性与标签并初始化上游表', status == 200,
                    'status=%s %s' % (status, body[:300]))

    deadline = time.time() + 45
    enabled = {}
    while time.time() < deadline:
        status, body = request(root, token=token, context=context)
        enabled = body_json(body)
        if status == 200 and enabled.get('enabled') and enabled.get('tags_enabled'):
            break
        time.sleep(2)
    passed &= check('属性与标签状态由 CE API 返回',
                    status == 200 and enabled.get('enabled') and enabled.get('tags_enabled'),
                    'status=%s %s' % (status, body[:300]))

    status, body = request(root + 'views/', method='POST', token=token,
                           payload={'name': 'CloudFile Matrix', 'type': 'table'},
                           context=context)
    view = body_json(body).get('view') or {}
    view_id = view.get('_id')
    passed &= check('创建独立元数据视图', status == 200 and bool(view_id),
                    'status=%s %s' % (status, body[:300]))
    status, body = request(root + 'views/', token=token, context=context)
    views = body_json(body).get('views') or []
    passed &= check('多视图配置可读回', status == 200 and
                    any(item.get('_id') == view_id for item in views),
                    'status=%s %s' % (status, body[:300]))

    status, body = request(base + '/api2/repos/%s/dir/?p=/docs' % repo_id,
                           method='POST', token=token,
                           form={'operation': 'mkdir'}, context=context)
    passed &= check('创建文件夹', status in (200, 201),
                    'status=%s %s' % (status, body[:200]))
    status, body = upload(base, token, repo_id, '/docs', 'tracked.txt',
                          b'CloudFile metadata lifecycle\n', context)
    passed &= check('上传待绑定文件', status == 200,
                    'status=%s %s' % (status, body[:200]))

    status, body, record = wait_record(root, token, '/docs', 'tracked.txt',
                                       context)
    record_id = record.get('_id') if record else None
    passed &= check('元数据服务建立文件记录', status == 200 and bool(record_id),
                    'status=%s %s' % (status, body[:400]))

    column_name = 'Department-' + uuid.uuid4().hex[:6]
    status, body = request(root + 'columns/', method='POST', token=token,
                           payload={'column_name': column_name,
                                    'column_type': 'text'}, context=context)
    column = body_json(body).get('column') or {}
    column_key = column.get('key')
    passed &= check('创建自定义文件属性列', status == 200 and bool(column_key),
                    'status=%s %s' % (status, body[:300]))
    if record_id and column_key:
        status, body = request(root + 'record/', method='PUT', token=token,
                               payload={'record_id': record_id,
                                        'data': {column_key: '法务'}},
                               context=context)
        passed &= check('写入自定义文件属性', status == 200,
                        'status=%s %s' % (status, body[:300]))
        status, body = request(root + 'record/?record_id=' +
                               urllib.parse.quote(record_id), token=token,
                               context=context)
        rows = body_json(body).get('results') or []
        passed &= check('自定义属性可读回', status == 200 and rows and
                        rows[0].get(column_key) == '法务',
                        'status=%s %s' % (status, body[:400]))

    tag_name = 'cloudfile-metadata-' + uuid.uuid4().hex[:8]
    # The CE endpoint passes fields through to the metadata table.  The tag
    # name column is the table's internal key (_tag_name), not its display label.
    status, body = request(root + 'tags/', method='POST', token=token,
                           payload={'tags_data': [{'_tag_name': tag_name}]}, context=context)
    tags = body_json(body).get('tags', [])
    tag = next((item for item in tags if item.get('_tag_name') == tag_name), {})
    tag_id = tag.get('_id')
    passed &= check('创建标签写入 metadata-server',
                    status == 200 and bool(tag_id),
                    'status=%s %s' % (status, body[:300]))

    status, body = request(root + 'tags/', token=token, context=context)
    tags = body_json(body).get('results', [])
    passed &= check('标签可从 metadata-server 读回',
                    status == 200 and any(tag.get('_tag_name') == tag_name for tag in tags),
                    'status=%s %s' % (status, body[:300]))

    if record_id and tag_id:
        status, body = request(root + 'file-tags/', method='PUT', token=token,
                               payload={'file_tags_data': [{
                                   'record_id': record_id, 'tags': [tag_id]}]},
                               context=context)
        passed &= check('标签绑定到文件记录', status == 200,
                        'status=%s %s' % (status, body[:300]))
        status, body, _ = wait_tag_file(root, token, tag_id, '/docs',
                                        'tracked.txt', context)
        passed &= check('标签反查命中已绑定文件', bool(_),
                        'status=%s %s' % (status, body[:400]))

        status, body = request(
            base + '/api2/repos/%s/file/?p=/docs/tracked.txt' % repo_id,
            method='POST', token=token,
            form={'operation': 'rename', 'newname': 'renamed.txt'},
            context=context)
        passed &= check('重命名已绑定文件', status == 200,
                        'status=%s %s' % (status, body[:300]))
        status, body, rows = wait_tag_file(root, token, tag_id, '/docs',
                                           'renamed.txt', context)
        passed &= check('重命名后标签跟随', bool(rows),
                        'status=%s %s' % (status, body[:400]))

        request(base + '/api2/repos/%s/dir/?p=/archive' % repo_id,
                method='POST', token=token, form={'operation': 'mkdir'},
                context=context)
        move_payload = {
            'src_repo_id': repo_id, 'dst_repo_id': repo_id,
            'paths': [{'src_path': '/docs/renamed.txt',
                       'dst_path': '/archive'}],
        }
        status, body = request(base + '/api/v2.1/repos/batch-move-item/',
                               method='POST', token=token,
                               payload=move_payload, context=context)
        move_result = body_json(body)
        passed &= check('移动已绑定文件', status == 200 and
                        bool(move_result.get('success')) and
                        not move_result.get('failed'),
                        'status=%s %s' % (status, body[:300]))
        status, body, rows = wait_tag_file(root, token, tag_id, '/archive',
                                           'renamed.txt', context)
        passed &= check('移动后标签跟随', bool(rows),
                        'status=%s %s' % (status, body[:400]))
        status, body, moved_record = wait_record(
            root, token, '/archive', 'renamed.txt', context)
        passed &= check('移动后自定义属性跟随',
                        moved_record is not None and
                        moved_record.get(column_key) == '法务',
                        'status=%s %s' % (status, body[:400]))

        moved_path = '/archive/renamed.txt'
        status, body = request(
            base + '/api2/repos/%s/file/?p=%s' %
            (repo_id, urllib.parse.quote(moved_path)), method='DELETE',
            token=token, context=context)
        passed &= check('删除已绑定文件', status == 200,
                        'status=%s %s' % (status, body[:300]))
        trash_item = None
        deadline = time.time() + 75
        while time.time() < deadline:
            status, body = request(
                base + '/api/v2.1/repos/%s/trash2/?per_page=100' % repo_id,
                token=token, context=context)
            for item in body_json(body).get('items') or []:
                full_path = (item.get('parent_dir') or '/').rstrip('/') + '/' + \
                            (item.get('obj_name') or '')
                if full_path == moved_path:
                    trash_item = item
                    break
            if trash_item:
                break
            time.sleep(3)
        passed &= check('回收站可找到已绑定文件', bool(trash_item),
                        'status=%s %s' % (status, body[:400]))
        if trash_item:
            status, body = request(
                base + '/api/v2.1/repos/%s/trash2/revert/' % repo_id,
                method='POST', token=token,
                payload={trash_item['commit_id']: [moved_path]},
                context=context)
            recover_result = body_json(body)
            passed &= check('恢复已绑定文件', status == 200 and
                            bool(recover_result.get('success')) and
                            not recover_result.get('failed'),
                            'status=%s %s' % (status, body[:300]))
            status, body, rows = wait_tag_file(
                root, token, tag_id, '/archive', 'renamed.txt', context)
            passed &= check('恢复后标签关联回归', bool(rows),
                            'status=%s %s' % (status, body[:400]))
            status, body, recovered_record = wait_record(
                root, token, '/archive', 'renamed.txt', context)
            passed &= check('恢复后自定义属性回归',
                            recovered_record is not None and
                            recovered_record.get(column_key) == '法务',
                            'status=%s %s' % (status, body[:400]))

    request(base + '/api2/repos/%s/' % repo_id, method='DELETE', token=token,
            context=context)
    print('\n════════ %s ════════' % ('通过' if passed else '失败'))
    return 0 if passed else 1


if __name__ == '__main__':
    sys.exit(main())
