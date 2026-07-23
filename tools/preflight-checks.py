#!/usr/bin/env python3
"""静态一致性检查：专抓"只有 CI 跑起来才会炸"的那类不一致。

每一条都对应一次真实付出过代价的失败。CI 一轮 20 分钟，这些检查是秒级的。

    python3 tools/preflight-checks.py <docker_repo> <workspace>
"""

import os
import re
import subprocess
import sys

failures = []


def ok(msg):
    print(f'  \033[32m✓\033[0m {msg}')


def bad(msg, detail=''):
    failures.append(msg)
    print(f'  \033[31m✗\033[0m {msg}')
    if detail:
        for line in detail.splitlines():
            print(f'      {line}')


def read(path):
    try:
        with open(path, encoding='utf-8') as fp:
            return fp.read()
    except OSError:
        return None


def check_workflow_references(repo, wf):
    """workflow 引用的脚本必须存在。"""
    refs = sorted(set(re.findall(
        r'cloudfile-docker/(?:tests|tools|build|image)/[A-Za-z0-9_/.-]+\.(?:py|sh)', wf)))
    for ref in refs:
        rel = ref[len('cloudfile-docker/'):]
        if os.path.isfile(os.path.join(repo, rel)):
            ok(f'workflow 引用存在：{rel}')
        else:
            bad(f'workflow 引用了不存在的文件：{rel}')


def check_tls_target(wf):
    """E2E 的 URL 协议要和 Compose 的 TLS 设置一致。

    第五次 CI 栽在这里：CADDY_TLS=internal 会把 http 跳到自签 https，
    而测试打的是 http，于是卡在 CERTIFICATE_VERIFY_FAILED。
    """
    if 'CADDY_TLS=internal' not in wf:
        return
    if '--url https://' in wf and '--insecure' in wf:
        ok('TLS 设置与 E2E 目标一致（internal + https + --insecure）')
    else:
        bad('CADDY_TLS=internal 但 E2E 未走 https/--insecure')


def check_hostname(wf, workspace):
    """主机名必须能过上游 setup 脚本的校验。

    第六次 CI 栽在这里：localhost 不含点，初始化直接退出 255，
    而表面症状只是 Caddy 502——从症状根本看不出原因。
    """
    # workflow 里这个名字出现两次，都在同一条 sed 上：
    #   sed -i "s|^SEAFILE_SERVER_HOSTNAME=.*|SEAFILE_SERVER_HOSTNAME=127.0.0.1|"
    # 前一处是查找模式（值为 ".*"），要的是后一处的替换值。
    candidates = [h for h in re.findall(r'SEAFILE_SERVER_HOSTNAME=([^|\s"]+)', wf)
                  if h != '.*']
    if not candidates:
        bad('workflow 里找不到 SEAFILE_SERVER_HOSTNAME 的取值')
        return
    host = candidates[-1]

    src = read(os.path.join(workspace, 'cloudfile-hub', 'scripts',
                            'setup-seafile-mysql.py'))
    if not src:
        print('  ⊘ 读不到上游 setup 脚本，跳过主机名校验')
        return

    pm = re.search(r"SERVER_IP_OR_DOMAIN_REGEX\s*=\s*r?['\"](.+?)['\"]\s*$",
                   src, re.M)
    if not pm:
        print('  ⊘ 上游正则格式变了，跳过主机名校验')
        return

    pattern = pm.group(1)
    if re.match(pattern, host):
        ok(f'主机名 {host} 可通过上游校验')
    else:
        bad(f'主机名 {host} 不满足上游 {pattern}',
            '初始化会退出 255，症状表现为 Caddy 502')


