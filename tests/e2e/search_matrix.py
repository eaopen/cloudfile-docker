#!/usr/bin/env python3
"""检索端到端门禁：默认 SeaSearch 路径可用，切到 Meilisearch 后结果一致，关闭
开关后恢复原生行为。

三阶段，跨两次配置变更（由 verify-local.sh 的 cap_search_run 或
search-e2e.yml 编排，这份脚本本身不改配置、不重启容器）：

    phase 1 —— CF_ENABLE_SEARCH=true、CF_PROVIDER_SEARCH 留空（默认，走
               upstream 自己的 SeaSearch 分支，seahub.api2.views.Search.get()
               的 elif HAS_FILE_SEASEARCH，见 docs/search.md）。建库、上传两个
               带独立关键词的文件，轮询直到 SeaSearch 完成索引，验证按关键词
               能分别搜到各自的文件（不是"搜到了任意结果"）。这条门禁真正验证
               的是 P0 唯一的新代码：两个接口的 Pro 门被正确解除——SeaSearch
               本身的索引/查询是上游代码，不是本仓库要证明正确性的对象。

    phase 2 —— （编排层已切到 CF_PROVIDER_SEARCH=meilisearch 并跑过一轮
               cf_worker --once）验证 phase 1 建的两个文件通过 Meilisearch
               仍能各自搜到——这证明索引器不仅能追新提交，也能回填切换前就
               存在的历史提交（index_tick() 从水位线 0 开始走，backfill 和
               实时索引走的是同一条代码路径，所以这一项等于两项都测了）。

    phase 3 —— （编排层已把 CF_ENABLE_SEARCH 改回 false 并重启）验证两个入口
               恢复到原生 CE 行为：403（IsProVersion 拒绝），不是 200 也不是
               500——这是铁律"开关关闭=原生 CE"在检索这条能力上的验收点，也是
               write_seafevents_search_config() 从"只在首次安装执行"改成
               "每次启动都执行"这个改动本身要证明的事：开关反复切换必须真的
               生效，而不是被 init_seafile_server() 提前返回吃掉。

矩阵同时建立跨用户 rw 共享，以及 invisible 和 none 两种目录 ACL，用
同一关键词的可见/隐藏/无权文件做对照，分别在 SeaSearch 与 Meilisearch
路径断言目录 ACL 零泄漏。管理员必须先能搜到全部对照文件，避免“隐藏
文件未被索引”的假阳性。
"""

import argparse
import json
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

REPO_PREFIX = 'search-matrix-'
B_EMAIL = 'search-matrix-b@example.com'
B_PASSWORD = 'SearchMatrix-B-7142'
#: SeaSearch 的索引间隔由编排层设成短值（CF_SEASEARCH_INTERVAL），但仍是异步
#: 的；Meilisearch 那一侧编排层显式跑过 cf_worker --once，同步完成，不需要轮询。
# SeaSearch's updater runs asynchronously.  In a cold CI image its first scan
# can take longer than one interval, so leave enough time for the service to
# discover both freshly-created commits before treating it as a failure.
POLL_SECONDS = 120

def request(url, method='GET', token=None, form=None, data=None, headers=None,
           context=None):
    hdrs = dict(headers or {})
    body = None
    if token:
        hdrs['Authorization'] = 'Token ' + token
    if form is not None:
        body = urllib.parse.urlencode(form).encode()
        hdrs['Content-Type'] = 'application/x-www-form-urlencoded'
    elif data is not None:
        body = data if isinstance(data, bytes) else data.encode()
    req = urllib.request.Request(url, data=body, method=method, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=60, context=context) as response:
            return response.status, response.read().decode(errors='replace')
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode(errors='replace')
    except Exception as error:
        return 0, str(error)


def json_body(body):
    try:
        return json.loads(body)
    except (TypeError, ValueError):
        return {}


def multipart(fields, filename, content):
    boundary = '----CloudFileSearch' + uuid.uuid4().hex
    chunks = []
    for key, value in fields.items():
        chunks.append('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n'
                      % (boundary, key, value))
    chunks.append('--%s\r\nContent-Disposition: form-data; name="file"; '
                  'filename="%s"\r\nContent-Type: text/plain\r\n\r\n'
                  % (boundary, filename))
    body = ''.join(chunks).encode() + content + ('\r\n--%s--\r\n' % boundary).encode()
    return body, 'multipart/form-data; boundary=' + boundary


