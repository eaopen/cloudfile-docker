#!/usr/bin/env python3
"""执行 bootstrap 生成的 seahub_settings.py 片段，验证它真的能跑。

preflight 的 `check_seahub_settings_block` 是**静态**的：它按正则找
`FOO['bar'] =` 这类依赖 seahub settings 命名空间的写法。那条检查抓住了当年
`DATABASES['cloudfile'] = {...}` 那个事故的形状，但抓不住别的形状——引号没转义、
把字符串拼成了非法字面量、`%r` 用在了元组上，全都能过静态检查，然后在容器里
被 seahub 吞成一行 NameError/SyntaxError，**整个文件的 CloudFile 配置一起丢掉，
而服务看起来是正常起来的**。

所以这里换个问法：把生成函数抠出来，喂各种 .env，`exec()` 它的输出，再断言得到
的值就是预期的值。秒级，不需要 docker，不需要真的 seahub。

    python3 tools/test-bootstrap-settings.py

只抠函数、不 import 整个 bootstrap，是因为 bootstrap 顶上 `from utils import ...`
依赖容器里的运行环境；为了跑一个纯字符串函数去搭那套环境不值得，而抠出来的是
**同一份源码**，不是复制品——这一点很关键，与被测代码不一致的 fixture 什么都
证明不了（`DATABASES['cloudfile']` 正是被一份手写的 fixture 放过去的）。
"""

import ast
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BOOTSTRAP = os.path.join(HERE, '..', 'scripts', 'scripts_14.0', 'bootstrap.py')

failures = []


def check(name, condition, detail=''):
    if condition:
        print('  \033[32m✓\033[0m %s' % name)
    else:
        print('  \033[31m✗\033[0m %s%s' % (name, ('：' + detail) if detail else ''))
        failures.append(name)


def load(func_name, env):
    """把 bootstrap 里的一个函数按当前 .env 取出来执行。"""
    with open(BOOTSTRAP, encoding='utf-8') as fp:
        tree = ast.parse(fp.read())

    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            break
    else:
        raise SystemExit('bootstrap.py 里找不到 %s' % func_name)

    ns = {
        'json': json,
        'get_conf': lambda key, default='': env.get(key, default),
        'cf_enabled': lambda key: env.get(key, 'false').lower() == 'true',
        'get_proto': lambda: env.get('SEAFILE_SERVER_PROTOCOL', 'https'),
    }
    exec(compile(ast.Module(body=[node], type_ignores=[]), BOOTSTRAP, 'exec'), ns)
    return ns[func_name]


def evaluate(block):
    """按 seahub 的方式加载：普通模块，没有任何预置名字。"""
    namespace = {}
    exec(block, namespace)
    return namespace


BASE_ENV = {
    'CF_ENABLE_SSO': 'true',
    'SEAFILE_SERVER_HOSTNAME': 'cloudfile.example.com',
    'CF_SSO_OAUTH_CLIENT_ID': 'cloudfile',
    # 带引号的密码是真实存在的，而且是最容易把生成的文件写坏的一种值。
    'CF_SSO_OAUTH_CLIENT_SECRET': "it's a secret",
    'CF_SSO_OAUTH_AUTHORIZATION_URL': 'https://idp.example.com/authorize',
    'CF_SSO_OAUTH_TOKEN_URL': 'https://idp.example.com/token',
    'CF_SSO_OAUTH_USER_INFO_URL': 'https://idp.example.com/userinfo',
    'CF_SSO_OAUTH_PROVIDER': 'idp.example.com',
    'CF_PROVIDER_SSO_DIRECTORY': 'static',
    'CF_SSO_GROUP_OWNER': 'admin@example.com',
    'CF_SSO_DIRECTORY_STATIC':
        '[{"external_id": "eng", "name": "Engineering",'
        ' "members": ["alice@example.com"]}]',
}


def test_sso():
    print('── _settings_block_sso')
    sso = load('_settings_block_sso', {})

    # 铁律：开关关掉 = 原生 CE。一个字节都不该写。
    check('开关关闭时不写任何内容', sso() == '', repr(sso()))

    env = dict(BASE_ENV)
    sso = load('_settings_block_sso', env)
    block = sso()

    try:
        values = evaluate(block)
    except Exception as e:
        check('生成的片段可以被加载', False, '%s: %s' % (type(e).__name__, e))
        return

    check('生成的片段可以被加载', True)
    check('登录被打开', values.get('ENABLE_OAUTH') is True)
    check('回调地址由部署自己的主机名推导',
          values.get('OAUTH_REDIRECT_URL')
          == 'https://cloudfile.example.com/oauth/callback/',
          repr(values.get('OAUTH_REDIRECT_URL')))
    check('带引号的密码没有把文件写坏',
          values.get('OAUTH_CLIENT_SECRET') == "it's a secret",
          repr(values.get('OAUTH_CLIENT_SECRET')))
    check('scope 是列表而不是一整个字符串',
          values.get('OAUTH_SCOPE') == ['openid', 'email', 'profile'],
          repr(values.get('OAUTH_SCOPE')))
    check('email claim 是必需项',
          values.get('OAUTH_ATTRIBUTE_MAP', {}).get('email') == (True, 'email'),
          repr(values.get('OAUTH_ATTRIBUTE_MAP')))
    check('static 目录被解析成结构',
          values.get('CF_SSO_DIRECTORY_STATIC', [{}])[0].get('external_id') == 'eng',
          repr(values.get('CF_SSO_DIRECTORY_STATIC')))

    # uid 与 email 取同一个 claim 的 IdP 是存在的。字典会吃掉其中一个，
    # 吃掉哪个取决于插入顺序——如果吃掉的是 email，登录会因"必需属性缺失"
    # 被拒，而报错里完全看不出是 .env 里两行配成了同一个值。
    env = dict(BASE_ENV, CF_SSO_OAUTH_UID_CLAIM='email')
    values = evaluate(load('_settings_block_sso', env)())
    check('uid 与 email 同名时 email 仍是必需项',
          values.get('OAUTH_ATTRIBUTE_MAP', {}).get('email') == (True, 'email'),
          repr(values.get('OAUTH_ATTRIBUTE_MAP')))

    # 只要组织映射、登录仍走 LDAP/SAML 的部署：不能因此打开 OAuth。
    env = dict(BASE_ENV, CF_SSO_OAUTH_CLIENT_ID='')
    values = evaluate(load('_settings_block_sso', env)())
    check('没配 client id 就不打开 OAuth', 'ENABLE_OAUTH' not in values)
    check('但组织映射的配置照写',
          values.get('CF_SSO_GROUP_OWNER') == 'admin@example.com')

    # JSON 写错要在启动时炸（运维正看着），不是在第一次同步时才炸。
    env = dict(BASE_ENV, CF_SSO_DIRECTORY_STATIC='{oops')
    try:
        load('_settings_block_sso', env)()
        check('static 目录的 JSON 写错时启动失败', False, '被接受了')
    except Exception:
        check('static 目录的 JSON 写错时启动失败', True)


def main():
    print(__doc__.splitlines()[0])
    print()
    test_sso()
    print()
    if failures:
        print('\033[31m%d 项失败\033[0m' % len(failures))
        return 1
    print('\033[32m全部通过\033[0m')
    return 0


if __name__ == '__main__':
    sys.exit(main())
