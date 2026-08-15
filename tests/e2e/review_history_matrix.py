#!/usr/bin/env python3
"""操作历史 review 门禁（P2-02）。

对照 docs/review-history-cases.json。CE 的 file/history 已返回修订提交（含创建人，
即「来源」），所以 history-001 应为绿；搜索/筛选/分页/文件夹「直属下一级」范围是
待落地项（P2-03+），当前应为红。
"""

import os
import sys

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
    return {'repo_id': repo_id, 'b_token': b_token}


def build_executors(ctx, fix):
    repo_id = fix['repo_id']
    b_token = fix['b_token']

    def file_history(path='/f.txt'):
        import urllib.parse
        status, body = ctx.api(
            f'/api2/repos/{repo_id}/file/history/?path={urllib.parse.quote(path)}',
            token=b_token)
        return status, (H.json_body(body) or {})

    def history_001():
        status, data = file_history()
        commits = data.get('data') or data.get('commits') or data or []
        has_creator = any((c.get('creator_name') or c.get('creator')) for c in commits
                          if isinstance(c, dict))
        return has_creator, f'file history status={status}, commits={len(commits) if isinstance(commits, list) else commits}'

    def history_002():
        return False, 'file-history search seam 未实现'

    def history_003():
        return False, 'file-history filter seam 未实现'

    def history_004():
        status, data = file_history()
        return False, f'pagination seam 未实现；history status={status}'

    def history_005():
        status, data = file_history()
        commits = data.get('data') or data.get('commits') or data or []
        first = commits[0] if isinstance(commits, list) and commits else {}
        has_detail = isinstance(first, dict) and (first.get('ctime') or first.get('size') is not None)
        return has_detail, f'detail status={status}, first={first}'

    def history_006():
        return False, 'folder-history direct-children scope 未实现'

    def history_007():
        return False, 'folder-history current-folder-only filter 未实现'

    return {
        'history-001': history_001, 'history-002': history_002,
        'history-003': history_003, 'history-004': history_004,
        'history-005': history_005, 'history-006': history_006,
        'history-007': history_007,
    }


if __name__ == '__main__':
    sys.exit(H.matrix_main(setup, build_executors, CASE_FILE))