def check(name, ok, detail=''):
    print('  %s %s%s' % ('✓' if ok else '✗', name,
                         ('\n      ' + detail) if detail and not ok else ''),
          flush=True)
    return ok


def login(base, admin, password, context):
    status, body = request(base + '/api2/auth-token/', method='POST',
                           form={'username': admin, 'password': password},
                           context=context)
    return json_body(body).get('token'), status, body


def upload(base, token, repo_id, filename, content, context, parent_dir='/'):
    status, body = request(base + '/api2/repos/%s/upload-link/?p=%s' %
                           (repo_id, urllib.parse.quote(parent_dir)),
                           token=token, context=context)
    upload_url = body.strip('"')
    if status != 200 or not upload_url.startswith('http'):
        return False, 'status=%s %s' % (status, body[:200])
    data, ctype = multipart({'parent_dir': parent_dir, 'replace': '1'}, filename,
                            content.encode('utf-8'))
    status, body = request(upload_url, method='POST', token=token, data=data,
                           headers={'Content-Type': ctype}, context=context)
    return status == 200, 'status=%s %s' % (status, body[:200])


def search(base, token, keyword, context, search_filename_only=False):
    params = {'q': keyword, 'per_page': '20'}
    if search_filename_only:
        params['search_filename_only'] = 'true'
    status, body = request(base + '/api2/search/?' + urllib.parse.urlencode(params),
                           token=token, context=context)
    return status, json_body(body), body


def search_until_found(base, token, keyword, context, deadline_seconds):
    """Poll for an async indexer to catch up. Returns the last (status, parsed, raw)."""
    deadline = time.time() + deadline_seconds
    status, parsed, raw = 0, {}, ''
    while time.time() < deadline:
        status, parsed, raw = search(base, token, keyword, context)
        names = [r.get('name') for r in parsed.get('results', [])]
        if status == 200 and names:
            return status, parsed, raw
        time.sleep(2)
    return status, parsed, raw


def result_names(parsed):
    return sorted(r.get('name') for r in parsed.get('results', []))


def resolve_identity(base, token, email, context):
    status, body = request(base + '/api/v2.1/admin/users/', token=token,
                           context=context)
    for user in json_body(body).get('data', []):
        if email in (user.get('email'), user.get('contact_email'),
                     user.get('login_id')):
            return user.get('email')
        if user.get('name') == email.split('@')[0]:
            return user.get('email')
    return None


def check_acl_search(base, token, marker, visible_name, hidden_names, context,
                     backend):
    status, parsed, raw = search_until_found(base, token, marker, context,
                                              POLL_SECONDS)
    names = result_names(parsed)
    if isinstance(hidden_names, str):
        hidden_names = [hidden_names]
    leaks = [n for n in hidden_names if n in names]
    return check(
        '%s 检索遵守目录 ACL：可读命中、invisible/none 零泄漏' % backend,
        status == 200 and visible_name in names and not leaks,
        'status=%s names=%s body=%s' % (status, names, raw[:300]))


