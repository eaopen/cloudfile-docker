#!/usr/bin/env python3
"""外部资料源能力门禁：只读目录不能变成对象库，也不能越过授权边界。"""

import argparse
import json
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid


FIXTURE = b'CloudFile external source fixture\n'


def request(url, method='GET', token=None, payload=None, context=None,
            raw=False):
    headers = {}
    body = None
    if token:
        headers['Authorization'] = 'Token ' + token
    if payload is not None:
        body = json.dumps(payload).encode()
        headers['Content-Type'] = 'application/json'
    req = urllib.request.Request(url, data=body, method=method,
                                 headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60, context=context) as res:
            data = res.read()
            return res.status, data if raw else data.decode(errors='replace')
    except urllib.error.HTTPError as error:
        data = error.read()
        return error.code, data if raw else data.decode(errors='replace')
    except Exception as error:
        return 0, str(error)


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
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', required=True)
    parser.add_argument('--admin', required=True)
    parser.add_argument('--admin-password', required=True)
    parser.add_argument('--insecure', action='store_true')
    args = parser.parse_args()

    context = ssl._create_unverified_context() if args.insecure else None
    base = args.url.rstrip('/')
    # The token endpoint expects form data, unlike the JSON management API.
    form = urllib.parse.urlencode({
        'username': args.admin, 'password': args.admin_password,
    }).encode()
    req = urllib.request.Request(base + '/api2/auth-token/', data=form,
                                 method='POST', headers={
                                     'Content-Type': 'application/x-www-form-urlencoded',
                                 })
    try:
        with urllib.request.urlopen(req, timeout=60, context=context) as res:
            status, body = res.status, res.read().decode(errors='replace')
    except urllib.error.HTTPError as error:
        status, body = error.code, error.read().decode(errors='replace')
    token = body_json(body).get('token')
    if not check('管理员登录', bool(token), 'status=%s %s' % (status, body[:200])):
        return 1

    passed = True
    name = 'external-e2e-' + uuid.uuid4().hex[:8]
    status, body = request(base + '/api/v2.1/admin/cloudfile/external-sources/',
                           method='POST', token=token, payload={
                               'name': name, 'source_type': 'local-path',
                               'root_path': '/shared/external/e2e',
                           }, context=context)
    source = body_json(body)
    source_id = source.get('id')
    passed &= check('登记已挂载目录', bool(source_id),
                    'status=%s %s' % (status, body[:300]))
    if not source_id:
        return 1

    status, body = request(base + '/api/v2.1/cloudfile/external-sources/',
                           token=token, context=context)
    visible = body_json(body).get('sources') or []
    passed &= check('可见源列表包含登记项', status == 200 and
                    any(item.get('id') == source_id for item in visible),
                    'status=%s %s' % (status, body[:300]))

    status, body = request(base + '/api/v2.1/cloudfile/external-sources/%s/dir/?p=/' % source_id,
                           token=token, context=context)
    entries = body_json(body).get('dirent_list') or []
    passed &= check('只读目录列举 fixture', status == 200 and
                    {entry.get('name') for entry in entries} >= {'readme.txt', 'nested'},
                    'status=%s %s' % (status, body[:500]))

    status, body = request(base + '/api/v2.1/cloudfile/external-sources/%s/file/?p=/readme.txt' % source_id,
                           token=token, context=context)
    passed &= check('读取文件元数据', status == 200 and
                    body_json(body).get('type') == 'file',
                    'status=%s %s' % (status, body[:300]))

    status, data = request(base + '/api/v2.1/cloudfile/external-sources/%s/file/?p=/readme.txt&op=download' % source_id,
                           token=token, context=context, raw=True)
    passed &= check('流式下载字节一致', status == 200 and data == FIXTURE,
                    'status=%s len=%s' % (status, len(data) if isinstance(data, bytes) else 0))

    repo_id = source.get('repo_id')
    status, body = request(base + '/api/v2.1/repos/?type=shared',
                           token=token, context=context)
    shadow_repos = body_json(body).get('repos') or []
    passed &= check('影子库出现在原生共享库列表', status == 200 and
                    any(item.get('repo_id') == repo_id and
                        item.get('is_external_source') for item in shadow_repos),
                    'status=%s %s' % (status, body[:500]))

    status, body = request(base + '/api/v2.1/repos/%s/dir/?p=/' % repo_id,
                           token=token, context=context)
    shadow_entries = body_json(body).get('dirent_list') or []
    passed &= check('影子库目录仍从挂载目录读取', status == 200 and
                    {entry.get('name') for entry in shadow_entries} >=
                    {'readme.txt', 'nested'},
                    'status=%s %s' % (status, body[:500]))

    status, body = request(base + '/api2/repos/%s/file/?p=/readme.txt&op=download' % repo_id,
                           token=token, context=context)
    shadow_download = body_json(body)
    passed &= check('影子下载指向 Hub 数据面', status == 200 and
                    isinstance(shadow_download, str) and
                    '/api/v2.1/cloudfile/external-sources/%s/file/' % source_id
                    in shadow_download,
                    'status=%s %s' % (status, body[:300]))

    status, body = request(base + '/api/v2.1/cloudfile/external-sources/%s/overlay/' % source_id,
                           method='PUT', token=token, payload={
                               'path': '/readme.txt',
                               'metadata': {'classification': 'internal'},
                               'tags': ['finance', 'internal'],
                           }, context=context)
    overlay = body_json(body)
    passed &= check('Overlay 只保存路径元数据和标签', status == 200 and
                    overlay.get('metadata', {}).get('classification') == 'internal' and
                    overlay.get('tags') == ['finance', 'internal'],
                    'status=%s %s' % (status, body[:300]))

    status, body = request(base + '/api/v2.1/cloudfile/external-sources/%s/overlay/?p=/readme.txt' % source_id,
                           token=token, context=context)
    passed &= check('Overlay 可按外部路径读回', status == 200 and
                    body_json(body).get('tags') == ['finance', 'internal'],
                    'status=%s %s' % (status, body[:300]))

    status, body = request(base + '/api/v2.1/cloudfile/external-sources/%s/dir/?p=%%2F..%%2F' % source_id,
                           token=token, context=context)
    passed &= check('拒绝目录逃逸', status == 400,
                    'status=%s %s' % (status, body[:200]))

    status, body = request(base + '/api/v2.1/admin/cloudfile/external-sources/%s/' % source_id,
                           method='PUT', token=token, payload={'enabled': False}, context=context)
    passed &= check('可以禁用源', status == 200 and not body_json(body).get('enabled'),
                    'status=%s %s' % (status, body[:200]))

    status, body = request(base + '/api/v2.1/cloudfile/external-sources/%s/dir/?p=/' % source_id,
                           token=token, context=context)
    passed &= check('禁用后拒绝数据面访问', status == 404,
                    'status=%s %s' % (status, body[:200]))

    status, body = request(base + '/api/v2.1/admin/cloudfile/external-sources/%s/' % source_id,
                           method='DELETE', token=token, context=context)
    passed &= check('删除源与授权记录', status == 200 and body_json(body).get('success'),
                    'status=%s %s' % (status, body[:200]))

    print('\n════════ 外部资料源 %s ════════' % ('通过' if passed else '失败'))
    return 0 if passed else 1


if __name__ == '__main__':
    sys.exit(main())
