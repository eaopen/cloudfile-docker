#!/usr/bin/env python3
"""目录 ACL 六入口验收矩阵。

这是 P1 的验收门禁。单元测试证明求解器算得对，这份脚本证明**算出来的结果真的
被每个入口执行了**——两者不能互相替代：ACL 最容易出的问题不是算错，而是某个
入口压根没走校验。

场景（对齐 docs/acl-semantics.md）：

    库 acl-matrix，owner 建立，共享给 B 且为 rw
    /public       无规则           B 应为 rw
    /restricted   B -> r           B 只读
    /secret       B -> invisible   B 完全不可见

只用标准库，容器与 CI 都不需要额外安装。

    python3 acl_matrix.py --url http://localhost --admin me@example.com \\
        --admin-password xxx
"""

import argparse
import base64
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

#: 由 --insecure 设置；见 main() 里的说明。与 smoke.py 保持同一种做法。
_SSL_CONTEXT = None

B_EMAIL = 'acl-matrix-b@example.com'
B_PASSWORD = 'AclMatrix-B-9271'
REPO_NAME = 'acl-matrix'

results = []


def record(entry, case, ok, detail=''):
    results.append((entry, case, ok, detail))
    mark = '✓' if ok else '✗'
    line = f'  {mark} [{entry}] {case}'
    if detail and not ok:
        line += f'\n      {detail}'
    print(line, flush=True)


def request(url, method='GET', token=None, data=None, form=None,
            basic=None, headers=None, raw=False):
    """返回 (status, body)。HTTP 错误不抛异常——本脚本大量断言 403。"""
    hdrs = dict(headers or {})
    body = None

    if token:
        hdrs['Authorization'] = f'Token {token}'
    if basic:
        cred = base64.b64encode(basic.encode()).decode()
        hdrs['Authorization'] = f'Basic {cred}'
    if form is not None:
        body = urllib.parse.urlencode(form).encode()
        hdrs['Content-Type'] = 'application/x-www-form-urlencoded'
    elif data is not None:
        body = data if isinstance(data, bytes) else data.encode()

    req = urllib.request.Request(url, data=body, method=method, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=60,
                                    context=_SSL_CONTEXT) as resp:
            payload = resp.read()
            return resp.status, payload if raw else payload.decode(errors='replace')
    except urllib.error.HTTPError as e:
        payload = e.read()
        return e.code, payload if raw else payload.decode(errors='replace')
    except Exception as e:                      # 连接错误等
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
    data = json_body(body) or {}
    return data.get('token'), status, body


def resolve_identity(admin, email):
    """把登录邮箱换成 seafile 内部身份。

    Seafile 14 之后两者不是一回事：账号的主键是不透明 id（`...@auth.local`），
    邮箱只是登录属性。共享接口要的是 id。

    ACL 规则则**故意仍然用邮箱下发**——CloudFile 的 ACL 接口负责自己解析，
    而"管理员填邮箱、规则却存了一个永远匹配不上的字符串"正是这一轮抓到的缺陷，
    所以这条路径必须被测到。
    """
    status, body = admin.api('/api/v2.1/admin/users/')
    for user in (json_body(body) or {}).get('data', []):
        if email in (user.get('email'), user.get('contact_email'),
                     user.get('login_id')):
            return user.get('email')
        # 14 把邮箱本地部分放进了 name，id 形如 <hex>@auth.local
        if user.get('name') == email.split('@')[0]:
            return user.get('email')
    sys.exit(f'在用户列表里找不到 {email}: {status} {body[:200]}')


