#!/usr/bin/env python3
"""扩展基线验收：扩展点装好了，但没有任何能力启用。

smoke.py 证明"行为和原生 CE 一样"。这份证明的是另一半：**扩展机制确实生效了**。

两者都必要。只跑 smoke 的话，一个 cloudfile_ext 根本没被加载的镜像也能通过——
那样基线看似完好，实则什么扩展点都没有，等到第一个能力接上去才会发现。

检查项：
  - CloudFile 能力查询接口存在且可用（说明 cloudfile_ext 被 Django 加载了，
    路由经 rooturl.py 挂上了）
  - 所有 CF_ENABLE_* 都报告为关闭
  - 没有任何能力路由存在（能力分支才会带来它们）
  - 权限钩子链是透传的：原生权限没有被改变

只用标准库。

    python3 baseline.py --url http://localhost --admin me@example.com \\
        --admin-password xxx
"""

import argparse
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
    print(f'  {"✓" if ok else "✗"} {case}'
          + (f'\n      {detail}' if detail and not ok else ''), flush=True)


def request(url, method='GET', token=None, form=None):
    headers = {}
    body = None
    if token:
        headers['Authorization'] = f'Token {token}'
    if form is not None:
        body = urllib.parse.urlencode(form).encode()
        headers['Content-Type'] = 'application/x-www-form-urlencoded'

    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, resp.read().decode(errors='replace')
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors='replace')
    except Exception as e:
        return 0, str(e)


def jbody(body):
    try:
        return json.loads(body)
    except Exception:
        return None


def wait_ready(base, timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        status, body = request(base + '/api2/ping/')
        if status == 200 and 'pong' in body:
            return True
        time.sleep(5)
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

    print('\n扩展基线验收…', flush=True)

    status, body = request(base + '/api2/auth-token/', method='POST',
                           form={'username': args.admin,
                                 'password': args.admin_password})
    token = (jbody(body) or {}).get('token')
    if not token:
        sys.exit(f'登录失败: {status} {body}')

    # 1. 扩展框架确实被加载了
    status, body = request(base + '/api/v2.1/cloudfile/features/', token=token)
    data = jbody(body) or {}
    features = data.get('features')
    record('能力查询接口可用（cloudfile_ext 已加载、路由已挂载）',
           status == 200 and isinstance(features, dict),
           f'status={status} {body[:200]}')

    if not isinstance(features, dict):
        # 后面的检查都建立在这个之上，没必要继续。
        print('\n════════ 基线未装配，后续检查跳过 ════════')
        sys.exit(1)

    # 2. 开关清单完整，且全部关闭
    expected = {
        'CF_ENABLE_SSO', 'CF_ENABLE_DIR_ACL', 'CF_ENABLE_AUDIT',
        'CF_ENABLE_METADATA', 'CF_ENABLE_TAGS', 'CF_ENABLE_MEILISEARCH',
        'CF_ENABLE_ONLYOFFICE', 'CF_ENABLE_CHECKOUT', 'CF_ENABLE_S3_STORAGE',
        'CF_ENABLE_EXTERNAL_SOURCES',
    }
    record('开关清单与约定一致', set(features) == expected,
           f'多出: {sorted(set(features) - expected)} 缺少: {sorted(expected - set(features))}')

    on = sorted(k for k, v in features.items() if v)
    record('所有开关均为关闭', not on, f'意外开启: {on}')

    # 3. 基线不应带来任何能力路由
    status, body = request(base + '/api2/repos/', method='POST',
                           token=token, form={'name': 'baseline-' + uuid.uuid4().hex[:6]})
    repo_id = (jbody(body) or {}).get('repo_id')
    if not repo_id:
        sys.exit(f'建库失败: {status} {body}')

    status, _ = request(
        f'{base}/api/v2.1/cloudfile/repos/{repo_id}/dir-acl/?path=/', token=token)
    record('能力路由不存在（dir-acl 应 404）', status == 404, f'status={status}')

    # 4. 权限钩子链透传：没有能力注册时，原生权限不被改变
    status, body = request(f'{base}/api2/repos/{repo_id}/dir/?p=/', token=token)
    record('目录列举正常（列举钩子透传）', status == 200,
           f'status={status} {body[:120]}')

    status, body = request(f'{base}/api2/repos/{repo_id}/download-info/',
                           token=token)
    record('库可同步（子树校验钩子透传）', status == 200,
           f'status={status} {body[:160]}')

    request(f'{base}/api2/repos/{repo_id}/', method='DELETE', token=token)

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