def phase1(base, admin, password, context, state_file):
    token, status, body = login(base, admin, password, context)
    if not check('管理员登录', bool(token), 'status=%s %s' % (status, body[:200])):
        return False

    repo_name = REPO_PREFIX + uuid.uuid4().hex[:8]
    status, body = request(base + '/api2/repos/', method='POST', token=token,
                           form={'name': repo_name}, context=context)
    repo_id = json_body(body).get('repo_id')
    if not check('创建资料库', bool(repo_id), 'status=%s %s' % (status, body[:200])):
        return False

    tag = uuid.uuid4().hex[:12]
    alpha_marker, beta_marker = 'cfsearch-alpha-' + tag, 'cfsearch-beta-' + tag
    alpha_name, beta_name = 'search-matrix-alpha-%s.txt' % tag, 'search-matrix-beta-%s.txt' % tag

    passed = check('未登录请求需要认证',
                   request(base + '/api2/search/?q=x', context=context)[0] in (401, 403))

    ok, detail = upload(base, token, repo_id, alpha_name,
                        'first file, marker %s\n' % alpha_marker, context)
    passed &= check('上传 alpha 文件', ok, detail)
    ok, detail = upload(base, token, repo_id, beta_name,
                        'second file, marker %s\n' % beta_marker, context)
    passed &= check('上传 beta 文件', ok, detail)

    # 跨用户 ACL 场景。两个文件使用同一关键词，只有路径可见性
    # 能将它们区分；不能用“搜到了任意结果”蒙混过关。
    status, body = request(base + '/api/v2.1/admin/users/', method='POST',
                           token=token,
                           form={'email': B_EMAIL, 'password': B_PASSWORD},
                           context=context)
    if status not in (200, 201) and 'exist' not in body.lower():
        return check('创建 ACL 验收用户', False,
                     'status=%s %s' % (status, body[:200]))
    b_token, status, body = login(base, B_EMAIL, B_PASSWORD, context)
    if not b_token:
        return check('ACL 验收用户登录', False,
                     'status=%s %s' % (status, body[:200]))
    b_id = resolve_identity(base, token, B_EMAIL, context)
    if not b_id:
        return check('解析 ACL 验收用户身份', False)
    for folder in ('visible', 'hidden', 'noperm'):
        request(base + '/api2/repos/%s/dir/?p=/%s' % (repo_id, folder),
                method='POST', token=token, form={'operation': 'mkdir'},
                context=context)
    acl_marker = 'cfsearch-acl-' + tag
    visible_name = 'acl-visible-%s.txt' % tag
    hidden_name = 'acl-hidden-%s.txt' % tag
    noperm_name = 'acl-noperm-%s.txt' % tag
    ok, detail = upload(base, token, repo_id, visible_name,
                        'shared marker %s\n' % acl_marker, context, '/visible')
    passed &= check('上传 ACL 可见文件', ok, detail)
    ok, detail = upload(base, token, repo_id, hidden_name,
                        'shared marker %s\n' % acl_marker, context, '/hidden')
    passed &= check('上传 ACL 隐藏文件', ok, detail)
    ok, detail = upload(base, token, repo_id, noperm_name,
                        'shared marker %s\n' % acl_marker, context, '/noperm')
    passed &= check('上传 ACL 无权文件', ok, detail)
    status, body = request(
        base + '/api2/repos/%s/dir/shared_items/?p=/' % repo_id,
        method='PUT', token=token,
        form={'share_type': 'user', 'username': b_id, 'permission': 'rw'},
        context=context)
    passed &= check('资料库以 rw 共享给 ACL 验收用户',
                    status == 200 and not json_body(body).get('failed'),
                    'status=%s %s' % (status, body[:300]))
    status, body = request(
        base + '/api/v2.1/cloudfile/repos/%s/dir-acl/' % repo_id,
        method='POST', token=token,
        form={'path': '/hidden', 'subject_type': 'user',
              'subject': B_EMAIL, 'permission': 'invisible',
              'inherit': 'true'}, context=context)
    passed &= check('下发 invisible 目录 ACL', status == 200,
                    'status=%s %s' % (status, body[:300]))
    status, body = request(
        base + '/api/v2.1/cloudfile/repos/%s/dir-acl/' % repo_id,
        method='POST', token=token,
        form={'path': '/noperm', 'subject_type': 'user',
              'subject': B_EMAIL, 'permission': 'none',
              'inherit': 'true'}, context=context)
    passed &= check('下发 none 目录 ACL', status == 200,
                    'status=%s %s' % (status, body[:300]))

    status, parsed, raw = search_until_found(base, token, alpha_marker, context, POLL_SECONDS)
    passed &= check('搜索 alpha 关键词只命中 alpha 文件（默认 SeaSearch 路径）',
                    status == 200 and result_names(parsed) == [alpha_name],
                    'status=%s names=%s body=%s' % (status, result_names(parsed), raw[:200]))

    status, parsed, raw = search_until_found(base, token, beta_marker, context, POLL_SECONDS)
    passed &= check('搜索 beta 关键词只命中 beta 文件（默认 SeaSearch 路径）',
                    status == 200 and result_names(parsed) == [beta_name],
                    'status=%s names=%s body=%s' % (status, result_names(parsed), raw[:200]))

    # 先等管理员能搜到两个同关键词文件，证明隐藏文件确实进了
    # 索引，再断言 B 的结果被查询层过滤，避免“根本没索引”假阳性。
    status, parsed, raw = search_until_found(base, token, acl_marker, context,
                                              POLL_SECONDS)
    names = result_names(parsed)
    passed &= check('SeaSearch 索引中同时存在 ACL 三个对照文件',
                    status == 200 and visible_name in names
                    and hidden_name in names and noperm_name in names,
                    'status=%s names=%s body=%s' % (status, names, raw[:300]))
    passed &= check_acl_search(base, b_token, acl_marker, visible_name,
                               [hidden_name, noperm_name], context, 'SeaSearch')

    if passed:
        with open(state_file, 'w') as fh:
            json.dump({'repo_id': repo_id, 'alpha_marker': alpha_marker,
                      'alpha_name': alpha_name, 'beta_marker': beta_marker,
                      'beta_name': beta_name, 'acl_marker': acl_marker,
                      'visible_name': visible_name,
                      'hidden_name': hidden_name,
                      'noperm_name': noperm_name}, fh)

    print('\n════════ phase 1 %s ════════' % ('通过' if passed else '失败'))
    return passed


