#!/usr/bin/env python3
"""静态一致性检查：专抓"只有 CI 跑起来才会炸"的那类不一致。

每一条都对应一次真实付出过代价的失败。CI 一轮 20 分钟，这些检查是秒级的。

    python3 tools/preflight-checks.py <docker_repo> <workspace>
"""

import os
import re
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

    # 只看写进 seahub_settings.py 的那段 body
    m = re.search(r'def write_cloudfile_settings\(\):(.*?)\n    _replace_block',
                  boot, re.S)
    if not m:
        print('  ⊘ 找不到 write_cloudfile_settings，跳过')
        return

    # 先剥掉注释：本函数的注释里正好引用了当年那行错误代码作为反面例子，
    # 不剥的话检查会拿自己的说明文字当成违规。
    body = '\n'.join(line for line in m.group(1).splitlines()
                     if not line.lstrip().startswith('#'))

    # 形如 FOO['bar'] = 或 FOO.setdefault( 都依赖 seahub settings 的命名空间
    offenders = sorted(set(re.findall(r'"\s*([A-Z_]+)\[', body)) |
                       set(re.findall(r'"\s*([A-Z_]+)\.\w+\(', body)))
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


def main():
    if len(sys.argv) != 3:
        sys.stderr.write(__doc__)
        return 2

    repo, workspace = sys.argv[1], sys.argv[2]
    wf = read(os.path.join(repo, '.github', 'workflows', 'build-and-e2e.yml'))
    if wf is None:
        bad('读不到 build-and-e2e.yml')
        return 1

    check_workflow_references(repo, wf)
    check_tls_target(wf)
    check_hostname(wf, workspace)
    check_node_pin(repo, workspace)
    check_seahub_settings_block(repo)
    check_switch_lists(repo, workspace)

    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