def check_node_pin(repo, workspace):
    """构建必须固定 Node 版本，不能依赖发行版自带的。

    本地首跑栽在这里：Ubuntu 24.04 的 apt nodejs 是 18.19.1，而 seahub 前端
    需要 20+（css-minimizer 用全局 crypto，Node 19 才有），构建以
    "ReferenceError: crypto is not defined" 失败。CI 上却是绿的——GitHub
    runner 预装了 Node 20+ 且排在 PATH 前面。也就是说 CI 绿灯掩盖了构建不可
    复现，任何人在干净容器里都构建不出来。
    """
    build = read(os.path.join(repo, 'build', 'cloudfile_14.0',
                              'cloudfile-build.sh'))
    if not build:
        bad('读不到 cloudfile-build.sh')
        return

    if re.search(r'^\s+nodejs\s*\\?\s*$', build, re.M):
        bad('构建脚本用 apt 装 nodejs',
            'apt 给的是 Node 18，seahub 前端需要 20+；改为固定版本安装')
        return

    m = re.search(r'NODE_VERSION=\$\{CF_NODE_VERSION:-([0-9]+)\.', build)
    if not m:
        bad('构建脚本没有固定 Node 版本')
        return

    major = int(m.group(1))

    # 与上游 seahub CI 要求的大版本对齐
    wanted = None
    dist = read(os.path.join(workspace, 'cloudfile-hub', '.github',
                             'workflows', 'dist.yml'))
    if dist:
        dm = re.search(r"node-version:\s*['\"]?(\d+)", dist)
        if dm:
            wanted = int(dm.group(1))

    if wanted and major < wanted:
        bad(f'Node 固定为 {major}.x，低于上游要求的 {wanted}.x')
    elif wanted:
        ok(f'Node 固定为 {major}.x，满足上游要求的 {wanted}.x')
    else:
        ok(f'Node 固定为 {major}.x')


def check_seahub_settings_block(repo):
    """写进 seahub_settings.py 的内容只能是自包含的赋值。

    栽过一次：bootstrap 写了 ``DATABASES['cloudfile'] = {...}``，但
    seahub_settings.py 是被当作**普通模块** import 的——seahub 的
    load_local_settings() 事后才去拷贝其中的大写名字——所以它的命名空间里根本
    没有 DATABASES。结果是 NameError，seahub 捕获后只记一行日志，**整个文件
    的 CloudFile 配置全被丢弃**，扩展框架压根没装上，而表面上服务是正常起来的。

    这类错误只在真跑起来时才显形，且症状（能力接口 404）离原因很远。
    """
    boot = read(os.path.join(repo, 'scripts', 'scripts_14.0', 'bootstrap.py'))
    if not boot:
        bad('读不到 bootstrap.py')
        return

    # 写进 seahub_settings.py 的**全部**片段，不只是主函数那一段。
    #
    # 能力多起来之后 body 是拼出来的（`body += _settings_block_sso()`），
    # 只查主函数等于查了个越来越小的子集——而一个不再覆盖被监视对象的检查，
    # 比没有检查更危险，因为它读起来像覆盖。约定：凡是往 body 里拼的助手都叫
    # `_settings_block_*`，这里连它们一起查。
    chunks = []
    m = re.search(r'def write_cloudfile_settings\(\):(.*?)\n    _replace_block',
                  boot, re.S)
    if not m:
        print('  ⊘ 找不到 write_cloudfile_settings，跳过')
        return
    chunks.append(m.group(1))
    chunks += re.findall(r'\ndef _settings_block_\w+\(\):(.*?)(?=\ndef |\Z)',
                         boot, re.S)

    # 先剥掉注释：本函数的注释里正好引用了当年那行错误代码作为反面例子，
    # 不剥的话检查会拿自己的说明文字当成违规。
    body = '\n'.join(line for chunk in chunks for line in chunk.splitlines()
                     if not line.lstrip().startswith('#'))

    # 形如 FOO['bar'] = 或 FOO.setdefault( 都依赖 seahub settings 的命名空间。
    # 两种引号都要查：写出来的行既有 "..." 也有 '...'，只认一种就是留了个口子。
    offenders = sorted(set(re.findall(r'["\']\s*([A-Z_]+)\[', body)) |
                       set(re.findall(r'["\']\s*([A-Z_]+)\.\w+\(', body)))
    if offenders:
        bad(f'seahub_settings.py 段落引用了未定义的名字：{offenders}',
            '该文件是独立模块，没有 seahub 的 settings 命名空间；\n'
            '改为写标量，再在 CloudFileConfig.ready() 里组装')
    else:
        ok('seahub_settings.py 段落只含自包含赋值')


