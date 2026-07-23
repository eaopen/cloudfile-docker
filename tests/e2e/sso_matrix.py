#!/usr/bin/env python3
"""SSO 组织映射验收矩阵。

这是簇 B 的验收门禁。单元测试证明**编排算得对**（cloudfile_ext/sso/reconcile.py
的 14 项，含五个变异），这份脚本证明算出来的结果**真的落到了 ccnet 里**，而且
落对了方向——加得进去、也删得掉。

分两个阶段跑，中间要改 .env 并重启：

    阶段 1  目录里 eng=[A,B]、sales=[B]
            → 两个组被建出来，A 看到 eng，B 看到两个
    阶段 2  目录改成 eng=[A]，sales 整个消失
            → B 被移出 eng；sales 只是解除映射，**组本身还在**

两个阶段是必要的，不是为了凑数：

  * **删除方向只有阶段 2 能测。** 一个只会加人的同步在阶段 1 里全绿，而"离职的
    人还留在组里"是这套东西唯一真正危险的失效方式。
  * **重启这一步本身就是被测对象。** 配置是每次启动重写的（write_cloudfile_config），
    改了 .env 却不生效是这套部署踩过的坑；阶段 2 顺带证明它没回来。

只用标准库，容器与 CI 都不需要额外安装。

    python3 sso_matrix.py --phase 1 --url https://127.0.0.1 --insecure \\
        --admin me@example.com --admin-password xxx
"""

import argparse
import base64
import hashlib
import hmac
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

#: 由 --insecure 设置。与 smoke.py / acl_matrix.py 保持同一种做法。
_SSL_CONTEXT = None

A_EMAIL = 'sso-matrix-a@example.com'
A_PASSWORD = 'SsoMatrix-A-6318'
B_EMAIL = 'sso-matrix-b@example.com'
B_PASSWORD = 'SsoMatrix-B-6318'

ENG = 'eng'
ENG_NAME = 'SSO Engineering'
SALES = 'sales'
SALES_NAME = 'SSO Sales'

results = []


def record(area, case, ok, detail=''):
    results.append((area, case, ok, detail))
    mark = '✓' if ok else '✗'
    line = f'  {mark} [{area}] {case}'
    if detail and not ok:
        line += f'\n      {detail}'
    print(line, flush=True)


def request(url, method='GET', token=None, data=None, form=None, headers=None):
    """返回 (status, body)。HTTP 错误不抛异常——本脚本也断言 403/404。"""
    hdrs = dict(headers or {})
    body = None

    if token:
        hdrs['Authorization'] = f'Token {token}'
    if form is not None:
        body = urllib.parse.urlencode(form).encode()
        hdrs['Content-Type'] = 'application/x-www-form-urlencoded'
    elif data is not None:
        body = data if isinstance(data, bytes) else data.encode()

    req = urllib.request.Request(url, data=body, method=method, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=120,
                                    context=_SSL_CONTEXT) as resp:
            return resp.status, resp.read().decode(errors='replace')
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors='replace')
    except Exception as e:
        return 0, str(e)


def json_body(body):
    try:
        return json.loads(body)
    except Exception:
        return None


class Client:
    def __init__(self, base, token=None):
        self.base = base.rstrip('/')
        self.token = token

    def api(self, path, method='GET', **kw):
        return request(self.base + path, method=method, token=self.token, **kw)


def wait_ready(base, timeout=600):
    print(f'等待 {base} 就绪（最多 {timeout}s）…', flush=True)
    deadline = time.time() + timeout
    last = ''
    while time.time() < deadline:
        status, body = request(base + '/api2/ping/')
        if status == 200 and 'pong' in body:
            print('  服务已就绪', flush=True)
            return True
        last = f'status={status} {body[:120]}'
        time.sleep(5)
    print(f'  超时：{last}', file=sys.stderr)
    return False


def get_token(base, email, password):
    status, body = request(base + '/api2/auth-token/', method='POST',
                           form={'username': email, 'password': password})
    return (json_body(body) or {}).get('token'), status, body


