#!/usr/bin/env python3
"""操作历史 review 门禁（P2-02，P2-10 落地）。

对照 docs/review-history-cases.json。CE 的 file/history 已返回修订提交（含创建人，
即「来源」），所以 history-001 应为绿；P2-10 在 seahub/api2/views.py 给
file/history 加了可选的 q/operator/source/page/per_page（history-002/003/004），
给 repo/history 加了可选的 path/current_folder_only 文件夹范围
（history-006/007）。不传这些参数时行为与 CE 一致。

场景：admin 上传 f.txt v1/v2；建 /docs、/docs/a.txt、/docs/sub、/docs/sub/b.txt；
rw 用户 b 再上传 f.txt v3。repo 提交（新→旧）：
  1. b 修改 f.txt（v3）          2. 添加 docs/sub/b.txt
  3. 新建目录 /docs/sub          4. 添加 docs/a.txt
  5. 新建目录 /docs              6. 修改 f.txt（v2）
  7. 添加 f.txt（v1）
/docs 默认范围（文件夹本身 + 直属下一级）= {5, 4, 3}，共 3 条；
current_folder_only（仅文件夹本身）= {5}，共 1 条。
"""

import os
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import review_harness as H

B_EMAIL = 'review-history-b@example.com'
B_PASSWORD = 'ReviewHistoryB9271'
REPO_NAME = 'review-history'
CASE_FILE = os.path.join('docs', 'review-history-cases.json')


def setup(ctx, admin_token):
    print('\n准备场景…', flush=True)
    b_token = H.create_user(ctx, B_EMAIL, B_PASSWORD)
    repo_id = H.create_repo(ctx, admin_token, REPO_NAME)
    b_id = H.resolve_identity(ctx, B_EMAIL)
    H.share_repo(ctx, admin_token, repo_id, b_id, 'rw')
    H.upload_file(ctx, admin_token, repo_id, '/', 'f.txt', b'v1')
    H.upload_file(ctx, admin_token, repo_id, '/', 'f.txt', b'v2')
    H.mkdir(ctx, admin_token, repo_id, 'docs')
    H.upload_file(ctx, admin_token, repo_id, '/docs', 'a.txt', b'a')
    H.mkdir(ctx, admin_token, repo_id, 'docs/sub')
    H.upload_file(ctx, admin_token, repo_id, '/docs/sub', 'b.txt', b'b')
    # The rw user owns the newest f.txt revision.
    H.upload_file(ctx, b_token, repo_id, '/', 'f.txt', b'v3')
    return {'repo_id': repo_id, 'b_token': b_token}


def build_executors(ctx, fix):
    repo_id = fix['repo_id']
    b_token = fix['b_token']

    def file_history(path='/f.txt', **params):
        qs = urllib.parse.urlencode({'p': path, **params})
        status, body = ctx.api(
            f'/api2/repos/{repo_id}/file/history/?{qs}', token=b_token)
        return status, (H.json_body(body) or {})

    def folder_history(**params):
        qs = urllib.parse.urlencode(params)
        status, body = ctx.api(
            f'/api2/repos/{repo_id}/history/?{qs}', token=b_token)
        return status, (H.json_body(body) or {})

    def commits_of(data):
        return data.get('commits') or data.get('data') or []

    def history_001():
        status, data = file_history()
        commits = commits_of(data)
        has_creator = any((c.get('creator_name') or c.get('creator'))
                          for c in commits if isinstance(c, dict))
        return has_creator, f'file history status={status}, commits={len(commits)}'

    def history_002():
        _, data = file_history(q='Added')
        added = commits_of(data)
        _, data2 = file_history(q='Modified')
        modified = commits_of(data2)
        ok = len(added) == 1 and len(modified) == 2
        return ok, f'q=Added -> {len(added)} 条, q=Modified -> {len(modified)} 条（期望 1/2）'

    def history_003():
        _, data = file_history(operator=ctx.admin_email)
        by_operator = commits_of(data)
        _, data2 = file_history(source=B_EMAIL)
        by_source = commits_of(data2)
        ok = len(by_operator) == 2 and len(by_source) == 1
        return ok, (f'operator=admin -> {len(by_operator)} 条（期望 2）, '
                    f'source=b -> {len(by_source)} 条（期望 1）')

    def history_004():
        _, p1 = file_history(page='1', per_page='2')
        _, p2 = file_history(page='2', per_page='2')
        c1, c2 = commits_of(p1), commits_of(p2)
        ids1 = {c.get('id') for c in c1 if isinstance(c, dict)}
        ids2 = {c.get('id') for c in c2 if isinstance(c, dict)}
        union = ids1 | ids2
        ok = (len(c1) == 2 and p1.get('page_next') is True
              and len(c2) == 1 and p2.get('page_next') is False
              and not (ids1 & ids2) and len(union) == 3)
        return ok, (f'p1={len(c1)} next={p1.get("page_next")}, '
                    f'p2={len(c2)} next={p2.get("page_next")}, '
                    f'无重叠且并集={len(union)}（期望 3）')

    def history_005():
        status, data = file_history()
        commits = commits_of(data)
        first = commits[0] if isinstance(commits, list) and commits else {}
        has_detail = isinstance(first, dict) and (
            first.get('ctime') or first.get('size') is not None)
        return has_detail, f'detail status={status}, first={first}'

    def history_006():
        status, data = folder_history(path='/docs')
        commits = commits_of(data)
        ok = len(commits) == 3
        return ok, (f'folder history status={status}, commits={len(commits)} '
                    f'（期望 3：/docs、/docs/a.txt、/docs/sub，不含更深层）')

    def history_007():
        status, data = folder_history(path='/docs', current_folder_only='1')
        commits = commits_of(data)
        ok = len(commits) == 1
        return ok, (f'current-folder-only status={status}, commits={len(commits)} '
                    f'（期望 1：仅 /docs 自身，排除直属子级）')

    return {
        'history-001': history_001, 'history-002': history_002,
        'history-003': history_003, 'history-004': history_004,
        'history-005': history_005, 'history-006': history_006,
        'history-007': history_007,
    }


if __name__ == '__main__':
    sys.exit(H.matrix_main(setup, build_executors, CASE_FILE))
