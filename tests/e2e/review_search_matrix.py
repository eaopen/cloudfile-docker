#!/usr/bin/env python3
"""搜索 review 门禁（P2-02 + P2-09）。

对照 docs/review-search-cases.json。名称匹配（search-001）与权限裁剪
（search-007）走默认 SeaSearch 路径；类型/位置/更新时间筛选由上游参数
（obj_type/search_path/time_from）表达，SeaSearch 与 Meilisearch 两条分支
都可断言；标签/创建人筛选（tags/creator_emails）只在选中 CloudFile provider
（Meilisearch）时生效——SeaSearch 无法表达结构化过滤器，这是
seahub.api2.views.Search 里明确注释的行为，不是缺实现。

编排层负责起 Meilisearch、把 CF_PROVIDER_SEARCH 切到 meilisearch 并跑过一轮
cf_worker --once（同 search-e2e.yml 的做法）；矩阵本身不改配置、不重启容器。
"""

import json
import os
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import review_harness as H

B_EMAIL = 'review-search-b@example.com'
B_PASSWORD = 'ReviewSearchB9271'
REPO_NAME = 'review-search'
CASE_FILE = os.path.join('docs', 'review-search-cases.json')
#: Meilisearch indexer is synchronous once cf_worker --once has run (see
#: indexer.py), but the tag/creator documents are only complete after the
#: worker pass; poll briefly so a slow worker does not read as a filter bug.
POLL_SECONDS = 60

def set_acl(ctx, admin_token, repo_id, path, subject, perm):
    return ctx.api(f'/api/v2.1/cloudfile/repos/{repo_id}/dir-acl/',
                   method='POST',
                   form={'path': path, 'subject_type': 'user', 'subject': subject,
                         'permission': perm, 'inherit': 'true'}, token=admin_token)

def search(ctx, token, query, **params):
    qs = [('q', query)] + sorted(params.items())
    status, body = ctx.api('/api2/search/?' + urllib.parse.urlencode(qs),
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
    H.upload_file(ctx, admin_token, repo_id, '/folder-alpha', 'nested.txt', b'nested')
    H.upload_file(ctx, admin_token, repo_id, '/', 'sunset.jpg', b'jpg')
    H.upload_file(ctx, admin_token, repo_id, '/secret', 'classified.txt', b'classified')
    set_acl(ctx, admin_token, repo_id, '/secret', B_EMAIL, 'invisible')

    # Tag fixture for search-004: one tag on /alpha.txt, none on /sunset.jpg.
    status, body = H.post_json(ctx, admin_token,
                               f'/api/v2.1/repos/{repo_id}/repo-tags/',
                               {'name': 'contract', 'color': '#ff0000'})
    tag_id = None
    if status in (200, 201):
        tag_id = (H.json_body(body) or {}).get('repo_tag_id') \
            or (H.json_body(body) or {}).get('id')
    if tag_id:
        status, body = H.post_json(
            ctx, admin_token, f'/api/v2.1/repos/{repo_id}/file-tags/',
            {'file_path': '/alpha.txt', 'repo_tag_id': tag_id})
    print(f'  预置标签 tag_id={tag_id} 绑定 status={status}', flush=True)

    return {'repo_id': repo_id, 'b_token': b_token,
            'admin_token': admin_token, 'tag_id': tag_id}

def build_executors(ctx, fix):
    repo_id = fix['repo_id']
    b_token = fix['b_token']
    admin_token = fix['admin_token']
    tag_id = fix['tag_id']

    def hits(token, query, **params):
        status, data = search(ctx, token, query, **params)
        out = []
        for r in (data.get('results') or []):
            if isinstance(r, dict):
                out.append((r.get('name') or '', r.get('fullpath') or '',
                            r.get('matched_tags') or (r.get('tags') or [])))
        return status, out

    def names(token, query, **params):
        status, found = hits(token, query, **params)
        return status, [n for n, _, _ in found]

    def wait_for(predicate, what):
        deadline = time.time() + POLL_SECONDS
        last = None
        while time.time() < deadline:
            last = predicate()
            if last[0]:
                return True, last[1]
            time.sleep(3)
        return False, last[1] if last else f'{what}: no result'

    def search_001():
        status, found = names(b_token, 'alpha')
        ok = any('alpha' in n for n in found)
        return ok, f'search alpha status={status}, names={found}'

    def search_002():
        # obj_type: only files match the review's "type" filter; CE folders
        # are indexed as dir, so restricting to file must drop folder-alpha.
        def probe():
            status, files = names(b_token, 'alpha', obj_type='file')
            dirs_named = [n for n in files if n == 'folder-alpha']
            return (any('alpha' in n for n in files) and not dirs_named,
                    f'obj_type=file status={status}, names={files}')
        ok, detail = wait_for(probe, 'obj_type filter')
        status, files = names(b_token, 'alpha', obj_type='file')
        return ok, f'{detail}; final status={status}'

    def search_003():
        # search_path narrows to folder-alpha: nested.txt in, alpha.txt out.
        def probe():
            status, found = names(b_token, 'alpha', search_repo=repo_id,
                                  search_path='/folder-alpha')
            paths = [n for n in found]
            return ('nested' in ' '.join(paths) and
                    not any(p == 'alpha.txt' for p in paths),
                    f'search_path status={status}, names={found}')
        ok, detail = wait_for(probe, 'search_path filter')
        return ok, detail

    def search_004():
        # tags filter rides the structured-filter vocabulary (Meilisearch
        # provider only); without the provider the param is absent upstream
        # and the case would assert a seam that CE cannot express.
        if tag_id is None:
            return False, '标签预置失败，无法断言 tag 筛选'
        def probe():
            status, found = hits(b_token, 'alpha', tags='contract')
            tagged = [n for n, _, mt in found if n == 'alpha.txt']
            return (bool(tagged) and all(
                n in ('alpha.txt',) for n, _, _ in found if n),
                f'tags=contract status={status}, hits={found}')
        ok, detail = wait_for(probe, 'tag filter')
        return ok, detail

    def search_005():
        # creator_emails filter (Meilisearch provider only): the admin owns
        # every fixture file, so filtering by the second user must exclude all.
        status, found = hits(b_token, 'alpha', creator_emails=B_EMAIL)
        excluded = all(n != 'alpha.txt' for n, _, _ in found)
        return excluded, f'creator_emails=B status={status}, hits={found}'

    def search_006():
        # time_from in the future excludes everything; a past window keeps hits.
        future = int(time.time()) + 3600
        past = int(time.time()) - 30 * 86400
        _, future_hits = names(b_token, 'alpha', time_from=future)
        _, past_hits = names(b_token, 'alpha', time_from=past)
        ok = (not future_hits) and any('alpha' in n for n in past_hits)
        return ok, f'future={future_hits} past={past_hits}'

    def search_007():
        status, found = names(b_token, 'classified')
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