def setup(admin, base):
    """建用户、建库、建目录、共享、下 ACL 规则。返回 (repo_id, b_token)。"""
    print('\n准备场景…', flush=True)

    # 用户 B —— 已存在则忽略
    status, body = admin.api('/api/v2.1/admin/users/', method='POST',
                             form={'email': B_EMAIL, 'password': B_PASSWORD})
    if status not in (200, 201) and 'exist' not in body.lower():
        sys.exit(f'建用户 B 失败: {status} {body}')

    b_token, status, body = get_token(base, B_EMAIL, B_PASSWORD)
    if not b_token:
        sys.exit(f'无法取得用户 B 的 token: {status} {body}')

    # B 的**身份**，不是他的邮箱。
    #
    # Seafile 14 把身份和邮箱拆开了：账号拿到的是
    # 0506008c...@auth.local 这样的不透明 id，邮箱降级为登录属性。共享接口和
    # 权限判定拿到的都是那个 id。这里如果继续用邮箱，共享会以
    # `{"failed":[{"error_msg":"User ... not found."}]}` **静态 200** 返回，
    # 而下面的断言会因为"B 什么都看不到"而以看不懂的方式失败。
    b_id = resolve_identity(admin, B_EMAIL)
    print(f'  用户 B 身份 = {b_id}', flush=True)

    # 库
    status, body = admin.api('/api2/repos/', method='POST',
                             form={'name': REPO_NAME})
    repo_id = (json_body(body) or {}).get('repo_id')
    if not repo_id:
        sys.exit(f'建库失败: {status} {body}')
    print(f'  repo_id = {repo_id}', flush=True)

    for folder in ('public', 'restricted', 'secret'):
        admin.api(f'/api2/repos/{repo_id}/dir/?p=/{folder}', method='POST',
                  form={'operation': 'mkdir'})

    # 放一个文件，用于验证读取与打包下载
    admin.api(f'/api2/repos/{repo_id}/dir/?p=/restricted/sub', method='POST',
              form={'operation': 'mkdir'})

    # 共享给 B（rw）——ACL 只能在此基础上收紧
    #
    # 这个接口**失败也返回 200**，把错误装在 body 的 failed 数组里。不看 body
    # 的话，整个矩阵会在一个根本没共享出去的库上跑，然后每一条都因为"B 无权限"
    # 而失败——离真因很远。第一次跑就是这么挂的。
    status, body = admin.api(f'/api2/repos/{repo_id}/dir/shared_items/?p=/',
                             method='PUT',
                             form={'share_type': 'user', 'username': b_id,
                                   'permission': 'rw'})
    failed = (json_body(body) or {}).get('failed') or []
    if status != 200 or failed:
        sys.exit(f'共享给 B 失败: {status} {body}')

    # ACL 规则
    for path, perm in (('/restricted', 'r'), ('/secret', 'invisible')):
        status, body = admin.api(
            f'/api/v2.1/cloudfile/repos/{repo_id}/dir-acl/', method='POST',
            form={'path': path, 'subject_type': 'user', 'subject': B_EMAIL,
                  'permission': perm, 'inherit': 'true'})
        if status != 200:
            sys.exit(f'下发 ACL 规则失败 ({path} -> {perm}): {status} {body}')
        print(f'  规则 {path} -> B = {perm}', flush=True)

    return repo_id, b_token


def check_rest(b, repo_id):
    entry = 'REST API'

    status, body = b.api(f'/api2/repos/{repo_id}/dir/?p=/')
    names = [e.get('name') for e in (json_body(body) or [])]
    record(entry, '/secret 不出现在目录列举中', 'secret' not in names,
           f'实际列举: {names}')
    record(entry, '/public 正常可见', 'public' in names, f'实际列举: {names}')

    status, _ = b.api(f'/api2/repos/{repo_id}/dir/?p=/restricted')
    record(entry, '/restricted 可读 (200)', status == 200, f'status={status}')

    status, _ = b.api(f'/api2/repos/{repo_id}/dir/?p=/secret')
    record(entry, '/secret 读取被拒 (403/404)', status in (403, 404),
           f'status={status}')

    status, _ = b.api(f'/api2/repos/{repo_id}/dir/?p=/restricted/new',
                      method='POST', form={'operation': 'mkdir'})
    record(entry, '/restricted 内建目录被拒', status == 403, f'status={status}')

    status, _ = b.api(f'/api2/repos/{repo_id}/dir/?p=/restricted/sub',
                      method='DELETE')
    record(entry, '/restricted 内删除被拒', status == 403, f'status={status}')

    status, _ = b.api(f'/api2/repos/{repo_id}/dir/?p=/public/ok',
                      method='POST', form={'operation': 'mkdir'})
    record(entry, '/public 内建目录允许', status in (200, 201),
           f'status={status}')


def check_upload_link(b, repo_id):
    entry = '上传/下载'

    status, body = b.api(f'/api2/repos/{repo_id}/upload-link/?p=/restricted')
    record(entry, '/restricted 取上传链接被拒', status == 403,
           f'status={status} {body[:80]}')

    status, body = b.api(f'/api2/repos/{repo_id}/upload-link/?p=/public')
    record(entry, '/public 取上传链接允许', status == 200,
           f'status={status} {body[:80]}')

    status, body = b.api(f'/api2/repos/{repo_id}/download-link/?p=/secret')
    record(entry, '/secret 取下载链接被拒', status in (403, 404),
           f'status={status} {body[:80]}')


