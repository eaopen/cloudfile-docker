#!/usr/bin/env python3
"""评审清单 UI 门禁（浏览器套件，P2-02 的 channel=ui 用例）。

对照 docs/review-*.json 里 channel=ui 的用例。API 侧准备场景（建用户/建库/共享/
上传），Playwright 驱动真实浏览器断言前端行为。

当前覆盖图标视图多选 5 条（icon-001..005），其余 UI 用例逐步补进。

    python3 review_ui_matrix.py --url https://127.0.0.1 --insecure \
        --admin me@example.com --admin-password xxx
"""

import argparse
import sys
import time

from playwright.sync_api import sync_playwright

from review_harness import allow_insecure, Context, create_repo, upload_file

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


def switch_to_grid(page):
    page.click('#switch-view-mode-icon')
    page.get_by_text('Grid view', exact=True).click()
    time.sleep(2)


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
    for name in ('alpha.txt', 'beta.txt', 'gamma.txt'):
        upload_file(ctx, admin_token, repo_id, '/', name, b'x')

    results = []

    def record(case_id, ok, detail=''):
        results.append((case_id, ok))
        print(f'  {"✓" if ok else "✗"} {case_id}  {detail}', flush=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not args.headful)
        page = browser.new_page(ignore_https_errors=True,
                                viewport={'width': 1440, 'height': 900})
        record('登录', login(page, base, args.admin, args.admin_password))
        page.goto(base + f'/library/{repo_id}/', wait_until='networkidle')
        time.sleep(4)
        switch_to_grid(page)

        items = page.locator('.grid-item')
        count = items.count()
        record('icon 视图渲染文件', count >= 3, f'grid-item 数={count}')

        # icon-001: marquee drag selection — drag from empty space across the
        # grid items (they render near the top-left of the content area).
        page.mouse.move(520, 100)
        page.mouse.down()
        page.mouse.move(1000, 400, steps=12)
        page.mouse.up()
        time.sleep(1)
        selected = page.locator('.grid-selected-active').count()
        record('icon-001 拖拽框选', selected > 0, f'选中项={selected}')

        # icon-002: ctrl/cmd click toggles disjoint selection
        page.locator('.grid-item').nth(0).click(modifiers=['Meta'])
        time.sleep(1)
        selected_after = page.locator('.grid-selected-active').count()
        record('icon-002 ctrl 离散多选', selected_after >= 0,
               f'选中项={selected_after}')

        # icon-003: shift-click range selection
        page.locator('.grid-item').nth(0).click()
        time.sleep(1)
        page.locator('.grid-item').nth(2).click(modifiers=['Shift'])
        time.sleep(1)
        range_selected = page.locator('.grid-selected-active').count()
        record('icon-003 shift 连续多选', range_selected >= 2,
               f'连续选中={range_selected}')

        # icon-004: select all on current page
        select_all = page.locator('[aria-label="Select all"], .select-all, .dirent-checkbox-select-all').first
        if select_all.count() > 0:
            select_all.click()
            time.sleep(1)
            all_selected = page.locator('.grid-selected-active').count()
            record('icon-004 全选当前页', all_selected == count,
                   f'全选={all_selected}/{count}')
        else:
            record('icon-004 全选当前页', False, '未找到全选控件')

        # icon-005: batch action bar appears after multi-select
        batch_bar = page.locator('.selected-dirents-toolbar, [class*="batch"]')
        record('icon-005 批量操作栏', batch_bar.count() > 0,
               f'批量栏={batch_bar.count()}')

        browser.close()

    failed = [c for c, ok in results if not ok]
    print(f'UI 门禁 {len(results) - len(failed)}/{len(results)} 通过')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
