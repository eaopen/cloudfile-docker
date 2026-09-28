#!/usr/bin/env python3
"""Storage-class assignment API matrix (P2 storage backends, backend+API only).

Verifies the two self-service allocation endpoints added in cloudfile-hub
(``cloudfile_ext/storage``) against a stack running with
``CF_ENABLE_S3_STORAGE=true`` and ``SEAF_SERVER_STORAGE_TYPE=multiple``:

    GET  /api/v2.1/cloudfile/storage-classes/   list configured classes
    POST /api/v2.1/cloudfile/repos/             create a repo pinned to a class

The storage classes may be fs-backed (no MinIO needed): the pin is written by
seaf-server *before* the initial commit, so a repo created with a non-default
storage_id stays readable (its root commit lives in the chosen store).

    python3 storage_classes_matrix.py --url https://127.0.0.1 --insecure \
        --admin admin@cloudfile.test --admin-password CloudFile-CI-4417
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import review_harness as H


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--url', required=True)
    ap.add_argument('--insecure', action='store_true')
    ap.add_argument('--admin', required=True)
    ap.add_argument('--admin-password', required=True)
    args = ap.parse_args()
    if args.insecure:
        H.allow_insecure()

    ctx = H.Context(args.url, args.admin, args.admin_password)
    if not H.wait_ready(ctx.base):
        return 1
    token = H.get_token(ctx.base, args.admin, args.admin_password)[0]
    if not token:
        print('无法取得管理员 token', file=sys.stderr)
        return 1

    passed = True

    # 1. List storage classes.
    status, body = ctx.api('/api/v2.1/cloudfile/storage-classes/', token=token)
    classes = (H.json_body(body) or {}).get('storage_classes') or []
    ok = (status == 200 and isinstance(classes, list) and len(classes) >= 1
          and all('storage_id' in c for c in classes))
    print(('  PASS ' if ok else '  FAIL ')
          + f'[storage-classes 列表] status={status} classes={classes}', flush=True)
    passed &= ok

    if not ok or len(classes) < 2:
        print('  需至少两个存储类（一个默认 + 一个非默认）才能测固定存储类建库。',
              flush=True)
        return 1 if not ok else 0

    default = next((c for c in classes if c.get('is_default')), classes[0])
    second = next((c for c in classes if not c.get('is_default')), None)
    if not second:
        print('  无第二个存储类，跳过建库固定断言。', flush=True)
        return 0 if passed else 1
    target = second['storage_id']

    # 2. Create a repo pinned to the non-default class.
    status, body = ctx.api('/api/v2.1/cloudfile/repos/', method='POST',
                           token=token,
                           data=json.dumps({'name': 'storage-class-matrix',
                                            'storage_id': target}),
                           headers={'Content-Type': 'application/json'})
    repo_id = (H.json_body(body) or {}).get('repo_id')
    ok = status == 201 and bool(repo_id)
    print(('  PASS ' if ok else '  FAIL ')
          + f'[按 storage_id 建库] status={status} repo_id={repo_id}', flush=True)
    passed &= ok

    # 3. The repo must be readable (root commit landed in the pinned store).
    if repo_id:
        status, body = ctx.api(f'/api2/repos/{repo_id}/dir/?p=/', token=token)
        ok = status == 200
        print(('  PASS ' if ok else '  FAIL ')
              + f'[固定类建库后仍可读] status={status}', flush=True)
        passed &= ok
        ctx.api(f'/api2/repos/{repo_id}/', method='DELETE', token=token)

    print(('\n════════ ' + ('通过' if passed else '失败') + ' ════════'),
          flush=True)
    return 0 if passed else 1


if __name__ == '__main__':
    sys.exit(main())
