#!/usr/bin/env python3
"""SSO 部门层级（dept 树）验收矩阵。

这是层级目录契约（eap-cloudfile cloudfile_decision_20260827.md §3）的验收门禁。
单元测试（cloudfile_ext/sso/tests/test_snapshot.py，17 项）证明**校验与排序算得
对**，本脚本证明层级快照真的落成了 ccnet 部门——parent_group_id=-1（顶级）/
>0（子级），以及 ACL 的部门祖先展开沿真树生效。

目录（static provider，同一 validate 通路，external-service 形状与之一致）：

    dept-root  总部           dept，顶级（parent_group_id=-1）
    dept-rd    研发部         dept，父=dept-root
    role-rev   评审员         group，平铺（parent_group_id=0）

成员：A 在 dept-rd；B 只在 role-rev。

断言面：
  1. 同步 ok，三组建出；
  2. dept-rd 的 parent_group_id == dept-root 的 group_id（真树，非名称前缀）；
  3. dept-root 的 parent_group_id == -1（顶级部门标记）；
  4. role-rev 的 parent_group_id == 0（普通群组，无部门语义）；
  5. revision 幂等：同一快照再同步一次，applied 全 0（不重建、不重复加人）；
  6. ACL 祖先继承（端到端）：dept-root 上挂一条 r 规则 → dept-rd 成员 A 的
     有效权限被该规则收紧（证明 _load_subjects 沿真 parent_group_id 展开祖先）。

阶段 2（目录变平）：dept-rd 改挂 dept-root 之外的父 → 快照拒绝整份、保留旧树。
这测的是"非法层级不半落地"，需要改 .env 重启，由 verify-local.sh 的
cap_sso_dept_run 编排，本脚本只做单阶段断言。

    python3 sso_dept_matrix.py --url https://127.0.0.1 --insecure \
        --admin me@example.com --admin-password xxx [--acl]
"""

import argparse
import json
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

#: 由 --insecure 设置。与 sso_matrix.py 同一种做法。
_SSL_CONTEXT = None

A_EMAIL = 'dept-matrix-a@example.com'
A_PASSWORD = 'DeptMatrix-A-6318'

ROOT = 'dept-root'
ROOT_NAME = '部门矩阵-总部'
RD = 'dept-rd'
RD_NAME = '部门矩阵-研发部'
ROLE = 'role-rev'
ROLE_NAME = '部门矩阵-评审员'

results = []


def record(area, case, ok, detail=''):
    results.append((area, case, ok, detail))
    mark = '✓' if ok else '✗'
    line = f'  {mark} [{area}] {case}'
    if detail and not ok:
        line += f'\n      {detail}'
    print(line, flush=True)


def request(url, method='GET', token=None, data=None, form=None, headers=None):
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


def get_token(base, email, password):
    status, body = request(base + '/api2/auth-token/', method='POST',
                           form={'username': email, 'password': password})
    return (json_body(body) or {}).get('token'), status, body


def ensure_user(admin, base, email, password):
    status, body = admin.api('/api/v2.1/admin/users/', method='POST',
                             form={'email': email, 'password': password})
    if status not in (200, 201) and 'exist' not in body.lower():
        sys.exit(f'建用户 {email} 失败: {status} {body}')
    token, status, body = get_token(base, email, password)
    if not token:
        sys.exit(f'无法取得 {email} 的 token: {status} {body}')
    return token


def mappings(admin):
    status, body = admin.api('/api/v2.1/admin/cloudfile/sso/group-map/')
    data = json_body(body) or {}
    return ({m['external_id']: m for m in data.get('mappings', [])},
            status, body)


def run_sync(admin):
    status, body = admin.api('/api/v2.1/admin/cloudfile/sso/sync/',
                             method='POST')
    return status, json_body(body) or {}, body


def group_detail(admin, group_id):
    """GET /api/v2.1/groups/{id}/ —— 带 parent_group_id 的组详情。"""
    status, body = admin.api(f'/api/v2.1/groups/{group_id}/')
    return json_body(body), status, body


