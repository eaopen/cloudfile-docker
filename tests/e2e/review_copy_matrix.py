#!/usr/bin/env python3
"""复制 review 门禁（P2-02 → P2-06）。

对照 docs/review-copy-cases.json。P2-06 在开启 CF_ENABLE_FILEOPS 时把 fileops/copy
影子成统一预检查：权限否定用目录 ACL 收紧来源/目标；同名冲突默认 rename（绝不静默
覆盖）；单文件大小/文件夹层级逐项进失败清单；配额 443；task_id 幂等去重。门禁需要
在 .env 里设置 CF_FILEOP_MAX_FILE_SIZE 与 CF_FILEOP_MAX_FOLDER_DEPTH 供大小/层级
用例使用（由 verify-local.sh cap review-copy 编排）。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import review_harness as H

B_EMAIL = 'review-copy-b@example.com'
B_PASSWORD = 'ReviewCopyB9271'
REPO_NAME = 'review-copy'
CASE_FILE = os.path.join('docs', 'review-copy-cases.json')

#: Gate .env sets CF_FILEOP_MAX_FILE_SIZE to 100 (bytes) so this 200-byte file
#: is over-limit, while the 12-byte f.txt is not.
BIG_BIN_BYTES = 200
#: The gate's CF_FILEOP_MAX_FOLDER_DEPTH=1; /src/deep has two nested dir levels.
#: A 1.5 MiB payload exceeds the 1 MiB user quota the matrix sets for the admin.
HUGE_BIN_BYTES = 1536 * 1024


def set_acl(ctx, admin_token, repo_id, path, subject, perm):
    return ctx.api(f'/api/v2.1/cloudfile/repos/{repo_id}/dir-acl/',
                   method='POST',
                   form={'path': path, 'subject_type': 'user', 'subject': subject,
                         'permission': perm, 'inherit': 'true'}, token=admin_token)


def copy_item(ctx, token, src_repo, src_parent, src_name, dst_repo, dst_parent,
              dirent_type='file'):
    return H.post_json(ctx, token, f'/api2/repos/{src_repo}/fileops/copy/',
                       {'src_repo_id': src_repo, 'src_parent_dir': src_parent,
                        'src_dirent_name': src_name, 'dst_repo_id': dst_repo,
                        'dst_parent_dir': dst_parent, 'operation': 'copy',
                        'dirent_type': dirent_type})


def list_dir(ctx, token, repo_id, path):
    import urllib.parse
    status, body = ctx.api(
        f'/api2/repos/{repo_id}/dir/?p={urllib.parse.quote(path)}', token=token)
    return [e.get('name') for e in (H.json_body(body) or [])]


def setup(ctx, admin_token):
    print('\n准备场景…', flush=True)
    b_token = H.create_user(ctx, B_EMAIL, B_PASSWORD)
    repo_id = H.create_repo(ctx, admin_token, REPO_NAME)
    b_id = H.resolve_identity(ctx, B_EMAIL)
    H.share_repo(ctx, admin_token, repo_id, b_id, 'rw')
    for folder in ('src', 'src-secret', 'dst', 'dst-ro'):
        H.mkdir(ctx, admin_token, repo_id, folder)
    H.upload_file(ctx, admin_token, repo_id, '/src', 'f.txt', b'src-content')
    H.upload_file(ctx, admin_token, repo_id, '/src', 'g.txt', b'g')
    H.upload_file(ctx, admin_token, repo_id, '/src', 'big.bin',
                  b'x' * BIG_BIN_BYTES)
    for folder in ('src/deep', 'src/deep/sub', 'src/deep/sub/inner'):
        H.mkdir(ctx, admin_token, repo_id, folder)
    H.upload_file(ctx, admin_token, repo_id, '/src/deep/sub/inner',
                  'leaf.txt', b'x')
    H.upload_file(ctx, admin_token, repo_id, '/src-secret', 'f.txt', b'secret')
    H.upload_file(ctx, admin_token, repo_id, '/dst', 'f.txt', b'existing')
    set_acl(ctx, admin_token, repo_id, '/src-secret', B_EMAIL, 'none')
    set_acl(ctx, admin_token, repo_id, '/dst-ro', B_EMAIL, 'r')

    # Cross-owner quota fixture: B owns a repo with a large file, admin's own
    # quota is capped afterwards so a copy into admin's library trips it.
    b_repo_id = H.create_repo(ctx, b_token, 'review-copy-b')
    H.upload_file(ctx, b_token, b_repo_id, '/', 'huge.bin',
                  b'x' * HUGE_BIN_BYTES)
    H.set_user_quota(ctx, admin_token, ctx.admin_email, 1)

    return {'repo_id': repo_id, 'b_repo_id': b_repo_id, 'b_token': b_token}


def build_executors(ctx, fix):
    repo_id = fix['repo_id']
    b_token = fix['b_token']

    def copy_001():
        status, body = copy_item(ctx, b_token, repo_id, '/src-secret', 'f.txt',
                                 repo_id, '/dst')
        ok = status == 403
        return ok, f'source none -> copy status={status} {body[:120]}'

    def copy_002():
        status, body = copy_item(ctx, b_token, repo_id, '/src', 'f.txt',
                                 repo_id, '/dst-ro')
        ok = status == 403
        return ok, f'target read-only -> copy status={status} {body[:120]}'

    def copy_003():
        status, body = copy_item(ctx, b_token, repo_id, '/src', 'f.txt',
                                 repo_id, '/dst')
        names = list_dir(ctx, b_token, repo_id, '/dst')
        overwritten = status in (200, 201) and set(names) == {'f.txt'}
        return (not overwritten), f'conflict copy status={status}, dst names={names}'

    def copy_004():
        status, body = copy_item(ctx, b_token, repo_id, '/src', 'big.bin',
                                 repo_id, '/dst')
        failures = (H.json_body(body) or {}).get('failures') or []
        reasons = [f.get('reason') for f in failures]
        ok = 'over_size' in reasons and 'big.bin' not in list_dir(ctx, b_token, repo_id, '/dst')
        return ok, f'size-limit copy status={status} failures={failures}'

    def copy_005():
        status, body = copy_item(ctx, b_token, repo_id, '/src', 'deep',
                                 repo_id, '/dst', dirent_type='dir')
        failures = (H.json_body(body) or {}).get('failures') or []
        reasons = [f.get('reason') for f in failures]
        ok = 'over_depth' in reasons
        return ok, f'depth-limit copy status={status} failures={failures}'

    def copy_006():
        status, body = copy_item(ctx, b_token, fix['b_repo_id'], '/', 'huge.bin',
                                 repo_id, '/dst')
        ok = status == 443
        return ok, f'over-quota copy status={status} {body[:120]}'

    def copy_007():
        status, body = copy_item(ctx, b_token, repo_id, '/src', 'g.txt',
                                 repo_id, '/dst')
        first = (H.json_body(body) or {}).get('task_id')
        status2, body2 = copy_item(ctx, b_token, repo_id, '/src', 'g.txt',
                                   repo_id, '/dst')
        second = (H.json_body(body2) or {}).get('task_id')
        count = list_dir(ctx, b_token, repo_id, '/dst').count('g.txt')
        ok = bool(first) and first == second and count <= 1
        return ok, (f'idempotency status={status}/{status2} '
                    f'task_id={first}/{second} g.txt count={count}')

    return {
        'copy-001': copy_001, 'copy-002': copy_002, 'copy-003': copy_003,
        'copy-004': copy_004, 'copy-005': copy_005, 'copy-006': copy_006,
        'copy-007': copy_007,
    }


if __name__ == '__main__':
    sys.exit(H.matrix_main(setup, build_executors, CASE_FILE))
