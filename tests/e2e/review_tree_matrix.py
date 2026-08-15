#!/usr/bin/env python3
"""树结构 review 门禁（P2-02）。

评审清单「树结构」的可执行部分只有一条 API 断言：收藏是个人数据，不向其他用户
泄漏。悬停收藏按钮 / 更多菜单 / 更多里的复制都是浏览器行为，由未来的浏览器套件
覆盖，本矩阵按 channel=ui 跳过（见 docs/review-tree-cases.json）。

    python3 review_tree_matrix.py --url https://127.0.0.1 --insecure \
        --admin me@example.com --admin-password xxx
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import review_harness as H

B_EMAIL = 'review-tree-b@example.com'
B_PASSWORD = 'ReviewTreeB9271'
REPO_NAME = 'review-tree'
CASE_FILE = os.path.join('docs', 'review-tree-cases.json')


def setup(ctx, admin_token):
    print('\n准备场景…', flush=True)
    b_token = H.create_user(ctx, B_EMAIL, B_PASSWORD)
    repo_id = H.create_repo(ctx, admin_token, REPO_NAME)
    b_id = H.resolve_identity(ctx, B_EMAIL)
    H.share_repo(ctx, admin_token, repo_id, b_id, 'rw')
    status, body = H.upload_file(ctx, admin_token, repo_id, '/', 'a.txt')
    if status != 200:
        sys.exit(f'上传失败: {status} {body[:160]}')
    status, body = ctx.api('/api2/starredfiles/', method='POST',
                           form={'repo_id': repo_id, 'path': '/a.txt'},
                           token=admin_token)
    print(f'  admin 收藏 status={status}', flush=True)
    return {'repo_id': repo_id, 'b_token': b_token}


def build_executors(ctx, fix):
    repo_id = fix['repo_id']
    b_token = fix['b_token']

    def tree_001():
        status, body = ctx.api('/api2/starredfiles/', token=b_token)
        items = H.json_body(body) or []
        leaked = [it for it in items
                  if it.get('repo_id') == repo_id and it.get('path') == '/a.txt']
        if leaked:
            return False, f'B 的收藏列表泄露了 admin 的收藏: {leaked}'
        return True, f'B 收藏列表 {len(items)} 项，无 admin 的 /a.txt'

    return {'tree-001': tree_001}


if __name__ == '__main__':
    sys.exit(H.matrix_main(setup, build_executors, CASE_FILE))
