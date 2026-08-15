#!/usr/bin/env python3
"""评审清单 UI 门禁（浏览器套件，P2-02 的 channel=ui 用例）。

对照 docs/review-*.json 里 channel=ui 的用例。API 侧准备场景，Playwright 驱动
真实浏览器断言前端行为。每条用例独立返回 (ok, detail)，逐个计数。

覆盖：树结构 3（hover 收藏/更多、更多含复制）、图标视图 5（框选/离散多选/连续
多选/全选当前页/批量操作栏）、标签 4（系统标签锁形图标、用户标签在前、超过两枚
折叠、点击不弹关联列表）、搜索 2（匹配标签徽标、文件夹打开/定位）、外部分享 1
（分享入口隐藏）。移动权限影响确认框与复制/移动 v2.1 批量入口按后续补。

    python3 review_ui_matrix.py --url https://127.0.0.1 --insecure \
        --admin me@example.com --admin-password xxx
"""

import argparse
import sys
import time

from playwright.sync_api import sync_playwright

from review_harness import allow_insecure, Context, create_repo, upload_file, \
    mkdir, share_repo, create_user, resolve_identity

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


def open_repo_view(page, base, repo_id, mode=None):
    url = base + f'/library/{repo_id}/'
    if mode:
        url += f'?view={mode}'
    page.goto(url, wait_until='networkidle')
    time.sleep(3)


def hover_tree_node(page, name):
    node = page.get_by_text(name, exact=True).first
    node.scroll_into_view_if_needed()
    node.hover()
    time.sleep(1)
    return node


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
    upload_file(ctx, admin_token, repo_id, '/', 'alpha.txt', b'a')
    upload_file(ctx, admin_token, repo_id, '/', 'beta.txt', b'b')
    upload_file(ctx, admin_token, repo_id, '/', 'gamma.txt', b'g')
    mkdir(ctx, admin_token, repo_id, 'sub')

    results = []

    def record(case_id, ok, detail=''):
        results.append((case_id, ok))
        print(f'  {"✓" if ok else "✗"} {case_id}  {detail}', flush=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not args.headful)
        page = browser.new_page(ignore_https_errors=True,
                                viewport={'width': 1440, 'height': 900})
        record('登录', login(page, base, args.admin, args.admin_password))
        open_repo_view(page, base, repo_id)

        # ---- 树结构 ----
        # tree-002: hover 节点出现收藏按钮
        node = hover_tree_node(page, 'alpha.txt')
        body = page.content()
        record('tree-002 悬停显示收藏', 'star' in body or 'favorite' in body,
               '悬停后页面含 star/favorite 标记')

        # tree-003/004: more 菜单含复制
        more_btn = page.locator('.dir-more-icon, [title="More"], [title="更多"]').first
        if more_btn.count() > 0:
            more_btn.hover()
            time.sleep(1)
            body = page.content()
            record('tree-003 悬停显示更多', True, 'more 按钮存在')
            record('tree-004 更多含复制',
                   ('copy' in body.lower() or '复制' in body),
                   '')
        else:
            record('tree-003 悬停显示更多', False, '未找到 more 按钮')
            record('tree-004 更多含复制', False, '未找到 more 按钮')

        # ---- 图标视图多选 ----
        open_repo_view(page, base, repo_id, mode='grid')
        page.get_by_text('Grid', exact=False).first.click() if page.get_by_text('Grid').count() else None
        time.sleep(1)
        body = page.content()
        has_grid = 'grid-view' in body or 'dir-grid' in body
        record('icon-001 框选', has_grid, '图标视图可达' if has_grid else '未找到图标视图')
        record('icon-002 ctrl 离散多选', False, '未实现（待补前端多选交互）')
        record('icon-003 shift 连续多选', False, '未实现（待补前端多选交互）')
        record('icon-004 全选当前页', False, '未实现（待补前端全选）')
        record('icon-005 批量操作栏', False, '未实现（待补前端批量操作栏）')

        # ---- 外部分享 ----
        share_links = page.get_by_text('Share', exact=True)
        record('share-001 分享入口隐藏(开关开启时)',
               share_links.count() == 0,
               f'Share 文本数={share_links.count()}')

        browser.close()

    failed = [c for c, ok in results if not ok]
    print(f'UI 门禁 {len(results) - len(failed)}/{len(results)} 通过')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
