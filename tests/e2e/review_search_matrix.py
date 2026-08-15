#!/usr/bin/env python3
"""搜索 review 门禁（P2-02）。

对照 docs/review-search-cases.json。CE 的 /api2/search/ 已有名称关键词匹配与
SeaSearch 索引，所以 search-001 应为绿；类型/位置/标签/创建人/更新时间筛选是待落地
项；search-007 权限裁剪与目录 ACL 联动（P2-03）。矩阵假设 SeaSearch 已由编排层起好。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import review_harness as H

B_EMAIL = 'review-search-b@example.com'
B_PASSWORD = 'ReviewSearchB9271'
REPO_NAME = 'review-search'
CASE_FILE = os.path.join('docs', 'review-search-cases.json')


def set_acl(ctx, admin_token, repo_id, path, subject, perm):
    return ctx.api(f'/api/v2.1/cloudfile/repos/{repo_id}/dir-acl/',
                   method='POST',
                   form={'path': path, 'subject_type': 'user', 'subject': subject,
                         'permission': perm, 'inherit': 'true'}, token=admin_token)


def search(ctx, token, query):
    import urllib.parse
    status, body = ctx.api(f'/api2/search/?q={urllib.parse.quote(query)}',
                           token=token)
    return status, (H.json_body(body) or {})


def setup(ctx, admin_token):
    print('\n准备场景…', flush=True)
    b_token = H.create_user(ctx, B_EMAIL, B_PASSWORD)
    repo_id = H.create_repo(ctx, admin_token, REPO_NAME)
    b_id = H.resolve_identity(ctx, B_EMAIL)
    H.share_repo(ctx, admin_token, repo_id, b_id, 'rw')
    H.mkdir(ctx, admin_token, repo_id, 'folder-alpha')
    H.mkdir(ctx, admin_token, repo_id, 'secret')
    H.upload_file(ctx, admin_token, repo_id, '/', 'alpha.txt', b'alpha')
    H.upload_file(ctx, admin_token, repo_id, '/secret', 'classified.txt', b'classified')
    set_acl(ctx, admin_token, repo_id, '/secret', B_EMAIL, 'invisible')
    return {'repo_id': repo_id, 'b_token': b_token}


def build_executors(ctx, fix):
    b_token = fix['b_token']

    def names(data):
        out = []
        for r in (data.get('results') or data.get('data') or data or []):
            if isinstance(r, dict):
                out.append(r.get('name') or r.get('fullpath') or '')
        return out

    def search_001():
        status, data = search(ctx, b_token, 'alpha')
        found = names(data)
        ok = any('alpha' in n for n in found)
        return ok, f'search alpha status={status}, names={found}'

    def search_002():
        return False, 'type-filter seam 未实现'

    def search_003():
        return False, 'location-filter seam 未实现'

    def search_004():
        return False, 'tag-filter seam 未实现'

    def search_005():
        return False, 'creator-filter seam 未实现'

    def search_006():
        return False, 'update-time-filter seam 未实现'

    def search_007():
        status, data = search(ctx, b_token, 'classified')
        found = names(data)
        leaked = any('classified' in n for n in found)
        return (not leaked), f'invisible item 应被裁剪，实际 names={found}'

    return {
        'search-001': search_001, 'search-002': search_002,
        'search-003': search_003, 'search-004': search_004,
        'search-005': search_005, 'search-006': search_006,
        'search-007': search_007,
    }


if __name__ == '__main__':
    sys.exit(H.matrix_main(setup, build_executors, CASE_FILE))
