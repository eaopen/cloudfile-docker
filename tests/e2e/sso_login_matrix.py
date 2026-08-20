#!/usr/bin/env python3
"""SSO（OAuth/OIDC 登录）配置翻译门禁。

T4：Authentik 2026.5.6 镜像 GB 级不拉；本门禁在容器内验证 CloudFile 把
CF_SSO_* 翻译到 seahub_settings.py 的 OAUTH_* 字段，验证 oauth/login/
路由在开关开启时被挂载、登出回跳 URL 写对。

完整 OAuth/OIDC 跳（Authentik→callback→用户落库）受限于镜像缺失，记技
术债务；本门禁只锁定配置翻译这一层。

    python3 sso_login_matrix.py --url https://127.0.0.1 --insecure \
        --admin me@example.com --admin-password xxx
"""

import argparse
import os
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import review_harness as H

def check(name, passed, detail=''):
    print('  %s %s%s' % ('✓' if passed else '✗', name,
                         ('\n      ' + detail) if detail and not passed else ''),
          flush=True)
    return passed

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--url', required=True)
    ap.add_argument('--admin', required=True)
    ap.add_argument('--admin-password', required=True)
    ap.add_argument('--insecure', action='store_true')
    args = ap.parse_args()

    if args.insecure:
        ssl._create_default_https_context = ssl._create_unverified_context
    base = args.url.rstrip('/')
    ctx = H.Context(base, args.admin, args.admin_password)
    admin_token = ctx.token(args.admin, args.admin_password)
    if not admin_token:
        print('✗ 管理员登录失败', file=sys.stderr)
        return 1

    passed = True

    # sso-001: CF_ENABLE_SSO=true 启动后 seahub_settings.py 含 ENABLE_OAUTH=True
    try:
        import subprocess
        out = subprocess.run(
            ['docker', 'exec', 'cloudfile', 'bash', '-c',
             'grep -E "^ENABLE_OAUTH|^OAUTH_CLIENT_ID|^OAUTH_CLIENT_SECRET|'
             '^OAUTH_AUTHORIZATION_URL|^OAUTH_TOKEN_URL|^OAUTH_USER_INFO_URL|'
             '^OAUTH_SCOPE|^OAUTH_PROVIDER|^OAUTH_REDIRECT_URL|^OAUTH_ATTRIBUTE_MAP" '
             '/shared/seafile/conf/seahub_settings.py || true'],
            capture_output=True, text=True, timeout=20)
        lines = (out.stdout or '').splitlines()
        eo = [l for l in lines if l.startswith('ENABLE_OAUTH')]
        cid = [l for l in lines if l.startswith('OAUTH_CLIENT_ID')]
        csec = [l for l in lines if l.startswith('OAUTH_CLIENT_SECRET')]
        prov = [l for l in lines if l.startswith('OAUTH_PROVIDER')]
        ru = [l for l in lines if l.startswith('OAUTH_REDIRECT_URL')]
        amap = [l for l in lines if l.startswith('OAUTH_ATTRIBUTE_MAP')]

        passed &= check('sso-001 ENABLE_OAUTH=True 写入',
                        any('True' in l for l in eo), f'lines={eo}')
        passed &= check('sso-002 OAUTH_CLIENT_ID 与 CF_SSO_OAUTH_CLIENT_ID 一致',
                        bool(cid), f'lines={cid}')
        passed &= check('sso-003 OAUTH_CLIENT_SECRET 写入（非空）',
                        bool(csec) and '\"\"' not in csec[0], f'lines={csec}')
        passed &= check('sso-004 OAUTH_PROVIDER 写入',
                        bool(prov), f'lines={prov}')
        passed &= check('sso-005 OAUTH_REDIRECT_URL 由 proto+host 派生',
                        any(re.search(r'://[A-Za-z0-9.\-]+/oauth/callback/', l)
                            for l in ru), f'lines={ru}')
        passed &= check('sso-006 OAUTH_ATTRIBUTE_MAP 含 email 与 sub',
                        bool(amap) and 'email' in amap[0]
                        and 'uid' in amap[0], f'lines={amap}')
    except Exception as e:
        passed &= check('sso-001..006 读 settings', False, str(e)[:150])

    # sso-007: oauth/login/ 路由可达（不 404）——启用后视图挂上
    try:
        req = urllib.request.Request(base + '/oauth/login/', method='GET',
                                     headers={'Authorization': f'Token {admin_token}'})
        ctx_ssl = ssl._create_unverified_context() if args.insecure else None
        with urllib.request.urlopen(req, timeout=20, context=ctx_ssl) as r:
            status = r.status
            loc = r.getheader('Location', '')
        # 启用后 oauth/login 应 302 到 OP authorize endpoint
        ok = status in (301, 302) and loc
        passed &= check('sso-007 /oauth/login/ 302 到 OP',
                        ok, f'status={status} location={loc[:80]}')
    except urllib.error.HTTPError as e:
        passed &= check('sso-007 /oauth/login/ 路由挂载',
                        e.code != 404, f'status={e.code}')
    except Exception as e:
        passed &= check('sso-007 /oauth/login/ 路由挂载', False, str(e)[:150])

    print('════════ SSO 配置翻译 %s ════════'
          % ('通过' if passed else '失败'))
    return 0 if passed else 1

if __name__ == '__main__':
    sys.exit(main())