def phase2(base, admin, password, context, state_file):
    try:
        with open(state_file) as fh:
            state = json.load(fh)
    except (OSError, ValueError) as error:
        check('读取 phase 1 状态文件', False, str(error))
        return False

    token, status, body = login(base, admin, password, context)
    if not check('管理员登录', bool(token), 'status=%s %s' % (status, body[:200])):
        return False

    status, parsed, raw = search(base, token, state['alpha_marker'], context)
    passed = check('Meilisearch 回填了切换前就存在的 alpha 文件',
                   status == 200 and result_names(parsed) == [state['alpha_name']],
                   'status=%s names=%s body=%s' % (status, result_names(parsed), raw[:200]))

    status, parsed, raw = search(base, token, state['beta_marker'], context)
    passed &= check('Meilisearch 回填了切换前就存在的 beta 文件',
                    status == 200 and result_names(parsed) == [state['beta_name']],
                    'status=%s names=%s body=%s' % (status, result_names(parsed), raw[:200]))

    status, parsed, raw = search(base, token, 'cfsearch-nonexistent-' + uuid.uuid4().hex, context)
    passed &= check('不存在的关键词不返回任何结果（无假阳性）',
                    status == 200 and not parsed.get('results'),
                    'status=%s body=%s' % (status, raw[:200]))

    b_token, status, body = login(base, B_EMAIL, B_PASSWORD, context)
    passed &= check('ACL 验收用户登录', bool(b_token),
                    'status=%s %s' % (status, body[:200]))
    if b_token:
        passed &= check_acl_search(
            base, b_token, state['acl_marker'], state['visible_name'],
            [state['hidden_name'], state['noperm_name']], context,
            'Meilisearch')

    print('\n════════ phase 2 %s ════════' % ('通过' if passed else '失败'))
    return passed


def phase3(base, admin, password, context, state_file):
    token, status, body = login(base, admin, password, context)
    if not check('管理员登录', bool(token), 'status=%s %s' % (status, body[:200])):
        return False

    status, _parsed, raw = search(base, token, 'anything', context)
    passed = check('CF_ENABLE_SEARCH 关闭后恢复原生 CE 行为（403，不是 200/500）',
                   status == 403, 'status=%s body=%s' % (status, raw[:200]))

    try:
        with open(state_file) as fh:
            repo_id = json.load(fh).get('repo_id')
        if repo_id:
            request(base + '/api2/repos/%s/' % repo_id, method='DELETE', token=token,
                   context=context)
    except (OSError, ValueError):
        pass

    print('\n════════ phase 3 %s ════════' % ('通过' if passed else '失败'))
    return passed


PHASES = {1: phase1, 2: phase2, 3: phase3}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', required=True)
    parser.add_argument('--admin', required=True)
    parser.add_argument('--admin-password', required=True)
    parser.add_argument('--insecure', action='store_true')
    parser.add_argument('--phase', type=int, choices=sorted(PHASES), required=True)
    parser.add_argument('--state-file', required=True,
                        help='phase 1 写入 repo_id 与关键词；phase 2/3 读取')
    args = parser.parse_args()

    context = ssl._create_unverified_context() if args.insecure else None
    base = args.url.rstrip('/')

    ok = PHASES[args.phase](base, args.admin, args.admin_password, context,
                            args.state_file)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
