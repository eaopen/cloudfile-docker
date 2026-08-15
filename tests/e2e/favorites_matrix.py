#!/usr/bin/env python3
"""收藏对象 ID 化容器 E2E（P2-05）。

对照 docs/features/favorites.md：开启 CF_ENABLE_FAVORITES_ID 后收藏身份改为
(email, org_id, obj_id)，移动/重命名跟随对象。本矩阵断言：

  * 收藏后可列举，且路径可解析；
  * 文件移动后，收藏仍指向同一对象（路径更新为新位置），旧路径不再出现；
  * 关闭开关时的行为由基线 smoke 覆盖（原生 CE 收藏）。

    python3 favorites_matrix.py --url https://127.0.0.1 --insecure \
        --admin me@example.com --admin-password xxx
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import review_harness as H

REPO_NAME = 'cf-favorites'


def setup(ctx, admin_token):
    print('\n准备场景…', flush=True)
    repo_id = H.create_repo(ctx, admin_token, REPO_NAME)
    H.upload_file(ctx, admin_token, repo_id, '/', 'fav.txt', b'x')
    H.mkdir(ctx, admin_token, repo_id, 'dest')
    H.upload_file(ctx, admin_token, repo_id, '/dest', 'other.txt', b'y')
    return {'repo_id': repo_id, 'admin_token': admin_token}


def build_executors(ctx, fix):
    repo_id = fix['repo_id']
    admin_token = fix['admin_token']

    def star(path):
        return ctx.api('/api2/starredfiles/', method='POST',
                       form={'repo_id': repo_id, 'path': path},
                       token=admin_token)

    def starred():
        status, body = ctx.api('/api2/starredfiles/', token=admin_token)
        return status, (H.json_body(body) or [])

    def fav_001():
        status, _ = star('/fav.txt')
        s2, items = starred()
        has = any(it.get('repo_id') == repo_id and it.get('path') == '/fav.txt'
                  for it in items if isinstance(it, dict))
        ok = status in (200, 201) and s2 == 200 and has
        return ok, f'收藏 status={status}, 列表 status={s2}, 含 /fav.txt: {has}'

    def fav_002():
        star('/fav.txt')
        status, body = ctx.api(
            f'/api2/repos/{repo_id}/file/?p=/fav.txt', method='POST',
            form={'operation': 'move', 'dst_repo_id': repo_id,
                  'dst_dir': '/dest'},
            token=admin_token)
        if status != 200:
            return False, f'移动失败 status={status} {body[:160]}'
        s2, items = starred()
        moved = any(it.get('repo_id') == repo_id and
                    it.get('path') == '/dest/fav.txt' for it in items)
        old_gone = not any(it.get('repo_id') == repo_id and
                          it.get('path') == '/fav.txt' for it in items)
        ok = s2 == 200 and moved and old_gone
        return ok, (f'移动后收藏路径 /dest/fav.txt: {moved}, '
                    f'旧路径消失: {old_gone}')

    return {'favorites-001': fav_001, 'favorites-002': fav_002}


if __name__ == '__main__':
    sys.exit(H.matrix_main(setup, build_executors,
                           os.path.join('docs', 'review-favorites-cases.json')))