def check_zip_download(b, repo_id):
    entry = '打包下载'
    status, body = b.api(
        '/api/v2.1/repos/%s/zip-task/?parent_dir=/&dirents=secret' % repo_id)
    record(entry, '含不可读子树的打包下载被拒', status in (403, 404),
           f'status={status} {body[:120]}')

    status, body = b.api(
        '/api/v2.1/repos/%s/zip-task/?parent_dir=/&dirents=public' % repo_id)
    record(entry, '可读目录打包下载允许', status == 200,
           f'status={status} {body[:120]}')


def check_sync(b, repo_id):
    entry = '同步客户端'
    status, body = b.api(f'/api2/repos/{repo_id}/download-info/')
    data = json_body(body) or {}
    # is_repo_syncable 为 false 时 seahub 返回 403
    blocked = status == 403 or data.get('is_syncable') is False
    record(entry, '含不可读内容的库拒绝同步', blocked,
           f'status={status} {body[:160]}')


def check_webdav(base, repo_id):
    entry = 'WebDAV'
    cred = f'{B_EMAIL}:{B_PASSWORD}'
    root = base.rstrip('/') + '/seafdav'

    status, _ = request(f'{root}/{REPO_NAME}/restricted/x.txt', method='PUT',
                        data=b'x', basic=cred)
    record(entry, '/restricted 写入被拒', status in (403, 401),
           f'status={status}')

    status, _ = request(f'{root}/{REPO_NAME}/public/x.txt', method='PUT',
                        data=b'x', basic=cred)
    record(entry, '/public 写入允许', status in (200, 201, 204),
           f'status={status}')

    # 不可见目录与只读目录的拒绝**方式应当不同**，这条断言的价值就在这个区别：
    #
    #   /restricted 存在但不可写 → 403
    #   /secret     根本不该被看见 → 404 / 409（父目录解析不到）
    #
    # 补上读侧补丁之前这里是 403，也就是说"目录不存在"和"目录存在但你不能写"
    # 用状态码就能分辨——光凭这一点就能确认 /secret 的存在。现在 seafdav 解析
    # 不到该路径，WebDAV 对"往不存在的父目录写"的标准回答就是 409。
    status, _ = request(f'{root}/{REPO_NAME}/secret/x.txt', method='PUT',
                        data=b'x', basic=cred)
    record(entry, '/secret 写入被拒且不泄露存在（404/409，非 403）',
           status in (404, 409), f'status={status}')

    # ── 读侧 ────────────────────────────────────────────────────────────
    #
    # 这几条对应 patches/seafdav/0001。写侧一直是好的（上面三条），读侧却完全
    # 没有校验：`invisible` 的目录照样被列出、照样能 GET。**一个只在部分入口
    # 生效的"不可见"不是不可见**，所以这是 ACL 的发布阻塞项，不是待办。
    propfind = {'Depth': '1', 'Content-Type': 'application/xml'}

    status, body = request(f'{root}/{REPO_NAME}/', method='PROPFIND',
                           basic=cred, headers=propfind)
    listed = status in (207, 200)
    record(entry, '库根可列举（对照）', listed, f'status={status}')
    # 没有这个对照，下面两条会在"WebDAV 整个坏掉"时一起变绿。
    record(entry, '/secret 不出现在 PROPFIND 结果中',
           listed and '/secret' not in body, f'status={status} {body[:200]}')
    record(entry, '/public 出现在 PROPFIND 结果中',
           listed and '/public' in body, f'status={status} {body[:200]}')

    status, _ = request(f'{root}/{REPO_NAME}/secret/', method='PROPFIND',
                        basic=cred, headers=propfind)
    # 404 而不是 403：不可见的目录应当与"不存在"无法区分，否则 404/403 的
    # 差异本身就泄露了它的存在。
    record(entry, '/secret 直接列举返回 404', status == 404, f'status={status}')

    status, _ = request(f'{root}/{REPO_NAME}/restricted/', method='PROPFIND',
                        basic=cred, headers=propfind)
    record(entry, '/restricted 只读仍可列举', status in (207, 200),
           f'status={status}')


