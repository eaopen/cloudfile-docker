#!/usr/bin/env python3
"""移动 review 门禁（P2-02 → P2-06）。

对照 docs/review-move-cases.json。P2-06 在开启 CF_ENABLE_FILEOPS 时把 fileops/move
影子成统一预检查：来源写/目标写用目录 ACL 收紧；跨 owner 移动要求源库 admin；移动前
返回 affected_members（权限继承变化）；循环/退化移动 400；同名冲突默认 rename；
task_id 幂等去重。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import review_harness as H

B_EMAIL = 'review-move-b@example.com'
B_PASSWORD = 'ReviewMoveB9271'
C_EMAIL = 'review-move-c@example.com'
C_PASSWORD = 'ReviewMoveC9271'
REPO_NAME = 'review-move'
CASE_FILE = os.path.join('docs', 'review-move-cases.json')


def set_acl(ctx, admin_token, repo_id, path, subject, perm):
    return ctx.api(f'/api/v2.1/cloudfile/repos/{repo_id}/dir-acl/',
                   method='POST',
                   form={'path': path, 'subject_type': 'user', 'subject': subject,
                         'permission': perm, 'inherit': 'true'}, token=admin_token)


def move_item(ctx, token, src_repo, src_parent, src_name, dst_repo, dst_parent,
              dirent_type='file', preview=False):
    payload = {'src_repo_id': src_repo, 'src_parent_dir': src_parent,
               'src_dirent_name': src_name, 'dst_repo_id': dst_repo,
               'dst_parent_dir': dst_parent, 'operation': 'move',
               'dirent_type': dirent_type}
    if preview:
        payload['preview'] = True
    return H.post_json(ctx, token, f'/api2/repos/{src_repo}/fileops/move/',
                       payload)


def list_dir(ctx, token, repo_id, path):
    import urllib.parse
    status, body = ctx.api(
        f'/api2/repos/{repo_id}/dir/?p={urllib.parse.quote(path)}', token=token)
    return [e.get('name') for e in (H.json_body(body) or [])]


def setup(ctx, admin_token):
    print('\n准备场景…', flush=True)
    b_token = H.create_user(ctx, B_EMAIL, B_PASSWORD)
    c_token = H.create_user(ctx, C_EMAIL, C_PASSWORD)
    repo_id = H.create_repo(ctx, admin_token, REPO_NAME)
    b_id = H.resolve_identity(ctx, B_EMAIL)
    c_id = H.resolve_identity(ctx, C_EMAIL)
    H.share_repo(ctx, admin_token, repo_id, b_id, 'rw')
    H.share_repo(ctx, admin_token, repo_id, c_id, 'rw')
    for folder in ('src-ro', 'dst', 'dst-ro', 'tree'):
        H.mkdir(ctx, admin_token, repo_id, folder)
    H.mkdir(ctx, admin_token, repo_id, 'tree/child')
    for name, content in (('f.txt', b'f'), ('g.txt', b'g'), ('h.txt', b'h'),
                          ('m2.txt', b'm2'), ('m3.txt', b'm3')):
        H.upload_file(ctx, admin_token, repo_id, '/tree', name, content)
    H.upload_file(ctx, admin_token, repo_id, '/src-ro', 'f.txt', b'ro')
    H.upload_file(ctx, admin_token, repo_id, '/dst', 'g.txt', b'existing')
    set_acl(ctx, admin_token, repo_id, '/src-ro', B_EMAIL, 'r')
    set_acl(ctx, admin_token, repo_id, '/dst-ro', B_EMAIL, 'r')
    # C can read /tree but not /dst: moving a /tree item into /dst costs C
    # access, which is exactly what move-004 counts.
    set_acl(ctx, admin_token, repo_id, '/dst', C_EMAIL, 'none')

    # Cross-space fixture: B owns a second library; moving out of admin's
    # library into it is a cross-owner move that needs source admin.
    b_repo_id = H.create_repo(ctx, b_token, 'review-move-b')

    return {'repo_id': repo_id, 'b_repo_id': b_repo_id, 'b_token': b_token}


def build_executors(ctx, fix):
    repo_id = fix['repo_id']
    b_token = fix['b_token']

    def move_001():
        status, body = move_item(ctx, b_token, repo_id, '/src-ro', 'f.txt',
                                 repo_id, '/dst')
        ok = status == 403
        return ok, f'source r -> move status={status} {body[:120]}'

    def move_002():
        status, body = move_item(ctx, b_token, repo_id, '/tree', 'm2.txt',
                                 repo_id, '/dst-ro')
        ok = status == 403
        return ok, f'target read-only -> move status={status} {body[:120]}'

    def move_003():
        status, body = move_item(ctx, b_token, repo_id, '/tree', 'm3.txt',
                                 fix['b_repo_id'], '/')
        ok = status == 403
        return ok, f'cross-space move status={status} {body[:120]}'

    def move_004():
        status, body = move_item(ctx, b_token, repo_id, '/tree', 'f.txt',
                                 repo_id, '/dst')
        hint = (H.json_body(body) or {}).get('affected_members')
        ok = isinstance(hint, int) and hint >= 1
        return ok, f'权限变化提示 affected_members={hint!r} status={status} {body[:120]}'

    def move_005():
        status, body = move_item(ctx, b_token, repo_id, '/tree', 'child',
                                 repo_id, '/tree', dirent_type='dir')
        ok = status == 400
        return ok, f'cyclic move status={status} {body[:120]}'

    def move_006():
        status, body = move_item(ctx, b_token, repo_id, '/tree', 'g.txt',
                                 repo_id, '/dst')
        names = list_dir(ctx, b_token, repo_id, '/dst')
        overwritten = status in (200, 201) and set(names) == {'g.txt'}
        return (not overwritten), f'conflict move status={status}, dst names={names}'

    def move_007():
        status, body = move_item(ctx, b_token, repo_id, '/tree', 'h.txt',
                                 repo_id, '/dst')
        first = (H.json_body(body) or {}).get('task_id')
        status2, body2 = move_item(ctx, b_token, repo_id, '/tree', 'h.txt',
                                   repo_id, '/dst')
        second = (H.json_body(body2) or {}).get('task_id')
        count = list_dir(ctx, b_token, repo_id, '/dst').count('h.txt')
        ok = bool(first) and first == second and count <= 1
        return ok, (f'idempotency status={status}/{status2} '
                    f'task_id={first}/{second} h.txt count={count}')

    def move_008():
        # Preview must report the permission-impact without moving the file.
        # m3.txt is still in /tree at this point (move-003 got a 403).
        status, body = move_item(ctx, b_token, repo_id, '/tree', 'm3.txt',
                                 repo_id, '/dst', preview=True)
        hint = (H.json_body(body) or {}).get('affected_members')
        still_at_src = 'm3.txt' in list_dir(ctx, b_token, repo_id, '/tree')
        not_in_dst = 'm3.txt' not in list_dir(ctx, b_token, repo_id, '/dst')
        ok = (status == 200 and isinstance(hint, int) and hint >= 1
              and still_at_src and not_in_dst)
        return ok, (f'preview affected_members={hint!r} status={status} '
                    f'仍留在源目录={still_at_src} 未落到目标={not_in_dst}')

    return {
        'move-001': move_001, 'move-002': move_002, 'move-003': move_003,
        'move-004': move_004, 'move-005': move_005, 'move-006': move_006,
        'move-007': move_007, 'move-008': move_008,
    }


if __name__ == '__main__':
    sys.exit(H.matrix_main(setup, build_executors, CASE_FILE))
