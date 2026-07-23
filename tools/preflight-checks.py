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
    check_switch_lists(repo, workspace)

    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