def ensure_user(admin, base, email, password):
    """建用户（已存在则复用），返回它的 token。

    返回值必须检查：建用户失败时接口不一定是非 200，而后面每一条断言都会以
    "这个人什么组都没有"的形式失败——离真因很远。acl_matrix 被这个套路坑过。
    """
    status, body = admin.api('/api/v2.1/admin/users/', method='POST',
                             form={'email': email, 'password': password})
    if status not in (200, 201) and 'exist' not in body.lower():
        sys.exit(f'建用户 {email} 失败: {status} {body}')

    token, status, body = get_token(base, email, password)
    if not token:
        sys.exit(f'无法取得 {email} 的 token: {status} {body}')
    return token


def group_names(client):
    status, body = client.api('/api/v2.1/groups/')
    data = json_body(body)
    if status != 200 or not isinstance(data, list):
        return None, f'status={status} {body[:160]}'
    return {g.get('name') for g in data}, ''


def mappings(admin):
    status, body = admin.api('/api/v2.1/admin/cloudfile/sso/group-map/')
    data = json_body(body) or {}
    return {m['external_id']: m for m in data.get('mappings', [])}, status, body


def run_sync(admin):
    status, body = admin.api('/api/v2.1/admin/cloudfile/sso/sync/',
                             method='POST')
    return status, json_body(body) or {}, body


# -- 前置：开关和 provider 真的开着 ---------------------------------------
#
# 全绿但开关其实没开的矩阵毫无意义，而且失败完全静默。ACL 那轮就是靠这条
# 检查才发现本地门禁写了 .env 却没生效。

def check_enabled(admin):
    status, body = admin.api('/api/v2.1/cloudfile/features/')
    data = json_body(body) or {}
    record('前置', 'CF_ENABLE_SSO 确实为 true',
           data.get('features', {}).get('CF_ENABLE_SSO') is True,
           f'status={status} {body[:200]}')

    selected = (data.get('providers', {})
                    .get('sso_directory', {})
                    .get('selected'))
    record('前置', 'CF_PROVIDER_SSO_DIRECTORY 已选中', bool(selected),
           f'providers={data.get("providers")}')


def check_worker(admin, timeout):
    """Verify the scheduled path, not merely the admin button.

    The worker's first task is due immediately.  It may run before this matrix
    creates its sample users, which is intentional: a directory member that
    is not yet a Seafile account is reported as unresolved but must not make
    the scheduler or the shared RPC connection fail.
    """
    deadline = time.time() + timeout
    last = ''
    while time.time() < deadline:
        status, body = admin.api('/api/v2.1/admin/cloudfile/sso/sync/')
        data = json_body(body) or {}
        if status == 200 and data.get('last_run') and data.get('last_status') == 'ok':
            record('worker', '周期 worker 已完成首次 SSO 同步', True)
            return
        last = f'status={status} body={body[:240]}'
        time.sleep(2)
    record('worker', '周期 worker 已完成首次 SSO 同步', False, last)


# -- 阶段 1 ----------------------------------------------------------------

