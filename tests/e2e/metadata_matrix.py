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


def request(url, method='GET', token=None, form=None, payload=None, context=None):
    headers = {}
    body = None
    if token:
        headers['Authorization'] = 'Token ' + token
    if form is not None:
        body = urllib.parse.urlencode(form).encode()
        headers['Content-Type'] = 'application/x-www-form-urlencoded'
    elif payload is not None:
        body = json.dumps(payload).encode()
        headers['Content-Type'] = 'application/json'
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
    task_id = body_json(body).get('task_id')
    passed &= check('启用属性与标签并初始化上游表', status == 200 and bool(task_id),
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

    tag_name = 'cloudfile-metadata-' + uuid.uuid4().hex[:8]
    status, body = request(root + 'tags/', method='POST', token=token,
                           payload={'tags_data': [{'name': tag_name}]}, context=context)
    tags = body_json(body).get('tags', [])
    passed &= check('创建标签写入 metadata-server',
                    status == 200 and any(tag.get('name') == tag_name for tag in tags),
                    'status=%s %s' % (status, body[:300]))

    status, body = request(root + 'tags/', token=token, context=context)
    tags = body_json(body).get('results', [])
    passed &= check('标签可从 metadata-server 读回',
                    status == 200 and any(tag.get('name') == tag_name for tag in tags),
                    'status=%s %s' % (status, body[:300]))

    request(base + '/api2/repos/%s/' % repo_id, method='DELETE', token=token,
            context=context)
    print('\n════════ %s ════════' % ('通过' if passed else '失败'))
    return 0 if passed else 1


if __name__ == '__main__':
    sys.exit(main())
