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


def check_branch_ref_is_remote(repo):
    """增量构建不能静默复用旧的本地同名分支。"""
    build = read(os.path.join(repo, 'build', 'cloudfile_14.0',
                              'cloudfile-build.sh'))
    if not build:
        print('  ⊘ 读不到 cloudfile-build.sh，跳过分支检出校验')
        return

    required = ('git fetch --no-tags origin "$ref"', 'target=FETCH_HEAD')
    # 8-15 构建加速提交把清理合并成一行：先删 seafile-server 再删
    # seafile-server-${version}。这里只要求"rm -rf 后出现版本化发行目录"这一
    # 意图，别用整行字面量匹配——否则未来再调整清理顺序又会误报。
    cleans_release = re.search(
        r'rm -rf .*"\$\{current_dir\}/seafile-server-\$\{version\}"', build)
    if all(fragment in build for fragment in required) and cleans_release:
        ok('构建分支使用远端 tip，重建前清理旧发行包')
    else:
        bad('构建分支或发行目录可能复用旧产物',
            '可变 ref 必须 fetch 后检出 FETCH_HEAD，并在重建前清理旧发行目录。')


def check_offline_image_build(repo):
    """日常应用镜像构建不能退回公网依赖或隐式拉取。"""
    dockerfile = read(os.path.join(repo, 'image', 'cloudfile_14.0',
                                   'Dockerfile'))
    build_script = read(os.path.join(repo, 'image', 'cloudfile_14.0',
                                     'docker-build.sh'))
    source_script = read(os.path.join(repo, 'build', 'cloudfile_14.0',
                                      'build-in-docker.sh'))
    basefile = read(os.path.join(repo, 'image', 'cloudfile_14.0',
                                 'Dockerfile.base'))
    if not all((dockerfile, build_script, source_script, basefile)):
        bad('离线镜像构建文件不完整')
        return

    forbidden = re.findall(
        r'^\s*(?:RUN\s+.*)?\b(?:apt-get|pip3?|npm|curl|wget)\b',
        dockerfile, re.M)
    if forbidden:
        bad('应用 Dockerfile 仍包含联网安装命令', '\n'.join(forbidden))
    elif not re.search(r'^FROM\s+\$\{CLOUDFILE_BASE\}', dockerfile, re.M):
        bad('应用 Dockerfile 未使用预制 CLOUDFILE_BASE')
    else:
        ok('应用 Dockerfile 只从预制基础镜像组装')

    required = ('docker image inspect', '--pull=false', '--network=none',
                '--build-context cloudfile_dist=', '--build-arg CLOUDFILE_BASE=')
    if all(part in build_script for part in required):
        ok('应用镜像构建禁止隐式拉取和构建期联网')
    else:
        bad('docker-build.sh 缺少离线保护',
            '必须检查本地基础镜像，并使用 --pull=false --network=none。')

    direct_ubuntu = re.search(r'^\s+ubuntu:24\.04\s*\\?$', source_script, re.M)
    if '--pull=never' in source_script and not direct_ubuntu:
        ok('源码构建容器复用基础镜像且禁止隐式拉取')
    else:
        bad('源码构建容器仍可能直接拉取 Ubuntu')


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


def check_local_capabilities(repo):
    """本地能力表必须指向存在的矩阵脚本。

    能力验收只在开发者本机运行，不在 GitHub Actions 中重复构建整套镜像。
    """
    script = read(os.path.join(repo, 'tools', 'verify-local.sh'))
    if not script:
        print('  ⊘ 读不到 verify-local.sh，跳过')
        return

    block = re.search(r'CAPABILITIES=\((.*?)\n\)', script, re.S)
    if not block:
        bad('verify-local.sh 里找不到 CAPABILITIES 表')
        return

    entries = re.findall(r'"([\w-]+)\|[^|]*\|([^"|]+)"', block.group(1))
    missing = sorted(test for _, test in entries
                     if not os.path.isfile(os.path.join(repo, test)))
    if missing:
        bad(f'本地能力门禁缺少矩阵脚本：{missing}')
    else:
        ok(f'{len(entries)} 个能力门禁均可本地运行')


