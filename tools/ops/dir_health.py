#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SSO 目录同步健康报表：哪些组被 quarantine、各自缺哪些人的账号、账号覆盖率、
以及**成员关系审计**（Seafile 里存在、但按当前口径不该有的成员是谁、为什么留着）。

为什么单独做成脚本（而不是 hub 的管理命令）：
  · 覆盖率类指标需要**同时**读 etech 组织库与 CloudFile 库，hub 侧只能看到快照、看不到 etech 用户表；
  · 现状下改 hub 要重建镜像，而本脚本只要有 DB 可达即可运行，故障排查时更实用。

口径来源（改这里之前先看这几处，避免与线上逻辑漂移）：
  · 部门成员 = etech `org_relation` 中 `type_ in ('groupUser','groupUserRole')` 且 `status_ = 1`
    —— CloudDirectorySnapshotService#fillMembers（**只给直接成员，不展开祖先**）
  · 角色成员 = `userRole` 直挂 ∪ 本人部门被 `roleGroup` 绑定的成员
    —— CloudDirectorySnapshotService#roleEntries / groupsForUser
  · 解析键 = `seahub_db.profile_profile` 的 `login_id` ∪ `contact_email`
    —— Seahub Profile.objects.convert_login_str_to_username（先 login_id 再 contact_email）
  · 某组只要有 1 个成员解析不出 → quarantine（整组不做"移除"）—— cloudfile_ext/sso/service.py::_resolve_members
  · 待移除集 = current − wanted − protected，仅对**未隔离**组执行 —— cloudfile_ext/sso/reconcile.py::build
      current   = ccnet GroupUser 现任成员（service.py::_current_state）
      wanted    = 该组可解析的直接成员（同上口径）
      protected = 组主 Group.creator_name（永不移除）
  · **祖先加人**之所以存在：eap 的 groupsForUser 曾返回"直接部门 + 全部祖先部门"，
    登录刷新把用户加进了每个祖先组；而全量快照只给直接成员 → 两边口径不一致。
    2026-09-20 已把 groupsForUser 改为只返回直接部门（祖先继承由 C 层
    ccnet_group_manager_get_groups_by_user(return_ancestors=TRUE) 沿 GroupStructure 展开，
    权限不依赖祖先组的成员行）。本审计把"祖先加人"单独归类，避免与真滞留混在一起。

用法：
  python3 dir_health.py \
      --etech-host 10.9.8.162 --etech-user etech   --etech-pass '***' --etech-db etech-db \
      --cf-host    10.12.1.157 --cf-user seafile   --cf-pass    '***'
  # 也可走环境变量：ETECH_DB_HOST/PORT/USER/PASS/NAME、CF_DB_HOST/PORT/USER/PASS
  常用开关：--detail（逐组列缺失账号） --json --limit N --group 2001 --fail-on-quarantine
           --fail-on-stale（有真滞留时退出码 1，接巡检用）
