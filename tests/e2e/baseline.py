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

#: 由 --insecure 设置；见 main() 里的说明。
_SSL_CONTEXT = None

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
        with urllib.request.urlopen(req, timeout=60,
                                    context=_SSL_CONTEXT) as resp:
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
    ap.add_argument('--insecure', action='store_true',
                    help='接受自签证书。CADDY_TLS=internal 时必需——那是内网与'
                         '试用部署的正常模式，CI 也用它。')
    args = ap.parse_args()

    if args.insecure:
        import ssl
        global _SSL_CONTEXT
        _SSL_CONTEXT = ssl._create_unverified_context()

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

    # 2b. provider 机制装好了，但基线上一个都没选中
    #
    # 这两条分开测是有原因的：providers 键存在证明机制在位（能力可以插进来），
    # selected 全空证明基线仍是原生行为。只测其中一条，另一半坏掉时看不出来。
    providers = data.get('providers')
    record('provider 机制已装配（features 接口返回 providers）',
           isinstance(providers, dict),
           f'实际: {type(providers).__name__} {str(providers)[:160]}')

    if isinstance(providers, dict):
        chosen = {k: v.get('selected') for k, v in providers.items()
                  if v.get('selected')}
        record('基线未选中任何 provider（检索等仍走原生路径）', not chosen,
               f'意外选中: {chosen}')

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

    # 5. 检索扩展点没有改变原生行为
    #
    # 基线上没有 provider，CE 也没有 Elasticsearch，所以上游的正确行为是
    # "搜索未启用"（404/400），而不是 500。会返回 500 说明 search_files 的
    # 委派把 es_search 未定义的情况打穿了——这正是那两处上游改动最可能
    # 引入的回归，值得单独盯一条。
    status, body = request(f'{base}/api2/search/?q=baseline&per_page=1',
                           token=token)
    record('检索委派未破坏原生行为（不应 5xx）', status < 500,
           f'status={status} {body[:200]}')

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
