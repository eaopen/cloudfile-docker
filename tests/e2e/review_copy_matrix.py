#!/usr/bin/env python3
"""复制 review 门禁（P2-02）。

对照 docs/review-copy-cases.json。CE 的 fileops/copy 已经校验「来源可读 + 目标可写」
（copy_move_task.py），所以 copy-001/copy-002 应为绿；同名冲突 / 大小 / 层级 / 配额 /
异步任务号这些 review 要求是待落地项（P2-03+），当前应为红。权限否定场景用目录 ACL
（CF_ENABLE_DIR_ACL）把来源/目标对用户 B 收紧。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import review_harness as H

B_EMAIL = 'review-copy-b@example.com'
B_PASSWORD = 'ReviewCopyB9271'
REPO_NAME = 'review-copy'
CASE_FILE = os.path.join('docs', 'review-copy-cases.json')


def set_acl(ctx, admin_token, repo_id, path, subject, perm):
    return ctx.api(f'/api/v2.1/cloudfile/repos/{repo_id}/dir-acl/',
                   method='POST',
                   form={'path': path, 'subject_type': 'user', 'subject': subject,
                         'permission': perm, 'inherit': 'true'}, token=admin_token)


def copy_item(ctx, token, src_repo, src_parent, src_name, dst_repo, dst_parent,
              dirent_type='file'):
    return H.post_json(ctx, token, f'/api2/repos/{src_repo}/fileops/copy/',
                       {'src_repo_id': src_repo, 'src_parent_dir': src_parent,
                        'src_dirent_name': src_name, 'dst_repo_id': dst_repo,
                        'dst_parent_dir': dst_parent, 'operation': 'copy',
                        'dirent_type': dirent_type})


def list_dir(ctx, token, repo_id, path):
    import urllib.parse
    status, body = ctx.api(
        f'/api2/repos/{repo_id}/dir/?p={urllib.parse.quote(path)}', token=token)
    return [e.get('name') for e in (H.json_body(body) or [])]


def setup(ctx, admin_token):
    print('\n准备场景…', flush=True)
    b_token = H.create_user(ctx, B_EMAIL, B_PASSWORD)
    repo_id = H.create_repo(ctx, admin_token, REPO_NAME)
    b_id = H.resolve_identity(ctx, B_EMAIL)
    H.share_repo(ctx, admin_token, repo_id, b_id, 'rw')
    for folder in ('src', 'src-secret', 'dst', 'dst-ro'):
        H.mkdir(ctx, admin_token, repo_id, folder)
    H.upload_file(ctx, admin_token, repo_id, '/src', 'f.txt', b'src-content')
    H.upload_file(ctx, admin_token, repo_id, '/src-secret', 'f.txt', b'secret')
    H.upload_file(ctx, admin_token, repo_id, '/dst', 'f.txt', b'existing')
    set_acl(ctx, admin_token, repo_id, '/src-secret', B_EMAIL, 'none')
    set_acl(ctx, admin_token, repo_id, '/dst-ro', B_EMAIL, 'r')
    return {'repo_id': repo_id, 'b_token': b_token}


def build_executors(ctx, fix):
    repo_id = fix['repo_id']
    b_token = fix['b_token']

    def copy_001():
        status, body = copy_item(ctx, b_token, repo_id, '/src-secret', 'f.txt',
                                 repo_id, '/dst')
        ok = status not in (200, 201)
        return ok, f'source none -> copy status={status} {body[:120]}'

    def copy_002():
        status, body = copy_item(ctx, b_token, repo_id, '/src', 'f.txt',
                                 repo_id, '/dst-ro')
        ok = status not in (200, 201)
        return ok, f'target read-only -> copy status={status} {body[:120]}'

    def copy_003():
        status, body = copy_item(ctx, b_token, repo_id, '/src', 'f.txt',
                                 repo_id, '/dst')
        names = list_dir(ctx, b_token, repo_id, '/dst')
        overwritten = status in (200, 201) and set(names) == {'f.txt'}
        return (not overwritten), f'conflict copy status={status}, dst names={names}'

    def copy_004():
        status, body = copy_item(ctx, b_token, repo_id, '/src', 'f.txt',
                                 repo_id, '/dst')
        return False, f'size-limit seam 未实现；copy status={status} {body[:120]}'

    def copy_005():
        status, body = copy_item(ctx, b_token, repo_id, '/src', 'f.txt',
                                 repo_id, '/dst')
        return False, f'depth-limit seam 未实现；copy status={status} {body[:120]}'

    def copy_006():
        status, body = copy_item(ctx, b_token, repo_id, '/src', 'f.txt',
                                 repo_id, '/dst')
        return False, f'quota seam 未实现；copy status={status} {body[:120]}'

    def copy_007():
        status, body = copy_item(ctx, b_token, repo_id, '/src', 'f.txt',
                                 repo_id, '/dst')
        task_id = (H.json_body(body) or {}).get('task_id')
        return bool(task_id), f'async task id 期望存在，实际 status={status} body={body[:120]}'

    return {
        'copy-001': copy_001, 'copy-002': copy_002, 'copy-003': copy_003,
        'copy-004': copy_004, 'copy-005': copy_005, 'copy-006': copy_006,
        'copy-007': copy_007,
    }


if __name__ == '__main__':
    sys.exit(H.matrix_main(setup, build_executors, CASE_FILE))