def check_move(b, repo_id):
    """批量移动端点，源与目标都要校验。

    走 batch-move-item 而不是 `/dir/?p=...&operation=move`：后者只支持
    mkdir / rename / revert，请求会以 400 "operation can only be ..." 被拒，
    而 400 不是 403——断言"被拒"如果只看状态码非 200，就会被这个 400 蒙混过去，
    看起来 ACL 生效了，其实请求根本没到权限判定。第一版矩阵就是这么写的。

    FEATURES.md 第 35 项审计的也正是这七个批量端点。
    """
    entry = '移动/复制/重命名'

    def batch_move(src, dst):
        """返回 (被拒?, 成功数, 原始 body)。

        **批量端点失败时返回 200**，逐项结果装在 failed / success 数组里——
        和共享端点一个套路，这一轮已经被它坑了三次。所以这里不看状态码，
        看条目落在哪个数组、以及 error_msg 是不是权限原因：上游还有一个
        "目标是源目录或其子目录"的检查，那个也进 failed，若只看"在不在
        failed"，一个因为路径校验被拒的请求会被读成 ACL 生效。
        """
        payload = json.dumps({
            'src_repo_id': repo_id, 'dst_repo_id': repo_id,
            'paths': [{'src_path': src, 'dst_path': dst}],
        })
        _, body = b.api('/api/v2.1/repos/batch-move-item/', method='POST',
                        data=payload,
                        headers={'Content-Type': 'application/json'})
        data = json_body(body) or {}
        failed = data.get('failed') or []
        denied = any('permission' in (f.get('error_msg') or '').lower()
                     for f in failed)
        return denied, len(data.get('success') or []), body

    denied, ok_count, body = batch_move('/public/ok', '/restricted')
    record(entry, '移动到 /restricted 被拒', denied and ok_count == 0,
           f'denied={denied} success={ok_count} {body[:200]}')

    denied, ok_count, body = batch_move('/restricted/sub', '/public')
    record(entry, '从 /restricted 移出被拒', denied and ok_count == 0,
           f'denied={denied} success={ok_count} {body[:200]}')

    # 正向对照，缺了它这一组就不成立：一个对什么都说不的端点会让上面两条
    # 全绿。这一条证明 B 在可写目录里确实搬得动东西，于是上面的拒绝确实
    # 来自 ACL，而不是端点根本不工作。
    denied, ok_count, body = batch_move('/public/x.txt', '/public/ok')
    record(entry, '/public 内移动允许（对照）', ok_count == 1 and not denied,
           f'denied={denied} success={ok_count} {body[:200]}')


def check_invariant(admin, b, repo_id):
    """扩展只能收紧：CF 结果必须 ⊆ 原生权限。"""
    entry = '安全不变量'
    for path in ('/', '/public', '/restricted', '/secret'):
        status, body = admin.api(
            f'/api/v2.1/cloudfile/repos/{repo_id}/dir-acl/effective/'
            f'?path={urllib.parse.quote(path)}&user={B_EMAIL}')
        data = json_body(body) or {}
        native = data.get('native_permission')
        eff = data.get('effective_permission')

        # 先确认这个断言有东西可断。
        #
        # 少了这一条，接口报错或查错了用户时 native 与 eff 都是 None，
        # "收紧"于是平凡成立，四条全绿——而实际上什么都没验证。上一轮就是这样：
        # 规则一条都没生效，这四项却全部通过。**恒真的断言比没有断言更糟，
        # 因为它读起来像覆盖。**
        if status != 200:
            record(entry, f'{path}: 有效权限接口可用', False,
                   f'status={status} {body[:160]}')
            continue
        if native is None:
            record(entry, f'{path}: B 有原生权限可供收紧', False,
                   f'native=None——共享没生效或查的是另一个用户；'
                   f'此时"未放宽"恒真，等于没测。body={body[:160]}')
            continue

        order = {None: 0, 'invisible': 0, 'none': 0, 'r': 1, 'rw': 2}
        ok = order.get(eff, 99) <= order.get(native, 99)
        record(entry, f'{path}: {native} → {eff} 未放宽', ok,
               f'status={status} {body[:120]}')


