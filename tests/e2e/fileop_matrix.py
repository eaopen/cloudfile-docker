#!/usr/bin/env python3
"""写入生命周期扩展点验收矩阵。

这是 P0.5 的整机门禁，也是它**唯一还没满足的退出条件**：

    "锁 provider 尚未实现时，假 provider 已能在所有写入口统一 veto"

单元级证据已经有了——C 144 项、Go 6 项跨语言契约、50 个调用点的类型检查、
9 个变异全部被捕获。**那些都不能证明运行时真的在每个入口被调用到。**
目录 ACL 已经把这一课上过一遍：62 项 C 检查和 87 项 Python 检查全绿，而存进去的
规则永远匹配不上，接口还返回 200；缺陷只在把栈起起来、拿另一个用户的 token 去敲
每个入口时才显形（FEATURES.md 第 71 项）。所以这份脚本只做一件事：
**证明 seam 真的在每条写路径上。**

被测对象是 `common/cf-fileop-test.c` 这个假 provider（`CF_FILEOP_TEST_PROVIDER`
开启时注册），它把每个事件写进一行 journal，并拒绝任何路径里含有标记组件的操作。

分两个阶段，中间要改 .env 并重启：

    阶段 1  标记为空 —— 全部放行，只记 journal
            → 建出后面要用的夹具（含一个名字就是标记的目录和文件）
            → 断言每个入口都产生了事实，且成功一次只产生一个
    阶段 2  标记为 cf-refuse —— 逐入口断言拒绝
            → 断言拒绝的操作产生零个 COMMITTED
            → 反向对照：未标记路径上同样的操作仍然成功

两个阶段缺一不可，而且不是为了凑数：

  * **夹具只能在阶段 1 建。** 拒绝一开，创建标记路径本身就被拒——那恰好是
    被测操作之一。
  * **反向对照只有跑在同一个栈上才有意义。** 一个把所有写入都拒掉的 provider
    会让"每个入口都拒绝"平凡成立，而那证明的是服务坏了，不是 seam 通了。
  * **重启这一步本身就是被测对象。** 配置是每次启动重写的
    （`write_cloudfile_config`），改了 .env 却不生效是这套部署踩过的坑。

只用标准库。

    python3 fileop_matrix.py --phase 1 --url https://127.0.0.1 --insecure \\
        --admin me@example.com --admin-password xxx \\
        --journal deploy/compose/data/seafile/cf-fileop-journal.log
"""

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

#: 由 --insecure 设置。与 smoke.py / acl_matrix.py 保持同一种做法。
_SSL_CONTEXT = None

#: 阶段 2 里被拒绝的那个路径组件。必须与 CF_FILEOP_TEST_REFUSE_TOKEN 一致。
TOKEN = 'cf-refuse'

REPO_NAME = 'cf-fileop-matrix'

#: 阶段之间要传递 repo_id 和基线 journal 行数，放文件里。与 search_matrix.py
#: 的 --state-file 同一做法：矩阵自己不碰容器，状态由编排层带过来。
DEFAULT_STATE = 'fileop-matrix-state.json'

results = []


def record(area, case, ok, detail=''):
    results.append((area, case, ok, detail))
    mark = '✓' if ok else '✗'
    line = f'  {mark} [{area}] {case}'
    if detail and not ok:
        line += f'\n      {detail}'
    print(line, flush=True)


def request(url, method='GET', token=None, data=None, form=None, basic=None,
            headers=None, raw=False):
    hdrs = dict(headers or {})
    body = None
    if token:
        hdrs['Authorization'] = f'Token {token}'
    if basic:
        hdrs['Authorization'] = 'Basic ' + base64.b64encode(basic.encode()).decode()
    if form is not None:
        body = urllib.parse.urlencode(form).encode()
        hdrs['Content-Type'] = 'application/x-www-form-urlencoded'
    elif data is not None:
        body = data if isinstance(data, bytes) else data.encode()

    req = urllib.request.Request(url, data=body, method=method, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=120,
                                    context=_SSL_CONTEXT) as resp:
            payload = resp.read()
            return resp.status, payload if raw else payload.decode(errors='replace')
    except urllib.error.HTTPError as e:
        payload = e.read()
        return e.code, payload if raw else payload.decode(errors='replace')
    except Exception as e:
        return 0, str(e)