"""
import argparse
import json
import os
import sys

try:
    import pymysql
except ImportError:
    sys.exit('缺少依赖：pip install pymysql')

EMAIL_SUFFIX = '@shanghai-electric.com'
ROLE_PREFIX = 'role:'

# 成员关系审计的分类。处置方式不同，不要合并：
#   祖先加人  —— 合法历史形态，移除不影响权限（C 层展开祖先）；已停止新增
#   其余三类  —— 都属"该收回没收回"，随账号覆盖率提高会开始出现
KIND_ANCESTOR = '祖先加人（C 层会展开，权限不丢）'
KIND_ROLE_STALE = '角色成员已撤销但未移除'
KIND_DEPT_STALE = '真滞留：已离开该部门子树'
KIND_JUNK = '历史脏数据（非账号形态）'
KIND_ANOMALY = '直接成员却不在列表（异常）'
STALE_KINDS = (KIND_ROLE_STALE, KIND_DEPT_STALE, KIND_ANOMALY)


def conn(host, port, user, password, name=None, charset='utf8mb4'):
    return pymysql.connect(host=host, port=int(port), user=user,
                           password=password, database=name, charset=charset)


def load_resolvable_keys(cf):
    """Seafile 侧"能解析出账号"的键集合 + 键→Seafile 用户名 + 用户名→工号。

    返回 (keys, accounts, key2user, user2acct)：
      keys       —— login_id ∪ contact_email 的小写集合（判"能否解析"）
      accounts   —— 已存在的 Seafile username 集合
      key2user   —— 小写键 → Seafile username（与 convert_login_str_to_username 同向）
      user2acct  —— Seafile username → etech 工号（审计时反查是谁）
    """
    cur = cf.cursor()
    cur.execute("SELECT user, login_id, contact_email FROM seahub_db.profile_profile")
    keys, accounts, key2user, user2acct = set(), set(), {}, {}
    for user, login_id, email in cur.fetchall():
        accounts.add(user)
        for k in (login_id, email):
            if k and k.strip():
                kk = k.strip().lower()
                keys.add(kk)
                key2user.setdefault(kk, user)
        if email and email.strip():
            user2acct[user] = email.strip().split('@')[0]
        elif login_id and login_id.strip():
            user2acct[user] = login_id.strip()
    return keys, accounts, key2user, user2acct


def user_to_username(acct, key2user):
    """etech 工号 → Seafile username（先试 {工号}@域，再试 login_id）。解析不出返回 None。"""
    if not acct:
        return None
    return (key2user.get((acct + EMAIL_SUFFIX).lower())
            or key2user.get(acct.strip().lower()))


def load_snapshot_inputs(etech):
    """按快照口径取出：每个 etech 组的成员账号 + 用户资料 + 部门父链。

    返回 (groups, users, dept_members, role_direct, role_dept, parent)；
    parent 是 {组id: 父组id}（已剥掉自环与 '0'），供审计判"某组是不是某人部门的祖先"。
    """
    cur = etech.cursor()
    cur.execute("SELECT id_, name_, active, parent_id_ FROM `%s`.org_group" % ARGS.etech_db)
    groups, parent = {}, {}
    for gid, name, active, pid in cur.fetchall():
        groups[gid] = (name or '', active)
        if pid and pid != gid and pid != '0':
            parent[gid] = pid
    cur.execute("SELECT id_, account_, fullname_, status_ FROM `%s`.org_user" % ARGS.etech_db)
    users = {uid: (acct or '', name or '', st) for uid, acct, name, st in cur.fetchall()}

    cur.execute("SELECT user_id_, group_id_, role_id_, type_ FROM `%s`.org_relation "
                "WHERE status_ = 1" % ARGS.etech_db)
    dept_members, role_direct, role_dept = {}, {}, {}
    for uid, gid, rid, typ in cur.fetchall():
        if typ in ('groupUser', 'groupUserRole') and gid:
            dept_members.setdefault(gid, set()).add(uid)
        elif typ == 'userRole' and rid:
            role_direct.setdefault(rid, set()).add(uid)
        elif typ == 'roleGroup' and rid and gid:
            role_dept.setdefault(rid, set()).add(gid)
    return groups, users, dept_members, role_direct, role_dept, parent


def ancestors_of(gid, parent, guard=64):
    """沿 parent_id_ 上溯，返回 gid 的全部祖先组 id。"""
    out, cur, n = set(), parent.get(gid), 0
    while cur and n < guard:
        out.add(cur)
        cur, n = parent.get(cur), n + 1
    return out


def load_cf_members(cf):
    """CloudFile 侧现状：{group_id: {username}} 与 {group_id: 组主}。"""
    cur = cf.cursor()
    cur.execute("SELECT group_id, user_name FROM ccnet_db.GroupUser")
    members = {}
    for gid, uname in cur.fetchall():
        members.setdefault(gid, set()).add(uname)
    cur.execute("SELECT group_id, creator_name FROM ccnet_db.`Group`")
    creators = {gid: c for gid, c in cur.fetchall()}
    return members, creators


def audit_memberships(mapped, members, creators, key2user, user2acct, users,
                      dept_members, role_direct, role_dept, parent, quarantined_ids):
    """审计 current − wanted − protected：Seafile 里"多出来"的成员关系是谁、为什么。

    分类（不合并，因为处置方式完全不同）：
      祖先加人                 —— 合法的历史形态；移除它**不影响权限**（C 层自己展开祖先），
                                  且 2026-09-20 起登录刷新不再产生新的这类行
      角色成员已撤销但未移除    —— 真滞留（角色组无层级，与祖先无关）
      真滞留：已离开该部门子树  —— 换部门/离职未被收回，正是 quarantine 要挡住的场景
      历史脏数据（非账号形态）  —— 旧版代码写入的邮箱形式成员串，任何同步都处理不掉，需人工清
      直接成员却不在列表（异常）—— 不该发生；出现即口径有 bug
    """
    acct2uid = {(a or ''): uid for uid, (a, _n, _s) in users.items() if a}
    unknown = ('', '(未在 etech 组织库中)', None)
    res = {'total': 0, 'groups': 0, 'frozen': 0, 'live': 0, 'kinds': {}, 'rows': []}
    for ext, gid, stype in mapped:
        cur_m = members.get(gid)
        if not cur_m:
            continue
        prot = {creators.get(gid)} if creators.get(gid) else set()
        wanted = set()
        for uid in members_of(ext, stype, dept_members, role_direct, role_dept):
            uname = user_to_username(users.get(uid, ('', '', 0))[0], key2user)
            if uname:
                wanted.add(uname)
        extra = cur_m - wanted - prot
        if not extra:
            continue
        res['groups'] += 1
        frozen = ext in quarantined_ids
        for uname in sorted(extra):
            uid = acct2uid.get(user2acct.get(uname, '')) or None
            if uid is None:
                kind, depts = KIND_JUNK, []
            else:
                depts = sorted(g for g, us in dept_members.items() if uid in us)
                if stype != 'dept':
                    kind = KIND_ROLE_STALE
                elif ext in depts:
                    kind = KIND_ANOMALY
                elif any(ext in ancestors_of(d, parent) for d in depts):
                    kind = KIND_ANCESTOR
                else:
                    kind = KIND_DEPT_STALE
            res['total'] += 1
            res['frozen' if frozen else 'live'] += 1
            res['kinds'][kind] = res['kinds'].get(kind, 0) + 1
            res['rows'].append({
                'external_id': ext, 'cf_group_id': gid, 'subject_type': stype,
                'username': uname,
                'account': users.get(uid, unknown)[0] if uid else None,
                'etech_status': users.get(uid, unknown)[2] if uid else None,
                'kind': kind, 'quarantined': frozen,
            })
    return res


def members_of(ext_id, stype, dept_members, role_direct, role_dept):
    if stype == 'dept':
        return set(dept_members.get(ext_id, set()))
    rid = ext_id[len(ROLE_PREFIX):] if ext_id.startswith(ROLE_PREFIX) else ext_id
    uids = set(role_direct.get(rid, set()))
    for dept in role_dept.get(rid, set()):
        uids |= dept_members.get(dept, set())
    return uids


def main():
    cf = conn(ARGS.cf_host, ARGS.cf_port, ARGS.cf_user, ARGS.cf_pass)
    etech = conn(ARGS.etech_host, ARGS.etech_port, ARGS.etech_user, ARGS.etech_pass,
                 name=ARGS.etech_db)

    resolvable, _cf_accounts, key2user, user2acct = load_resolvable_keys(cf)
    groups, users, dept_members, role_direct, role_dept, parent = load_snapshot_inputs(etech)

    ccur = cf.cursor()
    ccur.execute("SELECT external_id, group_id, subject_type FROM seafile_db.cf_sso_group_map")
    mapped = [(ext, gid, st) for ext, gid, st in ccur.fetchall()]

    ccur.execute("SELECT group_id, group_name FROM ccnet_db.`Group`")
    cf_group_names = {gid: name for gid, name in ccur.fetchall()}

    quarantined, involved, covered = [], set(), 0
    for ext, gid, stype in mapped:
        if ARGS.group and ext != ARGS.group:
            continue
        uids = members_of(ext, stype, dept_members, role_direct, role_dept)
        bad = []
        for uid in uids:
            acct, name, ustatus = users.get(uid, ('', '', 0))
            involved.add(uid)
            key = (acct + EMAIL_SUFFIX) if acct else ''
            if not key or key.lower() not in resolvable:
                bad.append({'account': acct, 'name': name, 'etech_status': ustatus})
        if bad:
            quarantined.append({
                'external_id': ext,
                'cf_group_id': gid,
                'cf_group_name': cf_group_names.get(gid) or ext,
                'etech_group_name': groups.get(ext, ('', None))[0],
                'subject_type': stype,
                'member_count': len(uids),
                'missing_count': len(bad),
                'missing': bad,
            })
    quarantined_ids = {q['external_id'] for q in quarantined}
    for uid in involved:
        acct = users.get(uid, ('', '', 0))[0]
        if acct and (acct + EMAIL_SUFFIX).lower() in resolvable:
            covered += 1

    cf_members, cf_creators = load_cf_members(cf)
    audit = audit_memberships([m for m in mapped if not ARGS.group or m[0] == ARGS.group],
                              cf_members, cf_creators, key2user, user2acct, users,
                              dept_members, role_direct, role_dept, parent, quarantined_ids)

    dept_total = sum(1 for _, _, st in mapped if st == 'dept')
    role_total = sum(1 for _, _, st in mapped if st != 'dept')
    dept_q = sum(1 for q in quarantined if q['subject_type'] == 'dept')
    role_q = len(quarantined) - dept_q
    report = {
        'managed_groups': len(mapped),
        'managed_dept': dept_total,
        'managed_role': role_total,
        'quarantined_groups': len(quarantined),
        'quarantined_dept': dept_q,
        'quarantined_role': role_q,
        'cf_accounts': len(_cf_accounts),
        'etech_accounts_in_dept_relations': len(involved),
        'covered_accounts': covered,
        'coverage_percent': round(100.0 * covered / len(involved), 1) if involved else None,
        'quarantined': quarantined,
        'membership_audit': audit,
    }

    if ARGS.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    else:
        p = print
        p('=' * 78)
        p('SSO 目录同步健康报表')
        p('=' * 78)
        p('受管组            : %d（部门 %d / 角色 %d）'
          % (report['managed_groups'], dept_total, role_total))
        p('处于 quarantine   : %d（部门 %d = %.0f%% / 角色 %d = %.0f%%）'
          % (len(quarantined), dept_q, 100.0 * dept_q / max(1, dept_total),
             role_q, 100.0 * role_q / max(1, role_total)))
        p('CloudFile 账号    : %d' % report['cf_accounts'])
        p('etech 涉及账号    : %d（已覆盖 %d = %.1f%%）'
          % (len(involved), covered, report['coverage_percent'] or 0.0))
        p('')
        if quarantined:
            p('⚠️ 被隔离的组**不会执行成员移除**（只加不减）：换科室/离职都不会被收回权限。')
            p('   根因：组内成员的登录名解析不到 CloudFile 账号（账号首次 OAuth 登录才创建）。')
            p('')
            rows = quarantined if ARGS.limit <= 0 else quarantined[:ARGS.limit]
            p('%-6s %-6s %-22s %-22s %6s %6s' %
              ('组ID', '类型', 'CloudFile 组名', 'etech 组名', '成员', '缺账号'))
            for q in sorted(rows, key=lambda x: -x['missing_count']):
                p('%-6s %-6s %-22s %-22s %6d %6d'
                  % (q['cf_group_id'], q['subject_type'],
                     q['cf_group_name'][:20], q['etech_group_name'][:20],
                     q['member_count'], q['missing_count']))
            if ARGS.limit > 0 and len(quarantined) > ARGS.limit:
                p('...（共 %d 个，已按缺失人数降序显示前 %d 个；--limit 0 显示全部）'
                  % (len(quarantined), ARGS.limit))
        if ARGS.detail:
            p('')
            p('=' * 78)
            p('逐组明细（缺失账号）')
            p('=' * 78)
            for q in sorted(quarantined, key=lambda x: -x['missing_count']):
                p('· group_id=%s %s（%s）缺 %d / %d：'
                  % (q['cf_group_id'], q['cf_group_name'], q['subject_type'],
                     q['missing_count'], q['member_count']))
                for m in q['missing'][:50]:
                    p('    %-12s %-10s etech状态=%s'
                      % (m['account'] or '(空)', m['name'], m['etech_status']))
                if len(q['missing']) > 50:
                    p('    ...（还有 %d 人）' % (len(q['missing']) - 50))

        p('')
        p('=' * 78)
        p('成员关系审计（Seafile 里存在、但按当前口径不该有的成员）')
        p('=' * 78)
        p('  待移除合计      : %d 条，涉及 %d 个组' % (audit['total'], audit['groups']))
        p('    隔离组冻结    : %d（解除隔离后才会执行）' % audit['frozen'])
        p('    未隔离组会执行: %d' % audit['live'])
        if audit['kinds']:
            p('  分类：')
            for k, n in sorted(audit['kinds'].items(), key=lambda x: -x[1]):
                p('    %-34s %d' % (k, n))
            stale = sum(n for k, n in audit['kinds'].items() if k in STALE_KINDS)
            p('')
            p('  说明：祖先加人是合法的历史形态 —— 它的权限由 C 层')
            p('        ccnet_group_manager_get_groups_by_user(return_ancestors=TRUE)')
            p('        沿 GroupStructure 展开，移除成员行不影响权限；')
            p('        2026-09-20 起登录刷新已不再产生这类行。')
            p('        需要收回的（角色已撤销 / 已离开部门子树）当前 %d 条。' % stale)
        else:
            p('  （无）')
        if ARGS.detail and audit['rows']:
            p('')
            by_kind = {}
            for r in audit['rows']:
                by_kind.setdefault(r['kind'], []).append(r)
            for kind, rows in sorted(by_kind.items(), key=lambda x: -len(x[1])):
                p('· %s（%d 条）' % (kind, len(rows)))
                for r in rows[:ARGS.limit if ARGS.limit > 0 else len(rows)]:
                    p('    group_id=%-6s ext=%-22s %-42s 工号=%-10s etech=%s%s'
                      % (r['cf_group_id'], r['external_id'][:22], r['username'][:42],
                         r['account'] or '-', r['etech_status'],
                         '  [隔离中]' if r['quarantined'] else ''))
                if 0 < ARGS.limit < len(rows):
                    p('    ...（还有 %d 条）' % (len(rows) - ARGS.limit))

    cf.close()
    etech.close()
    if ARGS.fail_on_quarantine and quarantined:
        return 1
    if ARGS.fail_on_stale and any(audit['kinds'].get(k) for k in STALE_KINDS):
        return 1
    return 0


def parse_args():
    ap = argparse.ArgumentParser(description='SSO 目录同步健康报表')
    ap.add_argument('--etech-host', default=os.getenv('ETECH_DB_HOST'))
    ap.add_argument('--etech-port', default=os.getenv('ETECH_DB_PORT', '3306'))
    ap.add_argument('--etech-user', default=os.getenv('ETECH_DB_USER', 'etech'))
    ap.add_argument('--etech-pass', default=os.getenv('ETECH_DB_PASS'))
    ap.add_argument('--etech-db', default=os.getenv('ETECH_DB_NAME', 'etech-db'))
    ap.add_argument('--cf-host', default=os.getenv('CF_DB_HOST'))
    ap.add_argument('--cf-port', default=os.getenv('CF_DB_PORT', '8036'))
    ap.add_argument('--cf-user', default=os.getenv('CF_DB_USER', 'seafile'))
    ap.add_argument('--cf-pass', default=os.getenv('CF_DB_PASS'))
    ap.add_argument('--detail', action='store_true', help='逐组列出缺失账号')
    ap.add_argument('--json', action='store_true', help='输出 JSON')
    ap.add_argument('--limit', type=int, default=30,
                    help='清单最多显示多少行；0 = 全部（默认 30）')
    ap.add_argument('--group', default=None, help='只看某个 external_id')
    ap.add_argument('--fail-on-quarantine', action='store_true',
                    help='存在被隔离的组时以退出码 1 结束（接 CI/巡检用）')
    ap.add_argument('--fail-on-stale', action='store_true',
                    help='存在"真滞留"（已离开部门子树却还在组里）时以退出码 1 结束')
    a = ap.parse_args()
    for req in ('etech_host', 'etech_pass', 'cf_host', 'cf_pass'):
        if not getattr(a, req):
            ap.error('缺少参数 --%s（或用对应环境变量）' % req.replace('_', '-'))
    return a


ARGS = parse_args()

if __name__ == '__main__':
    try:
        sys.exit(main())
    except pymysql.err.OperationalError as exc:
        sys.exit('连接数据库失败：%s' % exc)