def check_revision_revocation(admin, b, repo_id):
    """Rule writes must advance revision and invalidate live decisions now."""
    entry = '即时撤权与 revision'
    admin_endpoint = f'/api/v2.1/admin/cloudfile/repos/{repo_id}/dir-acl/'
    owner_endpoint = f'/api/v2.1/cloudfile/repos/{repo_id}/dir-acl/'

    status, body = admin.api(admin_endpoint)
    state = json_body(body) or {}
    initial_revision = state.get('revision')
    record(entry, '管理接口返回当前 revision',
           status == 200 and isinstance(initial_revision, int) and
           initial_revision >= 3,
           f'status={status} revision={initial_revision} {body[:160]}')

    query = urllib.parse.urlencode({
        'path': '/secret', 'subject_type': 'user', 'subject': B_EMAIL,
    })
    status, body = admin.api(f'{owner_endpoint}?{query}', method='DELETE')
    record(entry, '删除 invisible 规则成功', status == 200,
           f'status={status} {body[:160]}')

    status, body = admin.api(admin_endpoint)
    removed_state = json_body(body) or {}
    removed_revision = removed_state.get('revision')
    record(entry, '删除规则严格递增 revision',
           isinstance(initial_revision, int) and
           removed_revision == initial_revision + 1,
           f'before={initial_revision} after={removed_revision} {body[:160]}')

    status, body = b.api(f'/api2/repos/{repo_id}/dir/?p=/')
    names = [e.get('name') for e in (json_body(body) or [])]
    record(entry, '删除后 /secret 立即可见', status == 200 and 'secret' in names,
           f'status={status} names={names}')

    status, body = b.api(f'/api2/repos/{repo_id}/download-info/')
    data = json_body(body) or {}
    record(entry, '删除后同步立即恢复',
           status == 200 and data.get('is_syncable', True) is not False,
           f'status={status} {body[:160]}')

    status, body = admin.api(
        owner_endpoint, method='POST',
        form={'path': '/secret', 'subject_type': 'user',
              'subject': B_EMAIL, 'permission': 'invisible',
              'inherit': 'true'})
    record(entry, '重新下发 invisible 规则成功', status == 200,
           f'status={status} {body[:160]}')

    status, body = admin.api(admin_endpoint)
    restored_state = json_body(body) or {}
    restored_revision = restored_state.get('revision')
    record(entry, '重新下发严格递增 revision',
           isinstance(removed_revision, int) and
           restored_revision == removed_revision + 1,
           f'before={removed_revision} after={restored_revision} {body[:160]}')

    status, body = b.api(f'/api2/repos/{repo_id}/dir/?p=/')
    names = [e.get('name') for e in (json_body(body) or [])]
    record(entry, '重新下发后 /secret 立即隐藏',
           status == 200 and 'secret' not in names,
           f'status={status} names={names}')

    status, body = b.api(f'/api2/repos/{repo_id}/download-info/')
    data = json_body(body) or {}
    blocked = status == 403 or data.get('is_syncable') is False
    record(entry, '重新下发后同步立即拒绝', blocked,
           f'status={status} {body[:160]}')


def check_system_admin(admin, repo_id):
    """Verify the administrator recovery path for a library they do not own."""
    entry = '系统管理员 ACL'
    endpoint = f'/api/v2.1/admin/cloudfile/repos/{repo_id}/dir-acl/'
    status, body = admin.api(endpoint)
    data = json_body(body) or {}
    record(entry, '可列出整库规则',
           status == 200 and data.get('total') == 2,
           f'status={status} {body[:200]}')

    status, body = admin.api(endpoint, method='DELETE')
    record(entry, '可清空整库规则（应急出口）',
           status == 200 and (json_body(body) or {}).get('success') is True,
           f'status={status} {body[:200]}')

    status, body = admin.api(endpoint)
    data = json_body(body) or {}
    record(entry, '清空后规则数为零',
           status == 200 and data.get('total') == 0,
           f'status={status} {body[:200]}')


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

    token, status, body = get_token(base, args.admin, args.admin_password)
    if not token:
        sys.exit(f'管理员登录失败: {status} {body}')
    admin = Client(base, token)

    repo_id, b_token = setup(admin, base)
    b = Client(base, b_token)

    print('\n验收矩阵…', flush=True)
    check_rest(b, repo_id)
    check_upload_link(b, repo_id)
    check_zip_download(b, repo_id)
    check_sync(b, repo_id)
    check_webdav(base, repo_id)
    check_move(b, repo_id)
    check_invariant(admin, b, repo_id)
    check_revision_revocation(admin, b, repo_id)
    check_system_admin(admin, repo_id)

    passed = sum(1 for *_, ok, _ in results if ok)
    total = len(results)
    print(f'\n════════ {passed}/{total} 通过 ════════')

    if passed != total:
        print('\n失败项：')
        for entry, case, ok, detail in results:
            if not ok:
                print(f'  [{entry}] {case}\n      {detail}')
        sys.exit(1)


if __name__ == '__main__':
    main()
