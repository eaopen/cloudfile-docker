#!/usr/bin/env python3
"""标签 review 门禁（P2-02）。

对照 docs/review-tags-cases.json。CE 的 repo-tags 已有「创建需 rw」的校验，所以
tags-003/tags-004 应为绿；系统标签、批量上限、锁形图标、排序折叠、点击不弹列表是
待落地项（P2-07），当前应为红。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import review_harness as H

B_EMAIL = 'review-tags-b@example.com'
B_PASSWORD = 'ReviewTagsB9271'
C_EMAIL = 'review-tags-c@example.com'
C_PASSWORD = 'ReviewTagsC9271'
REPO_NAME = 'review-tags'
CASE_FILE = os.path.join('docs', 'review-tags-cases.json')


def setup(ctx, admin_token):
    print('\n准备场景…', flush=True)
    b_token = H.create_user(ctx, B_EMAIL, B_PASSWORD)
    c_token = H.create_user(ctx, C_EMAIL, C_PASSWORD)
    repo_id = H.create_repo(ctx, admin_token, REPO_NAME)
    b_id = H.resolve_identity(ctx, B_EMAIL)
    c_id = H.resolve_identity(ctx, C_EMAIL)
    H.share_repo(ctx, admin_token, repo_id, b_id, 'rw')
    H.share_repo(ctx, admin_token, repo_id, c_id, 'r')
    H.upload_file(ctx, admin_token, repo_id, '/', 'a.txt', b'x')
    return {'repo_id': repo_id, 'b_token': b_token, 'c_token': c_token}


def build_executors(ctx, fix):
    repo_id = fix['repo_id']
    b_token = fix['b_token']
    c_token = fix['c_token']

    def list_tags(token):
        status, body = ctx.api(f'/api2/repos/{repo_id}/repo-tags/', token=token)
        data = H.json_body(body) or {}
        tags = data.get('repo_tags') or data.get('tags') or data or []
        return status, tags

    def create_tag(token, name):
        return H.post_json(ctx, token, f'/api2/repos/{repo_id}/repo-tags/',
                           {'name': name, 'color': '#ff0000'})

    def tags_001():
        status, body = create_tag(b_token, 'user-tag-1')
        _, tags = list_tags(b_token)
        found = any(t.get('name') == 'user-tag-1' for t in tags if isinstance(t, dict))
        return found, f'create status={status}, tags={tags}'

    def tags_002():
        # CE 无系统标签概念：非 admin 修改「系统标签」的判定面不存在
        return False, 'system-tag read-only seam 未实现'

    def tags_003():
        status, body = create_tag(b_token, 'user-tag-3')
        return status in (200, 201), f'rw create status={status} {body[:120]}'

    def tags_004():
        status, body = create_tag(c_token, 'user-tag-4')
        return status not in (200, 201), f'r create 应被拒 status={status} {body[:120]}'

    def tags_005():
        return False, 'batch-tag object-limit seam 未实现'

    return {
        'tags-001': tags_001, 'tags-002': tags_002, 'tags-003': tags_003,
        'tags-004': tags_004, 'tags-005': tags_005,
    }


if __name__ == '__main__':
    sys.exit(H.matrix_main(setup, build_executors, CASE_FILE))
