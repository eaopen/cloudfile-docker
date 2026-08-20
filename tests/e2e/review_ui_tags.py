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

    # tags-008 的折叠组件（FileTagsFormatter）消费的是 metadata 记录的
    # _tags 字段（metadata-server 标签表 + 记录链接），不是上面的
    # repo_tags/FileTags 通路。因此再建 3 枚 metadata 标签并通过
    # PUT /metadata/file-tags/ 链到 tagged.txt 的记录上。
    status, body = ctx.api(f'/api/v2.1/repos/{repo_id}/metadata/tags/',
                           method='POST', token=admin_token,
                           data=json.dumps({'tags_data': [
                               {'_tag_name': f'm-user-{s}', '_tag_color': '#aa00aa'}
                               for s in 'abc']}).encode(),
                           headers={'Content-Type': 'application/json'})
    if status != 200:
        print(f'✗ 创建 metadata 标签失败 status={status} {body[:120]}', file=sys.stderr)
        return 1
    # 记录 id：先取默认视图 id，再按视图查行。新库的记录由 metadata-server
    # 异步建索引，立刻查可能为空——轮询重试。
    status, body = ctx.api(f'/api/v2.1/repos/{repo_id}/metadata/views/',
                           token=admin_token)
    views = (json.loads(body).get('views') or []) if status == 200 else []
    view_id = views[0]['_id'] if views else ''
    record_id = None
    for _ in range(12):
        status, body = ctx.api(f'/api/v2.1/repos/{repo_id}/metadata/records/'
                               f'?view_id={view_id}', token=admin_token)
        if status == 200:
            for row in json.loads(body).get('results', []):
                if row.get('_name') == 'tagged.txt' and not row.get('_is_dir'):
                    record_id = row.get('_id')
                    break
        if record_id:
            break
        time.sleep(5)
    if not record_id:
        print(f'✗ 未找到 tagged.txt 的 metadata 记录（重试 12 次）status={status}',
              file=sys.stderr)
        return 1
    status, body = ctx.api(f'/api/v2.1/repos/{repo_id}/metadata/tags/',
                           token=admin_token)
    tag_ids = [t['_id'] for t in json.loads(body).get('results', [])
               if str(t.get('_tag_name', '')).startswith('m-user-')]
    if len(tag_ids) < 3:
        print(f'✗ metadata 标签不足: {tag_ids}', file=sys.stderr)
        return 1
    status, body = ctx.api(f'/api/v2.1/repos/{repo_id}/metadata/file-tags/',
                           method='PUT', token=admin_token,
                           data=json.dumps({'file_tags_data': [
                               {'record_id': record_id, 'tags': tag_ids}]}).encode(),
                           headers={'Content-Type': 'application/json'})
    if status != 200:
        print(f'✗ 链接 metadata 标签失败 status={status} {body[:120]}', file=sys.stderr)
        return 1

    results = []

    def record(case_id, ok, detail=''):
        results.append((case_id, ok))
        print(f'  {"✓" if ok else "✗"} [{case_id}]  {detail}', flush=True)

    # 真实用户入口是 /library/<repo_id>/<repo_name>/。不带库名段的
    # /library/<repo_id>/ 会把前端 state.path 解析成 ''，已用标签栏的
    # 渲染判定（path === '/'）因此失败——那不是产品缺陷，是测试入口不对。
    repo_url = base + f'/library/{repo_id}/{REPO_NAME}/'

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not args.headful)
        page = browser.new_page(ignore_https_errors=True,
                                viewport={'width': 1440, 'height': 900})
        record('登录', login(page, base, args.admin, args.admin_password))

        # ── tags-006 / tags-007：资料库根目录的已用标签栏 ──
        page.goto(repo_url, wait_until='networkidle')
        time.sleep(5)
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

        # ── tags-008：file-tags 折叠 ──
        # tagged.txt 绑了 4 枚标签（3 用户 + 1 系统），行内应显示前两枚 + …。
        # file-tags formatter 在列表视图（dirent-list-item.js）渲染，但 Tags 列
        # 默认隐藏（LIST_VIEW_HIDDEN_COLUMNS_DEFAULT）；先把该库的
        # dir_hidden_column_keys_<repo_id> 置为不含 tags 再加载。
        fold_ok = False
        detail = '未找到 tags-formatter'
        try:
            page.evaluate(
                "(rid) => localStorage.setItem('dir_hidden_column_keys_' + rid, "
                "JSON.stringify(['modifier', 'creator']))",
                repo_id)
            page.goto(repo_url, wait_until='networkidle')
            time.sleep(5)
            formatter = page.locator('.tags-formatter')
            if formatter.count() > 0:
                row = formatter.first
                dots = row.locator('.sf-metadata-ui-tag-more')
                visible = row.locator('.sf-metadata-ui-tag-color, .sf-metadata-ui-tag')
                fold_ok = dots.count() > 0 and visible.count() <= 2
                detail = f'可见标签={visible.count()} 省略号={dots.count()}'
            else:
                detail = 'Tags 列已显示但 formatter 未渲染（metadata[TAGS] 未填充？）'
        except Exception as e:
            detail = f'加载异常: {str(e)[:80]}'
        record('tags-008', fold_ok, detail)

        # ── tags-009：点击标签树节点仅选中，不弹关联文件列表 ──
        # 侧栏标签树（metadata 开启时出现）：Files/All files、Tags/All tags。
        page.goto(repo_url, wait_until='networkidle')
        time.sleep(4)
        node = page.locator('.tree-node-inner', has_text='All tags').first
        clicked = False
        no_dialog = True
        detail = '未找到 All tags 树节点'
        if node.count() > 0:
            node.click()
            clicked = True
            time.sleep(3)
            # 弹窗判定：ListTaggedFilesDialog 的 modal 容器
            no_dialog = page.locator('.modal.show, [role="dialog"]').count() == 0
            detail = f'点击后弹窗={not no_dialog} url={page.url[-40:]}'
        record('tags-009', clicked and no_dialog, detail)

        browser.close()

    failed = [c for c, ok in results if not ok]
    print(f'UI 标签门禁 {len(results) - len(failed)}/{len(results)} 通过')
    return 1 if failed else 0

if __name__ == '__main__':
    sys.exit(main())