def check_enabled(admin):
    status, body = admin.api('/api/v2.1/cloudfile/features/')
    data = json_body(body) or {}
    record('前置', 'CF_ENABLE_SSO 确实为 true',
           data.get('features', {}).get('CF_ENABLE_SSO') is True,
           f'status={status} {body[:200]}')
    record('前置', 'CF_ENABLE_DIR_ACL 已开启（ACL 继承断言需要）',
           data.get('features', {}).get('CF_ENABLE_DIR_ACL') is True,
           f'features={data.get("features")}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--url', required=True)
    ap.add_argument('--admin', required=True)
    ap.add_argument('--admin-password', required=True)
    ap.add_argument('--insecure', action='store_true')
    ap.add_argument('--acl', action='store_true',
                    help='跑 ACL 祖先继承断言（需建库，默认开）')
    ap.set_defaults(acl=True)
    args = ap.parse_args()

    global _SSL_CONTEXT
    if args.insecure:
        _SSL_CONTEXT = ssl._create_unverified_context()

    base = args.url.rstrip('/')
    admin_token, status, body = get_token(base, args.admin, args.admin_password)
    if not admin_token:
        sys.exit(f'管理员登录失败: {status} {body}')
    admin = Client(base, admin_token)

    print('\n部门层级矩阵…', flush=True)
    check_enabled(admin)
    ensure_user(admin, base, A_EMAIL, A_PASSWORD)

    # -- 同步与幂等 --------------------------------------------------------
    status, result, raw = run_sync(admin)
    record('同步', '层级快照同步成功',
           status == 200 and result.get('status') == 'ok',
           f'status={status} {raw[:300]}')

    mapped, status, raw = mappings(admin)
    record('映射', 'root/rd/role 三组都建出',
           {ROOT, RD, ROLE} <= set(mapped),
           f'status={status} mapped={sorted(mapped)}')

    status, result, raw = run_sync(admin)
    applied = (json_body(result.get('detail') or '{}') or {}).get('applied', {})
    record('同步', 'revision 幂等：重同步零改动',
           status == 200 and result.get('status') == 'ok'
           and sum(applied.values()) == 0,
           f'applied={applied} raw={raw[:300]}')

    # -- ccnet 真树形状 ----------------------------------------------------
    root_gid = mapped.get(ROOT, {}).get('group_id')
    rd_gid = mapped.get(RD, {}).get('group_id')
    role_gid = mapped.get(ROLE, {}).get('group_id')

    rd_detail, status, raw = group_detail(admin, rd_gid) if rd_gid else ({}, 0, '')
    record('层级', 'dept-rd.parent_group_id == dept-root 的 group_id',
           rd_detail.get('parent_group_id') == root_gid,
           f'status={status} parent={rd_detail.get("parent_group_id")} '
           f'root_gid={root_gid} {raw[:200]}')

    root_detail, status, raw = (group_detail(admin, root_gid)
                                if root_gid else ({}, 0, ''))
    record('层级', 'dept-root.parent_group_id == -1（顶级部门标记）',
           root_detail.get('parent_group_id') == -1,
           f'status={status} parent={root_detail.get("parent_group_id")} {raw[:200]}')

    role_detail, status, raw = (group_detail(admin, role_gid)
                                if role_gid else ({}, 0, ''))
    record('层级', 'role-rev.parent_group_id == 0（普通群组无部门语义）',
           role_detail.get('parent_group_id') == 0,
           f'status={status} parent={role_detail.get("parent_group_id")} {raw[:200]}')

    # -- ACL 祖先继承（端到端）---------------------------------------------
    if args.acl and root_gid is not None:
        check_ancestor_inheritance(admin, base, mapped)

    failed = [r for r in results if not r[2]]
    print(f'\n{"✗" if failed else "✓"} 部门层级矩阵：'
          f'{len(results) - len(failed)}/{len(results)} 通过', flush=True)
    if failed:
        for area, case, _, detail in failed:
            print(f'  失败 [{area}] {case}\n    {detail}', file=sys.stderr)
        sys.exit(1)


def check_ancestor_inheritance(admin, base, mapped):
    """父部门规则覆盖子部门成员——沿真 parent_group_id，不是名称前缀。

    做法：建一个库并给 A 库级 rw（个人共享），然后在 dept-root（A 不直接属于
    它，A 属于子部门 dept-rd）挂一条 r 规则。A 的 effective 必须被收紧为 r。
    空跑这个断言的话，"部门祖先展开"只存在于单元测试里。
    """
    status, body = admin.api('/api/v2.1/admin/libraries/', method='POST',
                             form={'name': 'dept-matrix-repo'})
    repo = (json_body(body) or {}).get('id')
    if not repo:
        record('ACL 继承', '建库成功', False, f'status={status} {body[:200]}')
        return

    # 前提：A 的 native 是 rw。库 owner 是 admin，A 需要个人共享 rw
    # （AdminShares user 类型，share_to 走 form 多值）。
    status, body = admin.api('/api/v2.1/admin/shares/', method='POST',
                             form={'repo_id': repo, 'path': '/',
                                   'share_type': 'user',
                                   'share_to': A_EMAIL,
                                   'permission': 'rw'})
    record('ACL 继承', 'A 获得库级个人共享 rw（native 前提）',
           status == 200 and A_EMAIL not in (body or ''),
           f'status={status} {body[:200]}')

    root_gid = mapped[ROOT]['group_id']
    # 规则挂在父部门 dept-root 上；body 平铺 JSON（path 在 body，非 query），
    # subject 为 group id 十进制串（acl-semantics §1）。
    status, body = admin.api(
        f'/api/v2.1/cloudfile/repos/{repo}/dir-acl/',
        method='POST',
        data=json.dumps({'path': '/',
                         'subject_type': 'dept',
                         'subject': str(root_gid),
                         'permission': 'r',
                         'inherit': True}).encode(),
        headers={'Content-Type': 'application/json'})
    record('ACL 继承', 'dept-root 上挂 r 规则成功', status in (200, 201),
           f'status={status} {body[:200]}')

    # A 的有效权限：个人 rw + 祖先 dept r → 收紧为 r。
    # 查他人权限是 admin 级披露，用 admin token + user 参数（apis.py 语义）。
    status, body = request(
        base + f'/api/v2.1/cloudfile/repos/{repo}/dir-acl/effective/'
               f'?path=/&user={urllib.parse.quote(A_EMAIL)}',
        token=admin.token)
    effective = (json_body(body) or {}).get('effective_permission')
    record('ACL 继承', '子部门成员被父部门 r 规则收紧（rw→r）',
           effective == 'r',
           f'status={status} effective={effective} {body[:300]}')

    # 清理：删规则（DELETE 参数走 query string）、删库，矩阵可重跑
    admin.api(f'/api/v2.1/cloudfile/repos/{repo}/dir-acl/'
              f'?path=/&subject_type=dept&subject={root_gid}',
              method='DELETE')
    admin.api(f'/api/v2.1/admin/libraries/{repo}/', method='DELETE')


if __name__ == '__main__':
    main()
