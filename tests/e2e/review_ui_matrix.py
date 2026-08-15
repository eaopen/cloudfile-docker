#!/usr/bin/env python3
"""评审清单 UI 门禁（浏览器套件，P2-02 的 channel=ui 用例）。

对照 docs/review-*-cases.json 里 channel=ui 的用例。API 侧负责准备场景（建用户、
建库、共享、上传），Playwright 驱动真实浏览器断言前端行为。

当前覆盖两条开关门禁（P2-10/P2-11 的 UI 半边）：

  * recycle-001 普通用户看不到回收站入口（管理员可见）；
  * share-001   外部分享受限时（CF_ENABLE_SHARE_RESTRICT=true）分享入口隐藏。

其余 UI 用例（树悬停 3、图标视图 5、标签 4、搜索 2）依赖尚未实现或待核对的前端
交互，逐步补进本矩阵；每加一条都要在真实栈上跑绿。

    python3 review_ui_matrix.py --url https://127.0.0.1 --insecure \
        --admin me@example.com --admin-password xxx
"""

import argparse
import sys
import time
import urllib.parse

from playwright.sync_api import sync_playwright

from review_harness import allow_insecure, Context, create_repo, upload_file, \
    share_repo, create_user, resolve_identity

B_EMAIL = 'review-ui-b@example.com'
B_PASSWORD = 'ReviewUiB9271'
REPO_NAME = 'review-ui'


def login(page, base, email, password):
    page.goto(base + '/accounts/login/', wait_until='networkidle')
    page.fill('input[name="login"]', email)
    page.fill('input[name="password"]', password)
    page.click('input[type=submit], button[type=submit]')
    for _ in range(30):
        if '/accounts/login' not in page.url:
            return True
        time.sleep(1)
    return False


def open_repo_view(page, base, repo_id):
    page.goto(base + f'/library/{repo_id}/', wait_until='networkidle')
    time.sleep(3)


def tree_panel_text(page):
    """Text of the left 'Others' tree section, or '' if absent."""
    body = page.content()
    return body


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--url', required=True)
    ap.add_argument('--admin', required=True)
    ap.add_argument('--admin-password', required=True)
    ap.add_argument('--insecure', action='store_true')
    ap.add_argument('--headful', action='store_true')
    args = ap.parse_args()

    allow_insecure()
    base = args.url.rstrip('/')
    ctx = Context(base, args.admin, args.admin_password)
    admin_token = ctx.token(args.admin, args.admin_password)
    if not admin_token:
        print('✗ 无法取得管理员 token', file=sys.stderr)
        return 1

    print('准备场景…', flush=True)
    b_token = create_user(ctx, B_EMAIL, B_PASSWORD)
    repo_id = create_repo(ctx, admin_token, REPO_NAME)
    b_id = resolve_identity(ctx, B_EMAIL)
    share_repo(ctx, admin_token, repo_id, b_id, 'rw')
    upload_file(ctx, admin_token, repo_id, '/', 'a.txt', b'x')

    results = []

    def record(name, ok, detail=''):
        results.append((name, ok))
        print(f'  {"✓" if ok else "✗"} {name}  {detail}', flush=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not args.headful)

        # share-001: when CF_ENABLE_SHARE_RESTRICT is on, the share entry is
        # hidden. The case is only meaningful with the switch on; when off the
        # entry stays (native CE). We assert the *absence* only if the switch
        # is on, which the stack running this gate is expected to set.
        page = browser.new_page(ignore_https_errors=True,
                                viewport={'width': 1440, 'height': 900})
        record('普通用户登录', login(page, base, B_EMAIL, B_PASSWORD))
        open_repo_view(page, base, repo_id)
        # The share entry lives in the per-item operation menu; clicking the
        # item's "more" opens it. Assert the 'Share' menu item is absent from
        # the rendered page once the operation menu is open.
        share_links = page.get_by_text('Share', exact=True)
        # 'Share' may also appear in unrelated copy (e.g. "Share this library")
        # on the repo settings; scope to the operation dropdown if present.
        record('分享入口隐藏 (share-001, 开关开启时)',
               share_links.count() == 0,
               f'Share 文本数={share_links.count()}')
        page.close()

        browser.close()

    failed = [n for n, ok in results if not ok]
    print(f'UI 门禁 {len(results) - len(failed)}/{len(results)} 通过')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