def check_switch_lists(repo, workspace):
    """开关清单三处必须一致。"""
    sources = {
        'bootstrap.py': (
            os.path.join(repo, 'scripts', 'scripts_14.0', 'bootstrap.py'),
            r"'(CF_ENABLE_\w+)'"),
        '.env.example': (
            os.path.join(repo, 'deploy', 'compose', '.env.example'),
            r'^(CF_ENABLE_\w+)='),
        'features.py': (
            os.path.join(workspace, 'cloudfile-hub', 'cloudfile_ext',
                         'features.py'),
            r"'(CF_ENABLE_\w+)'"),
    }

    found = {}
    for name, (path, pattern) in sources.items():
        text = read(path)
        if text is None:
            continue
        # re.M 是必需的：'^CF_ENABLE_...' 没有它只会匹配文件开头，
        # 于是这个检查永远报"一致"。第一版就栽在这里。
        found[name] = set(re.findall(pattern, text, re.M))

    if len(found) < 2:
        print('  ⊘ 可比对的来源不足，跳过开关清单检查')
        return

    reference = next(iter(found.values()))
    diffs = {n: sorted(v ^ reference) for n, v in found.items()
             if v != reference}
    if diffs:
        bad('开关清单不一致',
            '\n'.join(f'{n} 差异: {d}' for n, d in diffs.items()))
    else:
        ok(f'开关清单三处一致（{len(reference)} 个）')


def check_extension_points_documented(repo, workspace):
    """registry.py 声明的每个扩展点都要在 EXTENSION-POINTS.md 的矩阵里。

    扩展点最容易出的问题不是写错，而是**加了却没人知道**——于是下一个特性
    又去改上游文件，而它要的钩子其实早就有了。这个检查把"加扩展点"和
    "登记扩展点"绑在一起。
    """
    registry = read(os.path.join(workspace, 'cloudfile-hub', 'cloudfile_ext',
                                 'registry.py'))
    doc = read(os.path.join(repo, 'docs', 'EXTENSION-POINTS.md'))
    if not registry or not doc:
        print('  ⊘ 读不到 registry.py 或 EXTENSION-POINTS.md，跳过')
        return

    declared = set(re.findall(r'def (register_\w+)\(self', registry))
    # register_provider 是通用机制，kind 由能力自己声明，不逐个登记
    declared.discard('register_provider')

    # 必须按词边界匹配，不能用 `n in doc`：register_search_indexer 是
    # register_search_indexerX 的子串，于是文档里写错名字时检查照样报"已登记"。
    # 第一版就是这么写的，变异测试当场抓出来。
    missing = sorted(n for n in declared
                     if not re.search(r'%s\b' % re.escape(n), doc))
    if missing:
        bad(f'扩展点未登记到 EXTENSION-POINTS.md：{missing}',
            '扩展点加了却没登记，下一个特性会重复去改上游文件')
    else:
        ok(f'{len(declared)} 个扩展点均已登记')


def check_capability_gates(repo):
    """每个能力的本地门禁与 CI 门禁必须成对存在。

    verify-local.sh 存在的全部理由是"不要再手抄 <能力>-e2e.yml"——而只抄了一半
    正是它要防的事：acl_matrix.py 缺 --insecure 就是这么留下来的。两边缺任何
    一边，本地和 CI 就在验不同的东西，而且没有任何信号。
    """
    script = read(os.path.join(repo, 'tools', 'verify-local.sh'))
    if not script:
        print('  ⊘ 读不到 verify-local.sh，跳过')
        return

    block = re.search(r'CAPABILITIES=\((.*?)\n\)', script, re.S)
    if not block:
        bad('verify-local.sh 里找不到 CAPABILITIES 表')
        return

    local = set(re.findall(r'"(\w+)\|', block.group(1)))

    wf_dir = os.path.join(repo, '.github', 'workflows')
    names = os.listdir(wf_dir) if os.path.isdir(wf_dir) else []
    ci = {n[:-len('-e2e.yml')] for n in names if n.endswith('-e2e.yml')}
    # 基线门禁不是能力门禁：它测的正是"一个能力都没启用"。
    ci.discard('build-and')

    if local != ci:
        bad(f'能力门禁两边不一致：本地 {sorted(local)} / CI {sorted(ci)}',
            '一个能力要么两边都有，要么两边都没有；\n'
            '只有一边时，本地跑绿了并不代表 CI 在验同一件事')
    else:
        ok(f'{len(local)} 个能力门禁本地与 CI 成对（{", ".join(sorted(local))}）')


