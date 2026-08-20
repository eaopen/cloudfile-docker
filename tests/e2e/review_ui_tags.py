#!/usr/bin/env python3
"""评审清单 UI 门禁（浏览器套件）：P2-07 标签四条 channel=ui 用例。

对照 docs/review-tags-cases.json tags-006..009。API 侧准备场景（建系统/用户
标签、绑定文件），Playwright 驱动真实浏览器断言前端行为：

  tags-006 系统标签锁形图标（repo-info-bar used-tag-list）
  tags-007 用户标签在前系统标签在后（同一条 used-tag-list 的渲染顺序）
  tags-008 超过两枚折叠为前两枚 + …（目录表格 file-tags formatter）
  tags-009 点击标签仅选中不弹关联列表（tags-tree-view selectTag）

    python3 review_ui_tags.py --url https://127.0.0.1 --insecure \
        --admin me@example.com --admin-password xxx
"""

import argparse
import json
import sys
import time

from playwright.sync_api import sync_playwright

from review_harness import (allow_insecure, Context, create_repo,
                            post_json, upload_file)

REPO_NAME = 'review-ui-tags'

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

def create_tag(ctx, token, repo_id, name, is_system=False):
    payload = {'name': name, 'color': '#ff0000'}
    if is_system:
        payload['is_system'] = True
    status, body = post_json(ctx, token, f'/api/v2.1/repos/{repo_id}/repo-tags/',
                             payload)
    tag_id = None
    data = json.loads(body) if isinstance(body, (str, bytes)) else body
    if isinstance(data, dict):
        tag_id = (data.get('repo_tag') or {}).get('repo_tag_id')
    return status, tag_id

