#!/usr/bin/env python3
"""评审清单 UI 门禁（浏览器套件）：share-001 前端隐藏分享入口。

对照 docs/review-share-cases.json share-001（channel=ui）。API 侧建库并上传
文件，Playwright 驱动真实浏览器断言：CF_ENABLE_SHARE_RESTRICT 开启时，

  1. 页面不渲染任何 share 图标（Icon symbol="share" →
     .seafile-multicolor-icon-share；侧栏 share-admin 是管理入口，类名
     token 不同，不受此开关影响）；
  2. 选中文件后的 dir-operation 操作区无 share 图标、无 Share 文本。

服务端已有 share-002/004 兜底（403/404）；share-001 只断言 UI 不渲染入口。
前置条件：栈以 CF_ENABLE_SHARE_RESTRICT=true 启动（cap review-share 编排）。

    python3 review_ui_share.py --url https://127.0.0.1 --insecure \
        --admin me@example.com --admin-password xxx
"""

import argparse
import sys
import time

from playwright.sync_api import sync_playwright

from review_harness import (allow_insecure, Context, create_repo,
                            upload_file)

REPO_NAME = 'review-ui-share'

def login(page, base, email, password):
    page.goto(base + '/accounts/login/', wait_until='networkidle')
    page.fill('input[name="login"]', email)
    page.fill('input[name="password"]', password)
    page.click('button[type="submit"], .login-submit-button, input[type="submit"]')
    for _ in range(30):
        if '/accounts/login' not in page.url:
            return True
        time.sleep(1)
    return False

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
    repo_id = create_repo(ctx, admin_token, REPO_NAME)
    upload_file(ctx, admin_token, repo_id, '/', 'shared.txt', b'x')

    results = []

    def record(case_id, ok, detail=''):
        results.append((case_id, ok))
        print(f'  {"✓" if ok else "✗"} [{case_id}]  {detail}', flush=True)

    repo_url = base + f'/library/{repo_id}/{REPO_NAME}/'

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not args.headful)
        page = browser.new_page(ignore_https_errors=True,
                                viewport={'width': 1440, 'height': 900})
        record('登录', login(page, base, args.admin, args.admin_password))

        page.goto(repo_url, wait_until='networkidle')
        # loadFeatures() 异步 fetch，等它落地再判定，否则误判成"未渲染"。
        time.sleep(6)

        # ── 断言 1：整页无 share 图标（Icon symbol="share"）──
        icons = page.locator('.seafile-multicolor-icon-share')
        record('share-001(整页图标)', icons.count() == 0,
               f'share 图标数={icons.count()}')

        # ── 断言 2：选中文件 → dir-operation 区无 share 入口 ──
        # 列表视图（dirent-virtual-list）行名在 .dirent-item-name-text；
        # 点击后出现 dir-operation 操作区。
        name = page.locator('.dirent-item-name-text',
                            has_text='shared.txt').first
        detail = '未找到文件行（.dirent-item-name-text）'
        ok = False
        if name.count() > 0:
            name.click()
            time.sleep(3)
            ops = page.locator('.dir-operation')
            if ops.count() > 0:
                op_icons = ops.locator('.seafile-multicolor-icon-share')
                op_text = ops.get_by_text('Share', exact=True)
                ok = op_icons.count() == 0 and op_text.count() == 0
                detail = (f'操作区 share 图标={op_icons.count()} '
                          f'Share 文本={op_text.count()}')
            else:
                detail = '选中后 dir-operation 区未出现'
        record('share-001(选中操作区)', ok, detail)

        browser.close()

    failed = [c for c, ok in results if not ok]
    print(f'UI 分享门禁 {len(results) - len(failed)}/{len(results)} 通过')
    return 1 if failed else 0

if __name__ == '__main__':
    sys.exit(main())
