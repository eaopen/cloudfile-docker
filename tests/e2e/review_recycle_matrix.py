#!/usr/bin/env python3
"""回收站 review 门禁（P2-02）。

对照 docs/review-recycle-cases.json。CE 的 repo-trash 允许普通用户查看自己的回收站，
所以 recycle-002（普通用户拒绝）应为红；管理员列举/恢复/删除与软删除是 CE 原生，
recycle-003/recycle-004 应为绿。
"""

import os
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import review_harness as H

B_EMAIL = 'review-recycle-b@example.com'
B_PASSWORD = 'ReviewRecycleB9271'
REPO_NAME = 'review-recycle'
CASE_FILE = os.path.join('docs', 'review-recycle-cases.json')


def setup(ctx, admin_token):
    print('\n准备场景…', flush=True)
    b_token = H.create_user(ctx, B_EMAIL, B_PASSWORD)
    repo_id = H.create_repo(ctx, admin_token, REPO_NAME)
    b_id = H.resolve_identity(ctx, B_EMAIL)
    H.share_repo(ctx, admin_token, repo_id, b_id, 'rw')
    H.upload_file(ctx, admin_token, repo_id, '/', 'gone.txt', b'x')
    status, body = ctx.api(f'/api2/repos/{repo_id}/file/?p=/gone.txt',
                           method='DELETE', token=admin_token)
    print(f'  删除 gone.txt status={status}', flush=True)
    return {'repo_id': repo_id, 'b_token': b_token, 'admin_token': admin_token}


def build_executors(ctx, fix):
    repo_id = fix['repo_id']
    b_token = fix['b_token']
    admin_token = fix['admin_token']

    def trash(token):
        status, body = ctx.api(f'/api2/repos/{repo_id}/trash/?path=/', token=token)
        data = H.json_body(body) or {}
        return status, data

    def recycle_002():
        status, data = trash(b_token)
        entries = data.get('data') or data.get('items') or data or []
        leaked = any((e.get('obj_name') or e.get('name')) == 'gone.txt'
                     for e in entries if isinstance(e, dict))
        # 评审要求普通用户不可见；CE 允许查看自己的回收站，故这里「无泄漏」才算绿
        return (not leaked), f'普通用户 trash status={status}, entries={entries}'

    def recycle_003():
        status, data = trash(admin_token)
        entries = data.get('data') or data.get('items') or data or []
        has = any((e.get('obj_name') or e.get('name')) == 'gone.txt'
                  for e in entries if isinstance(e, dict))
        return has, f'admin trash status={status}, entries={entries}'

    def recycle_004():
        status, data = trash(admin_token)
        entries = data.get('data') or data.get('items') or data or []
        has = any((e.get('obj_name') or e.get('name')) == 'gone.txt'
                  for e in entries if isinstance(e, dict))
        return has, f'soft delete 可恢复性：status={status}, entries={entries}'

    return {'recycle-002': recycle_002, 'recycle-003': recycle_003,
            'recycle-004': recycle_004}


if __name__ == '__main__':
    sys.exit(H.matrix_main(setup, build_executors, CASE_FILE))
