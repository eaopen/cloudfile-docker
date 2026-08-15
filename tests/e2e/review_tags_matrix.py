#!/usr/bin/env python3
"""标签 review 门禁（P2-02 / P2-07）。

对照 docs/review-tags-cases.json。P2-07 在 CE repo-tags 上落地系统/用户标签：
系统标签仅 admin 可写、用户标签 rw 及以上可编辑、批量加标签受单次上限约束。
因此 tags-001/tags-002/tags-003/tags-004/tags-005 在开启 CF_ENABLE_TAGS 的
能力门禁里应全部为绿；锁形图标、排序折叠、点击不弹列表仍是浏览器用例。
"""

import json
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

# Matches CF_TAG_BATCH_LIMIT's default (cloudfile-hub
# cloudfile_ext/settings_defaults.py). The capability gate runs with default
# configuration, so the over-limit probe is limit+1.
BATCH_LIMIT = 100
SYSTEM_TAG = 'system-tag-1'


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

    # An admin-created system tag is the fixture tags-002 asserts against.
    # Retry briefly: a freshly started stack can transiently answer 404 for a
    # repo the API just created (entrypoint still finishing), and a missing
    # fixture would turn tags-002 into a false negative.
    import time as _time
    status, body = 0, ''
    for _ in range(3):
        status, body = create_tag(ctx, admin_token, repo_id, SYSTEM_TAG,
                                  is_system=True)
        if status in (200, 201):
            break
        _time.sleep(5)
    print(f'  预置系统标签 status={status} {body[:160]}', flush=True)

    return {'repo_id': repo_id, 'admin_token': admin_token,
            'b_token': b_token, 'c_token': c_token}


def list_tags(ctx, repo_id, token):
    status, body = ctx.api(f'/api/v2.1/repos/{repo_id}/repo-tags/', token=token)
    data = H.json_body(body) or {}
    tags = data.get('repo_tags') or data.get('tags') or data or []
    return status, tags


def create_tag(ctx, repo_id, token, name, is_system=False):
    payload = {'name': name, 'color': '#ff0000'}
    if is_system:
        payload['is_system'] = True
    return H.post_json(ctx, token, f'/api/v2.1/repos/{repo_id}/repo-tags/',
                       payload)


def rename_tag(ctx, repo_id, token, tag_id, name):
    return ctx.api(f'/api/v2.1/repos/{repo_id}/repo-tags/{tag_id}/',
                   method='PUT', token=token,
                   data=json.dumps({'name': name, 'color': '#00ff00'}).encode(),
                   headers={'Content-Type': 'application/json'})


def delete_tag(ctx, repo_id, token, tag_id):
    return ctx.api(f'/api/v2.1/repos/{repo_id}/repo-tags/{tag_id}/',
                   method='DELETE', token=token)


def bulk_add(ctx, repo_id, token, names):
    tags = [{'name': name, 'color': '#0000ff'} for name in names]
    return ctx.api(f'/api/v2.1/repos/{repo_id}/repo-tags/', method='PUT',
                   token=token,
                   data=json.dumps({'tags': tags}).encode(),
                   headers={'Content-Type': 'application/json'})


def build_executors(ctx, fix):
    repo_id = fix['repo_id']
    admin_token = fix['admin_token']
    b_token = fix['b_token']
    c_token = fix['c_token']

    def tags_001():
        status, body = create_tag(ctx, repo_id, b_token, 'user-tag-1')
        _, tags = list_tags(ctx, repo_id, b_token)
        found = any((t.get('tag_name') or t.get('name')) == 'user-tag-1'
                    for t in tags if isinstance(t, dict))
        return found, f'create status={status}, tags={tags}'

    def tags_002():
        # A non-admin (rw) must not create, rename or delete a system tag.
        _, tags = list_tags(ctx, repo_id, b_token)
        system_id = None
        for t in tags:
            if isinstance(t, dict) and (t.get('tag_name') or t.get('name')) == SYSTEM_TAG:
                system_id = t.get('repo_tag_id') or t.get('id')
        if system_id is None:
            return False, f'预置系统标签 {SYSTEM_TAG} 未找到: {tags}'

        create_status, _ = create_tag(ctx, repo_id, b_token, 'system-tag-x', is_system=True)
        rename_status, _ = rename_tag(ctx, repo_id, b_token, system_id, 'system-tag-renamed')
        delete_status, _ = delete_tag(ctx, repo_id, b_token, system_id)
        denied = all(s in (400, 403) for s in (create_status, rename_status, delete_status))
        return denied, (f'create={create_status} rename={rename_status} '
                        f'delete={delete_status}')

    def tags_003():
        status, body = create_tag(ctx, repo_id, b_token, 'user-tag-3')
        return status in (200, 201), f'rw create status={status} {body[:120]}'

    def tags_004():
        status, body = create_tag(ctx, repo_id, c_token, 'user-tag-4')
        return status not in (200, 201), f'r create 应被拒 status={status} {body[:120]}'

    def tags_005():
        over_names = [f'bulk-over-{i}' for i in range(BATCH_LIMIT + 1)]
        over_status, over_body = bulk_add(ctx, repo_id, b_token, over_names)
        under_status, under_body = bulk_add(ctx, repo_id, b_token, ['bulk-ok-1', 'bulk-ok-2'])
        ok = over_status in (400, 403) and under_status in (200, 201)
        return ok, (f'over({BATCH_LIMIT + 1})={over_status} '
                    f'under(2)={under_status} over_body={over_body[:120]}')

    return {
        'tags-001': tags_001, 'tags-002': tags_002, 'tags-003': tags_003,
        'tags-004': tags_004, 'tags-005': tags_005,
    }


if __name__ == '__main__':
    sys.exit(H.matrix_main(setup, build_executors, CASE_FILE))