def bind_tag(ctx, token, repo_id, tag_id, file_path):
    return post_json(ctx, token, f'/api/v2.1/repos/{repo_id}/file-tags/',
                     {'file_path': file_path, 'repo_tag_id': tag_id})

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
    upload_file(ctx, admin_token, repo_id, '/', 'tagged.txt', b'x')

    # 新库默认关闭扩展属性。不开启的话前端走原生列表视图：
    # used-tag-list、tags-formatter、tags-tree-view 都不渲染。
    # PUT /metadata/ 打开扩展属性与标签表（返回 200 + task_id）。
    status, _ = ctx.api(f'/api/v2.1/repos/{repo_id}/metadata/',
                        method='PUT', token=admin_token)
    if status != 200:
        print(f'✗ 开启扩展属性失败 status={status}', file=sys.stderr)
        return 1

    # 系统标签先建（id 靠前），绑定到文件使 used-tag-list 出现系统+用户两组。
    status, sys_id = create_tag(ctx, admin_token, repo_id, 'sys-locked', is_system=True)
    if status != 201 or sys_id is None:
        print(f'✗ 预置系统标签失败 status={status}', file=sys.stderr)
        return 1
    # 三枚用户标签：两枚绑定 tagged.txt（表格折叠用例需要 ≥3 枚），
    # 第三枚也绑定，使 used-tag-list 同时含用户与系统标签。
    user_ids = []
    for name in ('user-a', 'user-b', 'user-c'):
        status, tid = create_tag(ctx, admin_token, repo_id, name)
        if status != 201 or tid is None:
            print(f'✗ 预置用户标签 {name} 失败 status={status}', file=sys.stderr)
            return 1
        user_ids.append(tid)
    for tid in user_ids + [sys_id]:
        status, body = bind_tag(ctx, admin_token, repo_id, tid, '/tagged.txt')
        if status != 201:
            print(f'✗ 绑定标签 {tid} 失败 status={status} {body[:120]}', file=sys.stderr)
            return 1

    results = []

    def record(case_id, ok, detail=''):
        results.append((case_id, ok))
        print(f'  {"✓" if ok else "✗"} [{case_id}]  {detail}', flush=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not args.headful)
        page = browser.new_page(ignore_https_errors=True,
                                viewport={'width': 1440, 'height': 900})
        record('登录', login(page, base, args.admin, args.admin_password))

        # ── tags-006 / tags-007：资料库根目录的已用标签栏 ──
        page.goto(base + f'/library/{repo_id}/', wait_until='networkidle')
        time.sleep(4)
        used = page.locator('.used-tag-item')
        used_count = used.count()
        if used_count == 0:
            record('tags-006', False, 'used-tag-list 未渲染')
            record('tags-007', False, 'used-tag-list 未渲染')
        else:
            # tags-006: the system tag (sys-locked) carries the lock icon;
            # user tags do not.
            sys_item = used.filter(has_text='sys-locked')
            lock_on_system = sys_item.locator('.used-tag-system-lock').count() > 0
            lock_on_user = used.filter(has_text='user-a') \
                .locator('.used-tag-system-lock').count() > 0
            record('tags-006', lock_on_system and not lock_on_user,
                   f'系统标签锁形={lock_on_system} 用户标签误锁={lock_on_user}')

            # tags-007: user tags render before system tags.
            names = [used.nth(i).locator('.used-tag-name').inner_text()
                     for i in range(used_count)]
            user_idx = [i for i, n in enumerate(names) if n.startswith('user-')]
            sys_idx = [i for i, n in enumerate(names) if n == 'sys-locked']
            ordered = (bool(user_idx) and bool(sys_idx)
                       and max(user_idx) < min(sys_idx))
            record('tags-007', ordered, f'渲染顺序={names}')

        # ── tags-008：目录表格 file-tags 折叠 ──
        # tagged.txt 绑了 4 枚标签（3 用户 + 1 系统），表格行应显示前两枚 + …。
        page.goto(base + f'/library/{repo_id}/', wait_until='networkidle')
        time.sleep(4)
        # 目录表格（metadata 视图）可能需要切到表格模式；先试默认视图里的
        # tags formatter，找不到再切。默认列表视图不渲染 file-tags formatter，
        # 该组件只在 metadata 表格（sf-metadata）里使用。
        page.locator('.dir-item-name, .dirent-name').first
        formatter = page.locator('.tags-formatter')
        fold_ok = False
        detail = '未找到 tags-formatter（需要 metadata 表格视图）'
        # 尝试切换到表格视图（toolbar 的 view-mode 菜单）
        try:
            page.click('#view-mode-btn, .view-mode-toggler', timeout=3000)
            page.get_by_text('Table view', exact=True).click(timeout=3000)
            time.sleep(3)
        except Exception:
            pass
        formatter = page.locator('.tags-formatter')
        if formatter.count() > 0:
            row = formatter.first
            dots = row.locator('.sf-metadata-ui-tag-more')
            visible = row.locator('.sf-metadata-ui-tag-color, .sf-metadata-ui-tag')
            fold_ok = dots.count() > 0 and visible.count() <= 2
            detail = f'可见标签={visible.count()} 省略号={dots.count()}'
        record('tags-008', fold_ok, detail)

        # ── tags-009：点击标签树节点仅选中，不弹关联文件列表 ──
        # 标签树在左侧 side-panel（Tags 入口），节点可见后才可点。
        node = page.locator('.side-panel .tree-node:visible').first
        if node.count() == 0:
            # 侧栏可能折叠，先展开 Tags 面板
            try:
                page.get_by_text('Tags', exact=True).first.click(timeout=3000)
                time.sleep(2)
            except Exception:
                pass
            node = page.locator('.side-panel .tree-node:visible').first
        clicked = False
        no_dialog = True
        detail = '未找到可见标签树节点'
        if node.count() > 0:
            node.click()
            clicked = True
            time.sleep(2)
            # 弹窗判定：ListTaggedFilesDialog 的 modal 容器
            no_dialog = page.locator('.modal, [role="dialog"]').count() == 0
            detail = f'点击后弹窗={not no_dialog}'
        record('tags-009', clicked and no_dialog, detail)

        browser.close()

    failed = [c for c, ok in results if not ok]
    print(f'UI 标签门禁 {len(results) - len(failed)}/{len(results)} 通过')
    return 1 if failed else 0

if __name__ == '__main__':
    sys.exit(main())
