#!/usr/bin/env python3
"""外部分享 review 门禁（P2-02）。

对照 docs/review-share-cases.json。评审要求外部分享通过功能开关关闭并隐藏入口。CE
本身没有这个开关，所以 share-002（创建被拒）/share-004（旧链接不得绕过）应为红；
share-003（接口与历史数据保留）对应 CE 原生 share-link 列表端点，应为绿。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import review_harness as H

B_EMAIL = 'review-share-b@example.com'
B_PASSWORD = 'ReviewShareB9271'
REPO_NAME = 'review-share'
CASE_FILE = os.path.join('docs', 'review-share-cases.json')


def setup(ctx, admin_token):
    print('\n准备场景…', flush=True)
    b_token = H.create_user(ctx, B_EMAIL, B_PASSWORD)
    repo_id = H.create_repo(ctx, admin_token, REPO_NAME)
    b_id = H.resolve_identity(ctx, B_EMAIL)
    H.share_repo(ctx, admin_token, repo_id, b_id, 'rw')
    H.upload_file(ctx, admin_token, repo_id, '/', 'f.txt', b'x')
    return {'repo_id': repo_id, 'b_token': b_token, 'admin_token': admin_token}


def build_executors(ctx, fix):
    repo_id = fix['repo_id']
    b_token = fix['b_token']
    admin_token = fix['admin_token']

    def share_002():
        status, body = ctx.api('/api/v2.1/share-links/', method='POST',
                               form={'repo_id': repo_id, 'path': '/f.txt'},
                               token=b_token)
        return status in (401, 403, 404), \
            f'创建外链应被拒（开关开启时非管理员）status={status} {body[:120]}'

    def share_003():
        status, body = ctx.api(f'/api2/repos/{repo_id}/file/shared-link/?path=/f.txt',
                               token=admin_token)
        return status == 200, f'share-link 列表端点保留 status={status} {body[:120]}'

    def share_004():
        # 管理员仍可创建（用于管理），但开关开启时匿名访问旧链接必须被拒。
        status, body = ctx.api('/api/v2.1/share-links/', method='POST',
                               form={'repo_id': repo_id, 'path': '/f.txt'},
                               token=admin_token)
        data = H.json_body(body) or {}
        link = data.get('link') or ''
        if status not in (200, 201) or not link:
            return False, f'管理员建链失败 status={status} {body[:120]}'
        anon_status, anon_body = H.request(link)
        ok = anon_status in (401, 403, 404) and 'gone' not in anon_body
        return ok, f'匿名访问旧链接 status={anon_status}（期望 403/404）'

    return {'share-002': share_002, 'share-003': share_003,
            'share-004': share_004}


if __name__ == '__main__':
    sys.exit(H.matrix_main(setup, build_executors, CASE_FILE))