def check_workflow_layout(repo):
    """GitHub Actions 只保留 dev 快速检查和 prod 构建。"""
    wf_dir = os.path.join(repo, '.github', 'workflows')
    names = {n for n in os.listdir(wf_dir) if n.endswith(('.yml', '.yaml'))} \
        if os.path.isdir(wf_dir) else set()
    expected = {'dev.yml', 'prod.yml'}
    if names != expected:
        bad(f'GitHub Actions 应仅保留 {sorted(expected)}，当前为 {sorted(names)}')
        return

    dev = read(os.path.join(wf_dir, 'dev.yml'))
    prod = read(os.path.join(wf_dir, 'prod.yml'))
    if 'branches: [dev]' not in dev or 'pull_request:' in dev or 'docker compose' in dev:
        bad('dev.yml 必须仅在 dev 推送时运行快速检查，且不得运行容器 E2E')
    else:
        ok('dev.yml 仅运行开发快速检查')
    if 'branches: [prod]' not in prod or 'tests/e2e/' in prod or 'docker compose' in prod:
        bad('prod.yml 必须仅在 prod 推送时构建产物，且不得运行验收矩阵')
    else:
        ok('prod.yml 仅构建生产镜像')


def check_feature_matrix_freshness(repo):
    """feature-matrix.md 不能明显落后于它所描述的代码。

    栽过一次（不是构建失败，是更隐蔽的一类）：基线跑通之后，FEATURES.md 仍然
    写着"完整镜像从未成功构建过。所有 🟡 项的共同前提都是它"，而那时它已经
    构建过、起过栈、跑过 12/12 冒烟。任何照着文档排期的人都会把力气花错地方。

    文档自己写了"把未验证的标成已完成，是这份文档唯一会失去价值的方式"——
    反过来同样成立。
    """
    doc_rel = 'docs/feature-matrix.md'
    # 只盯"一改动就意味着某个特性状态变了"的路径。
    #
    # 刻意不含 tools/：改一次 preflight 自己就要求更新特性表，是纯噪音，
    # 而会误报的硬门禁最后一定会被人关掉——那比没有这个检查更糟。
    watched = ['tests/e2e/', 'build/cloudfile_14.0/', 'image/',
               'scripts/scripts_14.0/']

    status = subprocess.run(
        ['git', '-C', repo, 'status', '--porcelain', '--', doc_rel],
        capture_output=True, text=True, timeout=10)
    if status.stdout.strip():
        ok('feature-matrix.md 已在当前工作区同步修改')
        return

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
        print('  ⊘ 取不到 feature-matrix.md 的提交时间（非 git 或未提交），跳过')
        return

    stale = []
    for path in watched:
        at = last_commit(path)
        if at is not None and at > doc_at:
            stale.append(path)

    if stale:
        bad(f'feature-matrix.md 落后于 {stale}',
            '代码已经前进而状态表没跟上。照着旧文档排期会把力气花错地方——\n'
            '基线跑通那次就是这样：文档仍写着"镜像从未构建过"。')
    else:
        ok('feature-matrix.md 不落后于代码')


def main():
    if len(sys.argv) != 3:
        sys.stderr.write(__doc__)
        return 2

    repo, workspace = sys.argv[1], sys.argv[2]

    check_workflow_layout(repo)
    check_node_pin(repo, workspace)
    check_branch_ref_is_remote(repo)
    check_offline_image_build(repo)
    check_seahub_settings_block(repo)
    check_switch_lists(repo, workspace)
    check_extension_points_documented(repo, workspace)
    check_local_capabilities(repo)
    check_feature_matrix_freshness(repo)

    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
