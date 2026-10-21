#!/usr/bin/env python3
"""S3/多存储端到端门禁：单一 S3 后端可用，且离线跨存储迁移后数据仍然正确。

这条门禁只覆盖 REST 可达的部分（上传/下载走的是同一条 HTTP 路径，backend 选
FS 还是 S3 对客户端透明）。GC/FSCK 的完整遍历、修复模式的停服校验，以及
seaf-storage-migrate.sh 本身，都是宿主机侧的 CLI 行为，不经过这条 HTTP 通道
——它们由 verify-local.sh 的 cap_storage_run 用
`docker compose exec`/`docker compose run` 直接驱动，跟这份脚本配合，但不在
这份脚本里。

两阶段，跨一次离线迁移：

    phase 1 —— 建库、上传一个跨多个 block 的文件、验证读回内容一致，
               把 repo_id 写进 --state-file 供外部编排读取
    phase 2 —— （migrate + 重启之后）验证同一个文件仍然读回一致，
               且迁移后的库仍然可以继续写入

文件故意选得比默认 block 大小（8MB）大，确保迁移路径真的搬了不止一个 block，
而不是凑巧只有一个对象、把"分块迁移"和"整库当成单个 blob 复制"混为一谈。
"""

import argparse
import hashlib
import json
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

#: 故意超过默认 8MB 的 block 大小，确保迁移路径真的搬运了不止一个 block。
CONTENT_SIZE = 12 * 1024 * 1024
CONTENT_PATTERN = b'cloudfile storage matrix payload '
FILENAME = 'storage-matrix.bin'
SECOND_FILENAME = 'storage-matrix-post-migration.txt'
REPO_PREFIX = 'storage-matrix-'


def build_content():
    reps = CONTENT_SIZE // len(CONTENT_PATTERN) + 1
    return (CONTENT_PATTERN * reps)[:CONTENT_SIZE]


def request(url, method='GET', token=None, form=None, data=None, headers=None,
           context=None, raw=False):
    hdrs = dict(headers or {})
    body = None
    if token:
        hdrs['Authorization'] = 'Token ' + token
    if form is not None:
        body = urllib.parse.urlencode(form).encode()
        hdrs['Content-Type'] = 'application/x-www-form-urlencoded'
    elif data is not None:
        body = data if isinstance(data, bytes) else data.encode()
    req = urllib.request.Request(url, data=body, method=method, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=120, context=context) as response:
            payload = response.read()
            return response.status, payload if raw else payload.decode(errors='replace')
    except urllib.error.HTTPError as error:
        payload = error.read()
        return error.code, payload if raw else payload.decode(errors='replace')
    except Exception as error:
        return 0, str(error)


def json_body(body):
    try:
        return json.loads(body)
    except (TypeError, ValueError):
        return {}


def multipart(fields, filename, content):
    boundary = '----CloudFileStorage' + uuid.uuid4().hex
    chunks = []
    for key, value in fields.items():
        chunks.append('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n'
                      % (boundary, key, value))
    chunks.append('--%s\r\nContent-Disposition: form-data; name="file"; '
                  'filename="%s"\r\nContent-Type: application/octet-stream\r\n\r\n'
                  % (boundary, filename))
    body = ''.join(chunks).encode() + content + ('\r\n--%s--\r\n' % boundary).encode()
    return body, 'multipart/form-data; boundary=' + boundary


def check(name, ok, detail=''):
    print('  %s %s%s' % ('✓' if ok else '✗', name,
                         ('\n      ' + detail) if detail and not ok else ''),
          flush=True)
    return ok


def login(base, admin, password, context):
    status, body = request(base + '/api2/auth-token/', method='POST',
                           form={'username': admin, 'password': password},
                           context=context)
    return json_body(body).get('token'), status, body


def upload(base, token, repo_id, path, filename, content, context):
    status, body = request(base + '/api2/repos/%s/upload-link/?p=%s' %
                           (repo_id, urllib.parse.quote(path)),
                           token=token, context=context)
    upload_url = body.strip('"')
    if status != 200 or not upload_url.startswith('http'):
        return False, 'status=%s %s' % (status, body[:200])
    data, ctype = multipart({'parent_dir': path, 'replace': '1'}, filename, content)
    status, body = request(upload_url, method='POST', token=token, data=data,
                           headers={'Content-Type': ctype}, context=context)
    return status == 200, 'status=%s %s' % (status, body[:200])


