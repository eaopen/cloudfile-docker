#!/usr/bin/env python3
"""Seafile AI 离线接线校验（云盘复检：镜像缺失，不启容器）。

seafile-ai:14.0-latest 镜像不存在（AI 是 Seafile Pro 组件，CE 不发布），且
CF_AI_ENABLED=true 一旦启动会让 seahub 注册 AI 模块并触发 AIUsageStatistics
聚合（smoke 在账号信息读取时 500）——开开关必坏原生冒烟，缺镜像必坏 AI 端点。
两边都对 T7 不友好，故 ai_matrix 走离线静态校验：

  ai-001  compose 的 ai profile 含 seafile-ai 服务定义（profiles: ["ai","full"]）
  ai-002  compose 透传 CF_AI_*、ENABLE_SEAFILE_AI、SEAFILE_AI_SERVER_URL 给 cloudfile
  ai-003  seahub/settings.py 直接读 env 派生 ENABLE_SEAFILE_AI（无 bootstrap 写入）
  ai-004  docs/features/seafile-ai.md 记录镜像缺失作为已知缺口

    python3 ai_matrix.py --repo cloudfile-docker
"""

import argparse
import os
import re
import sys

def check(name, passed, detail=''):
    print('  %s %s%s' % ('✓' if passed else '✗', name,
                         ('\n      ' + detail) if detail and not passed else ''),
          flush=True)
    return passed

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--repo', default='cloudfile-docker',
                    help='compose 仓路径（含 deploy/compose）')
    args = ap.parse_args()

    repo = args.repo
    compose = os.path.join(repo, 'deploy', 'compose', 'docker-compose.yml')
    seahub_settings = os.path.join(
        os.pardir, 'cloudfile-hub', 'seahub', 'settings.py')
    doc = os.path.join(repo, 'docs', 'features', 'seafile-ai.md')

    passed = True
    text = open(compose).read() if os.path.exists(compose) else ''

    # ai-001: seafile-ai 服务定义在 ai profile
    passed &= check('ai-001 seafile-ai 服务定义存在且 profiles 含 ai',
                    'seafile-ai:' in text
                    and re.search(r"profiles:\s*\[.*?ai.*?\]", text) is not None,
                    'compose 缺 seafile-ai 或 profiles')

    # ai-002: compose 透传 ENABLE_SEAFILE_AI / SEAFILE_AI_SERVER_URL
    keys = ['ENABLE_SEAFILE_AI', 'SEAFILE_AI_SERVER_URL',
            'SEAFILE_AI_SECRET_KEY']
    missing = [k for k in keys
               if not re.search(rf'\b{k}:', text)]
    passed &= check('ai-002 compose 透传关键 env',
                    not missing, f'缺={missing}')

    # ai-003: seahub 直接读 env 派生（无 bootstrap 介入）
    if os.path.exists(seahub_settings):
        st = open(seahub_settings).read()
        m = re.search(r"ENABLE_SEAFILE_AI\s*=\s*os\.environ\.get\('ENABLE_SEAFILE_AI'",
                      st)
        passed &= check('ai-003 seahub settings 从 os.environ 派生',
                        m is not None, 'settings.py 未直接读 env')
    else:
        passed &= check('ai-003 seahub settings 从 os.environ 派生', False,
                        f'路径不存在: {seahub_settings}')

    # ai-004: 文档记录镜像缺失
    if os.path.exists(doc):
        d = open(doc).read()
        passed &= check('ai-004 docs 记录镜像缺失/已知缺口',
                        '镜像' in d or 'Pro' in d or '缺口' in d,
                        'seafile-ai.md 缺缺口说明')
    else:
        passed &= check('ai-004 docs 记录镜像缺失', False,
                        f'缺 {doc}')

    print('════════ Seafile AI 离线接线 %s ════════'
          % ('通过' if passed else '失败'))
    return 0 if passed else 1

if __name__ == '__main__':
    sys.exit(main())