def phase_one(admin, base, require_worker=False, worker_timeout=90,
              webhook_secret=''):
    if require_worker:
        check_worker(admin, worker_timeout)

    a_token = ensure_user(admin, base, A_EMAIL, A_PASSWORD)
    b_token = ensure_user(admin, base, B_EMAIL, B_PASSWORD)

    status, result, raw = run_sync(admin)
    record('同步', '手动触发同步成功',
           status == 200 and result.get('status') == 'ok',
           f'status={status} {raw[:300]}')

    mapped, status, raw = mappings(admin)
    record('映射', 'eng 与 sales 都被建出来并记录',
           {ENG, SALES} <= set(mapped),
           f'status={status} {raw[:300]}')
    record('映射', '组名跟随目录',
           mapped.get(ENG, {}).get('name') == ENG_NAME,
           f'mapped={mapped}')

    a_groups, detail = group_names(Client(base, a_token))
    record('成员', 'A 进了 eng', bool(a_groups) and ENG_NAME in a_groups,
           detail or f'groups={a_groups}')
    record('成员', 'A 没进 sales', a_groups is not None and SALES_NAME not in a_groups,
           detail or f'groups={a_groups}')

    b_groups, detail = group_names(Client(base, b_token))
    record('成员', 'B 进了两个组',
           bool(b_groups) and {ENG_NAME, SALES_NAME} <= b_groups,
           detail or f'groups={b_groups}')

    # 幂等：同一份目录再同步一次不该动任何东西。不成立的话每个 tick 都会把
    # 人踢出去再加回来——组本身看起来正常，而通知和审计会被刷屏。
    status, result, raw = run_sync(admin)
    applied = (json_body(result.get('detail') or '{}') or {}).get('applied', {})
    record('同步', '重复同步不产生任何改动',
           status == 200 and result.get('status') == 'ok'
           and sum(applied.values()) == 0,
           f'applied={applied} raw={raw[:300]}')

    # 干跑：管理员要能在不改任何东西的前提下看到"下一次会做什么"。
    status, body = admin.api(
        '/api/v2.1/admin/cloudfile/sso/sync/?dry_run=true')
    data = json_body(body) or {}
    record('可观测', '干跑给出空计划',
           status == 200 and data.get('plan') is not None
           and sum(data['plan'].values()) == 0,
           f'status={status} {body[:300]}')
    record('可观测', '状态里有上次同步的时间与结果',
           bool(data.get('last_run')) and data.get('last_status') == 'ok',
           f'{body[:300]}')

    check_webhook(base, webhook_secret)


def _webhook_token(secret, expired=False):
    """Create the small HS256 token the webhook accepts without PyJWT."""
    def encode(value):
        raw = json.dumps(value, separators=(',', ':')).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b'=')

    header = encode({'alg': 'HS256', 'typ': 'JWT'})
    payload = encode({'exp': int(time.time()) + (-60 if expired else 60)})
    signed = header + b'.' + payload
    signature = hmac.new(secret.encode(), signed, hashlib.sha256).digest()
    return (signed + b'.' + base64.urlsafe_b64encode(signature).rstrip(b'=')).decode()


def check_webhook(base, secret=''):
    """Verify both safe-off and signed callback paths."""
    endpoint = base + '/api/v2.1/cloudfile/sso/directory-webhook/'
    if secret:
        status, body = request(endpoint, method='POST')
        record('webhook', '未签名回调被拒绝', status == 403,
               f'status={status} {body[:200]}')
        expired = _webhook_token(secret, expired=True)
        status, body = request(endpoint, method='POST',
                               headers={'Authorization': f'Token {expired}'})
        record('webhook', '过期签名回调被拒绝', status == 403,
               f'status={status} {body[:200]}')
        valid = _webhook_token(secret)
        status, body = request(endpoint, method='POST',
                               headers={'Authorization': f'Token {valid}'})
        result = json_body(body) or {}
        record('webhook', '有效签名触发目录同步',
               status == 200 and result.get('status') == 'ok',
               f'status={status} {body[:200]}')
        return

    # It triggers outbound calls, so with no shared secret it must not exist.
    status, body = request(endpoint, method='POST')
    record('webhook', '未配置 secret 时 webhook 不可用', status in (403, 404),
           f'status={status} {body[:200]}')


# -- 阶段 2：目录变小之后 --------------------------------------------------

