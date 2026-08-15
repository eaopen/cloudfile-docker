#!/usr/bin/env python3
"""移动 review 门禁（P2-02）。

对照 docs/review-move-cases.json。CE 的 fileops/move 校验「来源 rw + 目标 rw」，所以
move-001/move-002 应为绿；跨空间提权、权限变化提示、循环目录、冲突策略、异步任务号
是待落地项（P2-03/P2-06），当前应为红。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import review_harness as H

B_EMAIL = 'review-move-b@example.com'
B_PASSWORD = 'ReviewMoveB9271'
REPO_NAME = 'review-move'
CASE_FILE = os.path.join('docs', 'review-move-cases.json')


def set_acl(ctx, admin_token, repo_id, path, subject, perm):
    return ctx.api(f'/api/v2.1/cloudfile/repos/{repo_id}/dir-acl/',
                   method='POST',
                   form={'path': path, 'subject_type': 'user', 'subject': subject,
                         'permission': perm, 'inherit': 'true'}, token=admin_token)


def move_item(ctx, token, src_repo, src_parent, src_name, dst_repo, dst_parent,
              dirent_type='file'):
    return H.post_json(ctx, token, f'/api2/repos/{src_repo}/fileops/move/',
                       {'src_repo_id': src_repo, 'src_parent_dir': src_parent,
                        'src_dirent_name': src_name, 'dst_repo_id': dst_repo,
                        'dst_parent_dir': dst_parent, 'operation': 'move',
                        'dirent_type': dirent_type})


def setup(ctx, admin_token):
    print('\n准备场景…', flush=True)
    b_token = H.create_user(ctx, B_EMAIL, B_PASSWORD)
    repo_id = H.create_repo(ctx, admin_token, REPO_NAME)
    b_id = H.resolve_identity(ctx, B_EMAIL)
    H.share_repo(ctx, admin_token, repo_id, b_id, 'rw')
    for folder in ('src-ro', 'dst', 'dst-ro', 'tree'):
        H.mkdir(ctx, admin_token, repo_id, folder)
    H.mkdir(ctx, admin_token, repo_id, 'tree/child')
    H.upload_file(ctx, admin_token, repo_id, '/src-ro', 'f.txt', b'ro')
    H.upload_file(ctx, admin_token, repo_id, '/tree', 'f.txt', b'move-me')
    set_acl(ctx, admin_token, repo_id, '/src-ro', B_EMAIL, 'r')
    set_acl(ctx, admin_token, repo_id, '/dst-ro', B_EMAIL, 'r')
    return {'repo_id': repo_id, 'b_token': b_token}


def build_executors(ctx, fix):
    repo_id = fix['repo_id']
    b_token = fix['b_token']

    def move_001():
        status, body = move_item(ctx, b_token, repo_id, '/src-ro', 'f.txt',
                                 repo_id, '/dst')
        ok = status not in (200, 201)
        return ok, f'source r -> move status={status} {body[:120]}'

    def move_002():
        status, body = move_item(ctx, b_token, repo_id, '/tree', 'f.txt',
                                 repo_id, '/dst-ro')
        ok = status not in (200, 201)
        return ok, f'target read-only -> move status={status} {body[:120]}'

    def move_003():
        status, body = move_item(ctx, b_token, repo_id, '/tree', 'f.txt',
                                 repo_id, '/dst')
        return False, f'cross-space elevate seam 未实现；move status={status} {body[:120]}'

    def move_004():
        status, body = move_item(ctx, b_token, repo_id, '/tree', 'f.txt',
                                 repo_id, '/dst')
        hint = (H.json_body(body) or {}).get('affected_members')
        return hint is not None, f'权限变化提示期望存在，实际 status={status} body={body[:120]}'

    def move_005():
        status, body = move_item(ctx, b_token, repo_id, '/tree', 'child',
                                 repo_id, '/tree', dirent_type='dir')
        ok = status not in (200, 201)
        return ok, f'cyclic move status={status} {body[:120]}'

    def move_006():
        status, body = move_item(ctx, b_token, repo_id, '/tree', 'f.txt',
                                 repo_id, '/dst')
        return False, f'conflict-policy seam 未实现；move status={status} {body[:120]}'

    def move_007():
        status, body = move_item(ctx, b_token, repo_id, '/tree', 'f.txt',
                                 repo_id, '/dst')
        task_id = (H.json_body(body) or {}).get('task_id')
        return bool(task_id), f'async task id 期望存在，实际 status={status} body={body[:120]}'

    return {
        'move-001': move_001, 'move-002': move_002, 'move-003': move_003,
        'move-004': move_004, 'move-005': move_005, 'move-006': move_006,
        'move-007': move_007,
    }


if __name__ == '__main__':
    sys.exit(H.matrix_main(setup, build_executors, CASE_FILE))