def download(base, token, repo_id, path, context):
    status, body = request(base + '/api2/repos/%s/file/?p=%s' %
                           (repo_id, urllib.parse.quote(path)),
                           token=token, context=context)
    dl_url = body.strip('"')
    if status != 200 or not dl_url.startswith('http'):
        return None, 'status=%s %s' % (status, body[:200])
    status, payload = request(dl_url, token=token, context=context, raw=True)
    if status != 200:
        return None, 'download status=%s' % status
    return payload, 'status=%s len=%s' % (status, len(payload))


def phase1(base, admin, password, context, state_file):
    token, status, body = login(base, admin, password, context)
    if not check('管理员登录', bool(token), 'status=%s %s' % (status, body[:200])):
        return False

    repo_name = REPO_PREFIX + uuid.uuid4().hex[:8]
    status, body = request(base + '/api2/repos/', method='POST', token=token,
                           form={'name': repo_name}, context=context)
    repo_id = json_body(body).get('repo_id')
    if not check('创建资料库', bool(repo_id), 'status=%s %s' % (status, body[:200])):
        return False

    content = build_content()
    digest = hashlib.sha256(content).hexdigest()
    ok, detail = upload(base, token, repo_id, '/', FILENAME, content, context)
    passed = check('上传跨多 block 的文件', ok, detail)

    payload, detail = download(base, token, repo_id, '/' + FILENAME, context)
    passed &= check('下载内容与上传字节一致',
                    payload is not None and hashlib.sha256(payload).hexdigest() == digest,
                    detail)

    if passed:
        with open(state_file, 'w') as fh:
            json.dump({'repo_id': repo_id, 'sha256': digest, 'size': len(content)}, fh)

    print('\n════════ phase 1 %s ════════' % ('通过' if passed else '失败'))
    return passed


def phase2(base, admin, password, context, state_file):
    try:
        with open(state_file) as fh:
            state = json.load(fh)
    except (OSError, ValueError) as error:
        check('读取 phase 1 状态文件', False, str(error))
        return False
    repo_id = state['repo_id']

    token, status, body = login(base, admin, password, context)
    if not check('管理员登录', bool(token), 'status=%s %s' % (status, body[:200])):
        return False

    payload, detail = download(base, token, repo_id, '/' + FILENAME, context)
    passed = check(
        '迁移后读回内容仍与迁移前一致',
        payload is not None and hashlib.sha256(payload).hexdigest() == state['sha256']
        and len(payload) == state['size'],
        detail)

    ok, detail = upload(base, token, repo_id, '/', SECOND_FILENAME,
                        b'cloudfile storage matrix post-migration write\n', context)
    passed &= check('迁移后的库仍可继续写入', ok, detail)

    status, body = request(base + '/api2/repos/%s/dir/?p=/' % repo_id,
                           token=token, context=context)
    names = [entry.get('name') for entry in (json_body(body) or [])]
    passed &= check('迁移前后上传的文件都在列举里',
                    FILENAME in names and SECOND_FILENAME in names,
                    'status=%s 实际=%s' % (status, names))

    request(base + '/api2/repos/%s/' % repo_id, method='DELETE', token=token,
           context=context)

    print('\n════════ phase 2 %s ════════' % ('通过' if passed else '失败'))
    return passed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', required=True)
    parser.add_argument('--admin', required=True)
    parser.add_argument('--admin-password', required=True)
    parser.add_argument('--insecure', action='store_true')
    parser.add_argument('--phase', type=int, choices=(1, 2), required=True)
    parser.add_argument('--state-file', required=True,
                        help='phase 1 写入 repo_id/sha256；phase 2 读取以定位同一个库')
    args = parser.parse_args()

    context = ssl._create_unverified_context() if args.insecure else None
    base = args.url.rstrip('/')

    run = phase1 if args.phase == 1 else phase2
    ok = run(base, args.admin, args.admin_password, context, args.state_file)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
