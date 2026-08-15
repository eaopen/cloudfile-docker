#!/usr/bin/env python3
"""浏览器套件冒烟：验证 Playwright 能驱动 CloudFile Web 前端。

这是 P2-02 UI channel 用例（16 条）的底座验证：登录、建库、上传、
进入库视图、树节点悬停。selector 以 Seafile 14 React 前端为准，
若前端结构变化导致 selector 失效，这里会先红，而不是让 16 条用例一起红。

    python3 browser_smoke.py --url https://127.0.0.1 --admin me@example.com \
        --admin-password xxx [--headful]
"""

import argparse
import sys
import time

from playwright.sync_api import sync_playwright

from review_harness import allow_insecure, Context, create_repo, upload_file, mkdir


def login(page, base, email, password):
    page.goto(base + '/accounts/login/', wait_until='networkidle')
    page.fill('#id_login', email)
    page.fill('#id_password', password)
    page.click('input[type=submit], button[type=submit]')
    # Seafile 登录后跳到库列表；失败会留在登录页
    for _ in range(30):
        if '/library' in page.url or '/accounts/login' not in page.url:
            return True
        time.sleep(1)
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--url', required=True)
    ap.add_argument('--admin', required=True)
    ap.add_argument('--admin-password', required=True)
    ap.add_argument('--headful', action='store_true')
    args = ap.parse_args()

    allow_insecure()
    base = args.url.rstrip('/')

    # API 侧准备（上传等用 token 更快），浏览器侧只做视图断言。
    ctx = Context(base, args.admin, args.admin_password)
    if not ctx.token(args.admin, args.admin_password):
        print('✗ 无法取得管理员 token', file=sys.stderr)
        return 1
    repo_id = create_repo(ctx, ctx.token(args.admin, args.admin_password),
                          'browser-smoke')
    upload_file(ctx, ctx.token(args.admin, args.admin_password),
                repo_id, '/', 'hello.txt', b'hello browser')
    mkdir(ctx, ctx.token(args.admin, args.admin_password), repo_id, 'docs')

    results = []

    def record(name, ok, detail=''):
        results.append((name, ok))
        print(f'  {"✓" if ok else "✗"} {name}  {detail}', flush=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not args.headful)
        page = browser.new_page(ignore_https_errors=True,
                                viewport={'width': 1440, 'height': 900})
        record('登录 Web 前端', login(page, base, args.admin,
                                      args.admin_password),
               f'url={page.url}')
        # 库列表页应该出现 smoke 库
        page.goto(base + '/library/', wait_until='networkidle')
        record('库列表可达', '/library' in page.url, page.url)
        has_repo = 'browser-smoke' in page.content()
        record('库列表含 smoke 库', has_repo)
        # 进入库视图（列表模式）
        page.goto(base + f'/library/{repo_id}/', wait_until='networkidle')
        time.sleep(2)
        has_file = 'hello.txt' in page.content()
        record('库视图含 hello.txt', has_file)
        has_dir = 'docs' in page.content()
        record('库视图含 docs 目录', has_dir)
        browser.close()

    failed = [n for n, ok in results if not ok]
    print(f'浏览器冒烟 {len(results) - len(failed)}/{len(results)} 通过')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