def jbody(body):
    try:
        return json.loads(body)
    except Exception:
        return None


def multipart(fields, filename, content):
    """手工拼 multipart，避免为一个上传引入 requests 依赖。"""
    boundary = '----CloudFileFileop' + uuid.uuid4().hex
    out = []
    for k, v in fields.items():
        out.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n')
    out.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
        f'filename="{filename}"\r\nContent-Type: application/octet-stream\r\n\r\n')
    body = ''.join(out).encode() + content + f'\r\n--{boundary}--\r\n'.encode()
    return body, f'multipart/form-data; boundary={boundary}'


def wait_ready(base, timeout):
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


# ── journal ──────────────────────────────────────────────────────────────
#
# 一行一个事件，字段固定顺序、空值写 "-"：
#   <phase> <op> <repo_id> <subjects> <sources> <user> <commit_id>
# 格式与 common/cf-fileop-test.c 的 journal() 对应。

class Journal:
    """journal 的一段视图。

    每次断言前重新读整个文件、并只看某个偏移之后的行——增量而不是全量，
    因为"这次操作产生了什么"和"到目前为止一共产生了什么"是两个不同的问题，
    而只有前者能证明事实的唯一性。
    """

    def __init__(self, path):
        self.path = path

    def lines(self, since=0):
        if not os.path.exists(self.path):
            return []
        with open(self.path, encoding='utf-8', errors='replace') as fp:
            return [l.rstrip('\n') for l in fp][since:]

    def count(self):
        return len(self.lines())

    def events(self, since=0):
        out = []
        for line in self.lines(since):
            parts = line.split(' ')
            if len(parts) != 7:
                continue
            out.append({
                'phase': parts[0], 'op': parts[1], 'repo_id': parts[2],
                'subjects': parts[3].split(',') if parts[3] != '-' else [],
                'sources': parts[4].split(',') if parts[4] != '-' else [],
                'user': parts[5], 'commit_id': parts[6],
            })
        return out

    def wait_for(self, since, phase, op, timeout=20):
        """等到 (phase, op) 出现。

        提交后事实是同步发出的，但上传要经 Go fileserver 再回一趟 RPC，而
        HTTP 响应可能先到。轮询而不是 sleep 一个固定值：固定值要么太短
        （偶发失败，看起来像 seam 没接上）要么太长（每条断言都在等）。
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            hits = [e for e in self.events(since)
                    if e['phase'] == phase and e['op'] == op]
            if hits:
                return hits
            time.sleep(0.5)
        return []


class Client:
    def __init__(self, base, token=None):
        self.base = base.rstrip('/')
        self.token = token

    def api(self, path, method='GET', **kw):
        return request(self.base + path, method=method, token=self.token, **kw)


def upload(client, base, repo_id, parent_dir, filename, content, replace=False):
    """经 Go fileserver 上传。返回 (status, body)。"""
    status, body = client.api(
        f'/api2/repos/{repo_id}/upload-link/?p={urllib.parse.quote(parent_dir)}')
    url = (body or '').strip('"')
    if status != 200 or not url.startswith('http'):
        return 0, f'取上传链接失败 status={status} {body[:160]}'
    data, ctype = multipart(
        {'parent_dir': parent_dir, 'replace': '1' if replace else '0'},
        filename, content)
    return request(url, method='POST', data=data, token=client.token,
                   headers={'Content-Type': ctype})


def update(client, base, repo_id, path, content):
    """经 Go fileserver 覆盖已存在的文件。"""
    status, body = client.api(f'/api2/repos/{repo_id}/update-link/?p=/')
    url = (body or '').strip('"')
    if status != 200 or not url.startswith('http'):
        return 0, f'取更新链接失败 status={status} {body[:160]}'
    data, ctype = multipart({'target_file': path}, os.path.basename(path),
                            content)
    return request(url, method='POST', data=data, token=client.token,
                   headers={'Content-Type': ctype})


# ── 前置 ────────────────────────────────────────────────────────────────

def check_provider(journal, expect_token):
    """假 provider 真的装上了。

    全绿但 provider 其实没注册的矩阵毫无意义，而且失败完全静默——这正是
    verify-local.sh 会先断言开关为 true 的同一个理由。这里断言的是更强的东西：
    journal 文件存在，说明 provider 不只是配置写对了，而是真的被调用过。
    """
    exists = os.path.exists(journal.path)
    record('前置', 'journal 文件存在（provider 已注册并被调用过）', exists,
           f'{journal.path} 不存在——检查 CF_FILEOP_TEST_PROVIDER 与容器内路径')
    if exists:
        record('前置', f'标记为 {expect_token!r}' if expect_token else '标记为空',
               True)
    return exists


# ── 阶段 1：观察模式 ─────────────────────────────────────────────────────

def phase_one(admin, base, journal, state_path):
    repo_name = f'{REPO_NAME}-{uuid.uuid4().hex[:8]}'
    status, body = admin.api('/api2/repos/', method='POST',
                             form={'name': repo_name})
    repo_id = (jbody(body) or {}).get('repo_id')
    if not repo_id:
        sys.exit(f'建库失败: {status} {body}')
    print(f'  库 {repo_id}', flush=True)

    def since():
        return journal.count()

    def expect(area, case, op, mark, want_subject=None, want_source=None):
        """断言恰好一个 COMMITTED，op 正确，且带上了 commit_id。"""
        hits = journal.wait_for(mark, 'COMMITTED', op)
        if len(hits) != 1:
            record(area, case, False,
                   f'期望恰好 1 个 COMMITTED {op}，实际 {len(hits)} 个')
            return None
        e = hits[0]
        detail = f'subjects={e["subjects"]} commit={e["commit_id"]}'
        ok = e['repo_id'] == repo_id and e['commit_id'] != '-'
        if want_subject is not None:
            ok = ok and want_subject in e['subjects']
        if want_source is not None:
            ok = ok and want_source in e['sources']
        record(area, case, ok, detail)
        return e

    # -- mkdir（C：post_dir）
    mark = since()
    status, body = admin.api(f'/api2/repos/{repo_id}/dir/?p=/box',
                             method='POST', form={'operation': 'mkdir'})
    record('REST', '建目录成功', status in (200, 201),
           f'status={status} {body[:120]}')
    expect('REST', 'mkdir 产生恰好一个事实', 'mkdir', mark, '/box')

    # -- 空文件（C：post_empty_file）
    mark = since()
    status, body = admin.api(f'/api2/repos/{repo_id}/file/?p=/box/empty.txt',
                             method='POST', form={'operation': 'create'})
    record('REST', '建空文件成功', status in (200, 201),
           f'status={status} {body[:120]}')
    expect('REST', 'create-file 产生恰好一个事实', 'create-file', mark,
           '/box/empty.txt')

    # -- 上传（Go：postFilesAndGenCommit）
    mark = since()
    status, body = upload(admin, base, repo_id, '/box', 'up.dat', b'one\n')
    record('Go 上传', '上传成功', status == 200, f'status={status} {body[:160]}')
    expect('Go 上传', 'create-file 产生恰好一个事实', 'create-file', mark,
           '/box/up.dat')

    # -- 覆盖（Go：putFile）
    mark = since()
    status, body = update(admin, base, repo_id, '/box/up.dat', b'two\n')
    record('Go 更新', '覆盖成功', status == 200, f'status={status} {body[:160]}')
    expect('Go 更新', 'update-file 产生恰好一个事实', 'update-file', mark,
           '/box/up.dat')

    # -- 内容不变的覆盖：没有提交，所以没有事实，只有 abort
    mark = since()
    status, body = update(admin, base, repo_id, '/box/up.dat', b'two\n')
    record('Go 更新', '内容相同的覆盖仍返回成功', status == 200,
           f'status={status} {body[:160]}')
    same = journal.wait_for(mark, 'ABORTED', 'update-file')
    committed = [e for e in journal.events(mark)
                 if e['phase'] == 'COMMITTED' and e['op'] == 'update-file']
    record('Go 更新', '内容相同 → 零个 COMMITTED、一个 ABORTED',
           len(committed) == 0 and len(same) == 1,
           f'COMMITTED={len(committed)} ABORTED={len(same)}')

    # -- 重命名（C：rename_file）
    mark = since()
    status, body = admin.api(f'/api2/repos/{repo_id}/file/?p=/box/empty.txt',
                             method='POST',
                             form={'operation': 'rename',
                                   'newname': 'renamed.txt'})
    record('REST', '重命名成功', status in (200, 201),
           f'status={status} {body[:120]}')
    expect('REST', 'rename 产生恰好一个事实且带源路径', 'rename', mark,
           '/box/renamed.txt', '/box/empty.txt')

    # -- 批量删除（C：batch_del_files），一次操作一个事实、携带多条路径
    mark = since()
    for name in ('d1.txt', 'd2.txt'):
        admin.api(f'/api2/repos/{repo_id}/file/?p=/box/{name}',
                  method='POST', form={'operation': 'create'})
    mark = since()
    status, body = admin.api(
        f'/api/v2.1/repos/{repo_id}/batch-delete-item/', method='DELETE',
        data=json.dumps({'parent_dir': '/box',
                         'dirents': ['d1.txt', 'd2.txt']}),
        headers={'Content-Type': 'application/json'})
    record('REST', '批量删除成功', status == 200, f'status={status} {body[:160]}')
    hits = journal.wait_for(mark, 'COMMITTED', 'delete')
    record('REST', '批量删除是一个事实、携带两条路径',
           len(hits) == 1 and len(hits[0]['subjects']) == 2,
           f'事实数={len(hits)} '
           f'paths={hits[0]["subjects"] if hits else None}')

    # -- WebDAV 写：继承 C 的 seam，不需要自己的补丁
    cred = f'{ADMIN_EMAIL}:{ADMIN_PASSWORD}'
    dav = f'{base}/seafdav/{urllib.parse.quote(repo_name)}/box/dav.txt'
    mark = since()
    status, body = request(dav, method='PUT', data=b'dav\n', basic=cred)
    record('WebDAV', 'PUT 成功', status in (200, 201, 204),
           f'status={status} {body[:160]}')
    expect('WebDAV', 'PUT 经 C 产生 create-file 事实', 'create-file', mark,
           '/box/dav.txt')

    # -- 阶段 2 的夹具：一个名字就是标记的目录和文件。
    #    只有现在能建——拒绝一开，建它本身就会被拒。
    mark = since()
    status, body = admin.api(f'/api2/repos/{repo_id}/dir/?p=/{TOKEN}',
                             method='POST', form={'operation': 'mkdir'})
    record('夹具', f'建标记目录 /{TOKEN}', status in (200, 201),
           f'status={status} {body[:120]}')
    status, body = upload(admin, base, repo_id, f'/{TOKEN}', 'inside.dat',
                          b'inside\n')
    record('夹具', f'/{TOKEN}/inside.dat', status == 200,
           f'status={status} {body[:160]}')
    status, body = upload(admin, base, repo_id, '/box', f'{TOKEN}', b'marked\n')
    record('夹具', f'/box/{TOKEN}（文件名就是标记）', status == 200,
           f'status={status} {body[:160]}')
    status, body = upload(admin, base, repo_id, '/box', 'plain.dat', b'plain\n')
    record('夹具', '/box/plain.dat（反向对照用）', status == 200,
           f'status={status} {body[:160]}')

    # -- 恒真断言的防线：journal 真的在增长。
    #    如果 provider 压根没被调用，上面每一条 expect 都会以"0 个事实"失败，
    #    但这一条让原因一眼可见，而不是十条下游症状。
    record('前置', 'journal 在阶段 1 里确实增长了', journal.count() > 0,
           f'总行数={journal.count()}')

    with open(state_path, 'w', encoding='utf-8') as fp:
        json.dump({'repo_id': repo_id, 'repo_name': repo_name,
                   'journal_lines': journal.count()}, fp)
    print(f'  状态已写入 {state_path}', flush=True)


# ── 阶段 2：拒绝模式 ─────────────────────────────────────────────────────

def phase_two(admin, base, journal, state_path):
    with open(state_path, encoding='utf-8') as fp:
        state = json.load(fp)
    repo_id = state['repo_id']
    repo_name = state['repo_name']
    print(f'  库 {repo_id}', flush=True)

    def refused(area, case, status, body, want=(403, 423, 500),
                forbid_500=True):
        """拒绝到达了客户端，而且不是以 500 的形式。

        forbid_500 是这条断言的重点。上游 CE 的锁接口就是这么坏的：
        `check_file_lock` 恒返回 false，随后调用不存在的 `seafile_api.lock_file`
        抛 AttributeError，只捕获 SearpcError，于是普通 rw 用户就能触发 500
        （FEATURES.md 待办第 6 条）。一个被吞成 500 的拒绝对用户是"服务坏了"，
        对监控是噪声，对排查毫无信息。
        """
        ok = status in want
        if forbid_500 and status == 500:
            ok = False
        record(area, case, ok, f'status={status} {body[:200]}')
        return ok

    def no_fact(area, case, mark, op):
        hits = [e for e in journal.events(mark)
                if e['phase'] == 'COMMITTED' and e['op'] == op]
        record(area, case, len(hits) == 0,
               f'期望零个 COMMITTED {op}，实际 {len(hits)} 个')

    mark = journal.count()

    # -- Go 上传进标记目录
    status, body = upload(admin, base, repo_id, f'/{TOKEN}', 'nope.dat',
                          b'nope\n')
    refused('Go 上传', '上传进标记目录被拒', status, body)
    no_fact('Go 上传', '被拒的上传零事实', mark, 'create-file')

    # -- Go 更新标记文件
    mark = journal.count()
    status, body = update(admin, base, repo_id, f'/box/{TOKEN}', b'nope\n')
    refused('Go 更新', '覆盖标记文件被拒', status, body)
    no_fact('Go 更新', '被拒的覆盖零事实', mark, 'update-file')

    # -- REST 建空文件
    mark = journal.count()
    status, body = admin.api(
        f'/api2/repos/{repo_id}/file/?p=/{TOKEN}/nope.txt', method='POST',
        form={'operation': 'create'})
    refused('REST', '在标记目录里建文件被拒', status, body)
    no_fact('REST', '被拒的建文件零事实', mark, 'create-file')

    # -- REST mkdir
    mark = journal.count()
    status, body = admin.api(f'/api2/repos/{repo_id}/dir/?p=/{TOKEN}/sub',
                             method='POST', form={'operation': 'mkdir'})
    refused('REST', '在标记目录里建子目录被拒', status, body)
    no_fact('REST', '被拒的 mkdir 零事实', mark, 'mkdir')

    # -- REST rename
    mark = journal.count()
    status, body = admin.api(f'/api2/repos/{repo_id}/file/?p=/box/{TOKEN}',
                             method='POST',
                             form={'operation': 'rename',
                                   'newname': 'escaped.dat'})
    refused('REST', '重命名标记文件被拒', status, body)
    no_fact('REST', '被拒的 rename 零事实', mark, 'rename')

    # -- REST 删除
    mark = journal.count()
    status, body = admin.api(
        f'/api/v2.1/repos/{repo_id}/batch-delete-item/', method='DELETE',
        data=json.dumps({'parent_dir': '/box', 'dirents': [TOKEN]}),
        headers={'Content-Type': 'application/json'})
    # 批量端点失败时返回 200，逐项结果在 failed 里——这一轮被这个套路坑过三次。
    data = jbody(body) or {}
    failed = data.get('failed') or []
    record('REST', '删除标记文件被拒',
           status != 200 or bool(failed),
           f'status={status} failed={failed} {body[:160]}')
    no_fact('REST', '被拒的删除零事实', mark, 'delete')

    # -- REST 移动（源在标记路径上：移动写的是两端）
    mark = journal.count()
    status, body = admin.api(
        f'/api/v2.1/repos/{repo_id}/batch-move-item/', method='POST',
        data=json.dumps({'src_repo_id': repo_id, 'src_parent_dir': '/box',
                         'src_dirents': [TOKEN],
                         'dst_repo_id': repo_id, 'dst_parent_dir': '/'}),
        headers={'Content-Type': 'application/json'})
    data = jbody(body) or {}
    failed = data.get('failed') or []
    record('REST', '移动标记文件被拒（源侧锁也要拦）',
           status != 200 or bool(failed),
           f'status={status} failed={failed} {body[:160]}')
    no_fact('REST', '被拒的移动零事实', mark, 'move')

    # -- WebDAV：拒绝要传导到客户端，且不能是 500
    cred = f'{ADMIN_EMAIL}:{ADMIN_PASSWORD}'
    mark = journal.count()
    dav = f'{base}/seafdav/{urllib.parse.quote(repo_name)}/{TOKEN}/nope.txt'
    status, body = request(dav, method='PUT', data=b'nope\n', basic=cred)
    refused('WebDAV', 'PUT 进标记目录被拒且不是 500', status, body,
            want=(403, 409, 423, 502))
    no_fact('WebDAV', '被拒的 PUT 零事实', mark, 'create-file')

    # -- 反向对照。没有这一组，上面全部平凡成立：一个把所有写入都拒掉的
    #    provider（或者一个坏掉的服务）会让每条断言都绿。
    mark = journal.count()
    status, body = upload(admin, base, repo_id, '/box', 'still-ok.dat',
                          b'ok\n')
    record('对照', '未标记路径上传仍然成功', status == 200,
           f'status={status} {body[:160]}')
    hits = journal.wait_for(mark, 'COMMITTED', 'create-file')
    record('对照', '成功的上传仍然产生事实', len(hits) == 1,
           f'事实数={len(hits)}')

    mark = journal.count()
    status, body = update(admin, base, repo_id, '/box/plain.dat', b'changed\n')
    record('对照', '未标记文件覆盖仍然成功', status == 200,
           f'status={status} {body[:160]}')
    hits = journal.wait_for(mark, 'COMMITTED', 'update-file')
    record('对照', '成功的覆盖仍然产生事实', len(hits) == 1,
           f'事实数={len(hits)}')

    # -- 每条 PREPARE 拒绝都该带着能解释原因的消息。契约第六节：
    #    不解释原因的拒绝会变成一张没有可用信息的支持工单。
    prepares = [e for e in journal.events(0) if e['phase'] == 'PREPARE']
    record('契约', 'PREPARE 事件确实产生了', len(prepares) > 0,
           f'PREPARE 事件数={len(prepares)}')


ADMIN_EMAIL = ''
ADMIN_PASSWORD = ''


def main():
    global ADMIN_EMAIL, ADMIN_PASSWORD

    ap = argparse.ArgumentParser()
    ap.add_argument('--phase', type=int, choices=(1, 2), required=True)
    ap.add_argument('--url', required=True)
    ap.add_argument('--admin', required=True)
    ap.add_argument('--admin-password', required=True)
    ap.add_argument('--journal', required=True,
                    help='宿主机上 journal 文件的路径（容器里的 '
                         'CF_FILEOP_TEST_JOURNAL 经卷映射出来）')
    ap.add_argument('--state-file', default=DEFAULT_STATE)
    ap.add_argument('--timeout', type=int, default=600)
    ap.add_argument('--insecure', action='store_true',
                    help='接受自签证书。CADDY_TLS=internal 时必需。')
    args = ap.parse_args()

    if args.insecure:
        import ssl
        global _SSL_CONTEXT
        _SSL_CONTEXT = ssl._create_unverified_context()

    base = args.url.rstrip('/')
    ADMIN_EMAIL = args.admin
    ADMIN_PASSWORD = args.admin_password

    if not wait_ready(base, args.timeout):
        sys.exit('服务未就绪')

    status, body = request(base + '/api2/auth-token/', method='POST',
                           form={'username': args.admin,
                                 'password': args.admin_password})
    token = (jbody(body) or {}).get('token')
    if not token:
        sys.exit(f'管理员登录失败: {status} {body}')
    admin = Client(base, token)

    journal = Journal(args.journal)

    print(f'\n阶段 {args.phase}…', flush=True)
    if args.phase == 1:
        # 阶段 1 的 journal 可能还不存在：provider 刚注册、还没有任何写入。
        # 所以这里不作前置断言，改在阶段末尾断言它增长了。
        phase_one(admin, base, journal, args.state_file)
    else:
        check_provider(journal, TOKEN)
        phase_two(admin, base, journal, args.state_file)

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