def check_features_doc_freshness(repo):
    """FEATURES.md 不能明显落后于它所描述的代码。

    栽过一次（不是构建失败，是更隐蔽的一类）：基线跑通之后，FEATURES.md 仍然
    写着"完整镜像从未成功构建过。所有 🟡 项的共同前提都是它"，而那时它已经
    构建过、起过栈、跑过 12/12 冒烟。任何照着文档排期的人都会把力气花错地方。

    文档自己写了"把未验证的标成已完成，是这份文档唯一会失去价值的方式"——
    反过来同样成立。
    """
    doc_rel = 'docs/FEATURES.md'
    # 只盯"一改动就意味着某个特性状态变了"的路径。
    #
    # 刻意不含 tools/：改一次 preflight 自己就要求更新特性表，是纯噪音，
    # 而会误报的硬门禁最后一定会被人关掉——那比没有这个检查更糟。
    watched = ['tests/e2e/', 'build/cloudfile_14.0/', 'image/',
               'scripts/scripts_14.0/']

    def last_commit(path):
        try:
            out = subprocess.run(
                ['git', '-C', repo, 'log', '-1', '--format=%ct', '--', path],
                capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            return None
        out = out.stdout.strip()
        return int(out) if out.isdigit() else None

    doc_at = last_commit(doc_rel)
    if doc_at is None:
        print('  ⊘ 取不到 FEATURES.md 的提交时间（非 git 或未提交），跳过')
        return

    stale = []
    for path in watched:
        at = last_commit(path)
        if at is not None and at > doc_at:
            stale.append(path)

    if stale:
        bad(f'FEATURES.md 落后于 {stale}',
            '代码已经前进而状态表没跟上。照着旧文档排期会把力气花错地方——\n'
            '基线跑通那次就是这样：文档仍写着"镜像从未构建过"。')
    else:
        ok('FEATURES.md 不落后于代码')


def stack_workflows(repo):
    """起栈跑 E2E 的 workflow，按文件名排序。

    刻意不写死 build-and-e2e.yml：每加一条能力门禁（acl-e2e.yml 及其后继），
    它都要重新踩一遍同样的集成边界——TLS、主机名、脚本路径。第一版只查基线那
    一条，于是 acl-e2e.yml 少了 --insecure 这个错误是人工发现的，而这恰好是
    本文件存在的理由。凡是 `docker compose up` 的 workflow 都要过同一套检查。
    """
    wf_dir = os.path.join(repo, '.github', 'workflows')
    found = []
    for name in sorted(os.listdir(wf_dir)) if os.path.isdir(wf_dir) else []:
        if not name.endswith(('.yml', '.yaml')):
            continue
        text = read(os.path.join(wf_dir, name))
        if text and 'docker compose up' in text:
            found.append((name, text))
    return found


def main():
    if len(sys.argv) != 3:
        sys.stderr.write(__doc__)
        return 2

    repo, workspace = sys.argv[1], sys.argv[2]

    workflows = stack_workflows(repo)
    if not workflows:
        bad('找不到任何起栈的 workflow')
        return 1

    for name, wf in workflows:
        print(f'  ── {name}')
        check_workflow_references(repo, wf)
        check_tls_target(wf)
        check_hostname(wf, workspace)

    check_node_pin(repo, workspace)
    check_seahub_settings_block(repo)
    check_switch_lists(repo, workspace)
    check_extension_points_documented(repo, workspace)
    check_capability_gates(repo)
    check_features_doc_freshness(repo)

    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