def phase_two(admin, base):
    a_token = ensure_user(admin, base, A_EMAIL, A_PASSWORD)
    b_token = ensure_user(admin, base, B_EMAIL, B_PASSWORD)

    # 配置在每次启动时重写。这条断言先于同步，因为如果 .env 没生效，下面
    # 每一条都会以"目录没变"的形式失败，而那和"同步不会删人"长得一模一样。
    status, body = admin.api(
        '/api/v2.1/admin/cloudfile/sso/sync/?dry_run=true')
    plan = (json_body(body) or {}).get('plan') or {}
    record('配置', '改过的 .env 在重启后生效（计划里有删除与解除映射）',
           plan.get('remove', 0) >= 1 and plan.get('unmap', 0) >= 1,
           f'plan={plan} body={body[:300]}')

    status, result, raw = run_sync(admin)
    record('同步', '同步成功', status == 200 and result.get('status') == 'ok',
           f'status={status} {raw[:300]}')

    b_groups, detail = group_names(Client(base, b_token))
    record('成员', 'B 已被移出 eng',
           b_groups is not None and ENG_NAME not in b_groups,
           detail or f'groups={b_groups}')

    a_groups, detail = group_names(Client(base, a_token))
    record('成员', 'A 仍在 eng 里（对照，防"整个组被清空"也算通过）',
           bool(a_groups) and ENG_NAME in a_groups,
           detail or f'groups={a_groups}')

    mapped, status, raw = mappings(admin)
    record('映射', 'sales 的映射被解除', SALES not in mapped,
           f'mapped={list(mapped)}')
    record('映射', 'eng 的映射还在', ENG in mapped, f'mapped={list(mapped)}')

    # 组本身必须还在：它可能拥有资料库、被共享进来。解除映射是可逆的，
    # 删除不是——所以一个同步 tick 永远不该能做这个决定。
    record('映射', '离开目录的组只是不再被同步，组本身仍然存在',
           b_groups is not None and SALES_NAME in b_groups,
           f'B 的组={b_groups}')

    # 管理员手动解除映射：同样只动映射。放在最后，因为之后再同步会重新建组。
    status, body = admin.api(
        '/api/v2.1/admin/cloudfile/sso/group-map/?external_id=' + ENG,
        method='DELETE')
    mapped, _, _ = mappings(admin)
    record('映射', '管理员可以手动解除映射',
           status == 200 and ENG not in mapped,
           f'status={status} {body[:200]} mapped={list(mapped)}')

    a_groups, detail = group_names(Client(base, a_token))
    record('映射', '手动解除映射之后组和成员都还在',
           bool(a_groups) and ENG_NAME in a_groups,
           detail or f'groups={a_groups}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--phase', type=int, choices=(1, 2), required=True)
    ap.add_argument('--url', default='http://localhost')
    ap.add_argument('--admin', required=True)
    ap.add_argument('--admin-password', required=True)
    ap.add_argument('--timeout', type=int, default=600)
    ap.add_argument('--require-worker', action='store_true',
                    help='require cf-worker to complete its first scheduled sync')
    ap.add_argument('--worker-timeout', type=int, default=90)
    ap.add_argument('--webhook-secret', default='',
                    help='verify signed directory webhook with this shared secret')
    ap.add_argument('--insecure', action='store_true',
                    help='接受自签证书。CADDY_TLS=internal 时必需。')
    args = ap.parse_args()

    if args.insecure:
        import ssl
        global _SSL_CONTEXT
        _SSL_CONTEXT = ssl._create_unverified_context()

    base = args.url.rstrip('/')

    if not wait_ready(base, args.timeout):
        sys.exit('服务未就绪')

    token, status, body = get_token(base, args.admin, args.admin_password)
    if not token:
        sys.exit(f'管理员登录失败: {status} {body}')
    admin = Client(base, token)

    print(f'\n阶段 {args.phase}…', flush=True)
    check_enabled(admin)
    if args.phase == 1:
        phase_one(admin, base, args.require_worker, args.worker_timeout,
                  args.webhook_secret)
    else:
        phase_two(admin, base)

    passed = sum(1 for *_, ok, _ in results if ok)
    total = len(results)
    print(f'\n════════ {passed}/{total} 通过 ════════')

    if passed != total:
        print('\n失败项：')
        for area, case, ok, detail in results:
            if not ok:
                print(f'  [{area}] {case}\n      {detail}')
        sys.exit(1)


if __name__ == '__main__':
    main()
