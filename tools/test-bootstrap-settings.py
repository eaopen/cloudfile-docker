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


def _module_constant(tree, name):
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise SystemExit('bootstrap.py 里找不到常量 %s' % name)


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
        # Read out of bootstrap.py rather than restated here: a restated switch
        # list is a fixture that can drift, and drifting fixtures are exactly
        # what this file exists to catch.
        'CF_FEATURE_SWITCHES': _module_constant(tree, 'CF_FEATURE_SWITCHES'),
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


def test_upstream_packages():
    print('── _settings_block_upstream')
    packaged = load('_settings_block_upstream', {})
    check('所有打包层开关关闭时不写任何内容', packaged() == '', repr(packaged()))

    env = {
        'CF_LDAP_ENABLED': 'true',
        'CF_LDAP_SERVER_URL': 'ldaps://directory.example.com:636',
        'CF_LDAP_BASE_DN': 'ou=people,dc=example,dc=com',
        'CF_LDAP_ADMIN_DN': 'cn=reader,dc=example,dc=com',
        'CF_LDAP_ADMIN_PASSWORD': "it's a secret",
        'CF_LDAP_LOGIN_ATTR': 'uid',
        'CF_LDAP_CONTACT_EMAIL_ATTR': 'mail',
        'CF_ADFS_ENABLED': 'true',
        'CF_ADFS_REMOTE_METADATA_URL': 'https://idp.example.com/metadata',
        'CF_ADFS_ATTRIBUTE_MAPPING_JSON':
            '{"uid":["uid"],"email":["mail"]}',
        'CF_SHIBBOLETH_ENABLED': 'true',
        'CF_SHIBBOLETH_REMOTE_USER_HEADER': 'HTTP_X_AUTH_REQUEST_EMAIL',
        'CF_SHIBBOLETH_ATTRIBUTE_MAP_JSON':
            '{"HTTP_DISPLAYNAME":"name"}',
        'CF_SHIBBOLETH_AFFILIATION_ROLE_MAP_JSON':
            '{"staff@example.com":"staff"}',
        'CF_SHIBBOLETH_LOGOUT_URL': 'https://idp.example.com/logout?return=',
        'CF_SHIBBOLETH_LOGOUT_RETURN': 'https://cloudfile.example.com/',
        'CF_ROLE_PERMISSIONS_JSON':
            '{"default":{"can_add_repo":false}}',
        'CF_ADMIN_ROLE_PERMISSIONS_JSON':
            '{"daily_admin":{"can_manage_group":false}}',
        'CF_TWO_FACTOR_ENABLED': 'true',
        'CF_TWO_FACTOR_DEVICE_REMEMBER_DAYS': '0',
    }
    try:
        values = evaluate(load('_settings_block_upstream', env)())
    except Exception as e:
        check('完整打包配置可以被加载', False,
              '%s: %s' % (type(e).__name__, e))
        return

    check('完整打包配置可以被加载', True)
    check('LDAP 及带引号的绑定密码被完整写入',
          values.get('ENABLE_LDAP') is True
          and values.get('LDAP_ADMIN_PASSWORD') == "it's a secret",
          repr(values.get('LDAP_ADMIN_PASSWORD')))
    check('ADFS 写入元数据、属性映射和 xmlsec 默认值',
          values.get('ENABLE_ADFS_LOGIN') is True
          and values.get('SAML_ATTRIBUTE_MAPPING', {}).get('email') == ['mail']
          and values.get('SAML_XMLSEC_BINARY_PATH') == '/usr/bin/xmlsec1',
          repr(values.get('SAML_ATTRIBUTE_MAPPING')))
    check('Shibboleth 同时启用可信反向代理认证',
          values.get('ENABLE_SHIB_LOGIN') is True
          and values.get('ENABLE_REMOTE_USER_AUTHENTICATION') is True
          and values.get('REMOTE_USER_HEADER') == 'HTTP_X_AUTH_REQUEST_EMAIL',
          repr(values.get('REMOTE_USER_HEADER')))
    check('用户和管理员角色策略保持对象结构',
          values.get('ENABLED_ROLE_PERMISSIONS', {}).get('default', {}).get('can_add_repo') is False
          and values.get('ENABLED_ADMIN_ROLE_PERMISSIONS', {}).get('daily_admin', {}).get('can_manage_group') is False,
          repr(values.get('ENABLED_ROLE_PERMISSIONS')))
    check('2FA 允许零天记住设备',
          values.get('ENABLE_TWO_FACTOR_AUTH') is True
          and values.get('TWO_FACTOR_DEVICE_REMEMBER_DAYS') == 0,
          repr(values.get('TWO_FACTOR_DEVICE_REMEMBER_DAYS')))

    env = {'CF_LDAP_ENABLED': 'true'}
    try:
        load('_settings_block_upstream', env)()
        check('LDAP 缺少连接参数时启动失败', False, '被接受了')
    except Exception:
        check('LDAP 缺少连接参数时启动失败', True)

    env = {
        'CF_ADFS_ENABLED': 'true',
        'CF_ADFS_REMOTE_METADATA_URL': 'https://idp.example.com/metadata',
        'CF_ADFS_ATTRIBUTE_MAPPING_JSON': '[]',
    }
    try:
        load('_settings_block_upstream', env)()
        check('ADFS 属性映射不是对象时启动失败', False, '被接受了')
    except Exception:
        check('ADFS 属性映射不是对象时启动失败', True)

    env = {'CF_TWO_FACTOR_ENABLED': 'true',
           'CF_TWO_FACTOR_DEVICE_REMEMBER_DAYS': '-1'}
    try:
        load('_settings_block_upstream', env)()
        check('2FA 负的记住天数时启动失败', False, '被接受了')
    except Exception:
        check('2FA 负的记住天数时启动失败', True)

    env = {'CF_ENABLE_TAGS': 'true'}
    try:
        load('_settings_block_upstream', env)()
        check('标签未启用元数据时启动失败', False, '被接受了')
    except Exception:
        check('标签未启用元数据时启动失败', True)

    env = {'CF_ENABLE_CONVERT_EXPORT': 'true'}
    try:
        load('_settings_block_upstream', env)()
        check('转换导出未配置 JWT 密钥时启动失败', False, '被接受了')
    except Exception:
        check('转换导出未配置 JWT 密钥时启动失败', True)

    env['JWT_PRIVATE_KEY'] = 'stable-test-key'
    try:
        load('_settings_block_upstream', env)()
        check('转换导出配置 JWT 密钥后可以启动', True)
    except Exception as e:
        check('转换导出配置 JWT 密钥后可以启动', False, str(e))


def test_search():
    print('── _settings_block_search')
    search = load('_settings_block_search', {})

    # 铁律：开关关掉 = 原生 CE。一个字节都不该写——CF_PROVIDER_SEARCH 留空
    # 时的默认行为（走 SeaSearch）也不该被写死成某个值。
    check('开关关闭时不写任何内容', search() == '', repr(search()))

    env = {'CF_ENABLE_SEARCH': 'true'}
    try:
        values = evaluate(load('_settings_block_search', env)())
    except Exception as e:
        check('开关打开、留空 provider 时可以被加载', False,
              '%s: %s' % (type(e).__name__, e))
        return

    check('开关打开、留空 provider 时可以被加载', True)
    check('CF_PROVIDER_SEARCH 默认留空（SeaSearch/原生路径）',
          values.get('CF_PROVIDER_SEARCH') == '',
          repr(values.get('CF_PROVIDER_SEARCH')))
    check('Meilisearch 连接信息即使未选用也写了默认值',
          values.get('CF_MEILISEARCH_URL') == 'http://meilisearch:7700',
          repr(values.get('CF_MEILISEARCH_URL')))
    check('索引正文体积上限是整数而不是字符串',
          values.get('CF_SEARCH_INDEX_TEXT_MAX_BYTES') == 1048576,
          repr(values.get('CF_SEARCH_INDEX_TEXT_MAX_BYTES')))

    env = {
        'CF_ENABLE_SEARCH': 'true',
        'CF_PROVIDER_SEARCH': 'meilisearch',
        'CF_MEILISEARCH_URL': 'http://meilisearch.internal:7700',
        # 带引号的 key 是真实存在的一类值,和 SSO 的 client secret 同一个理由。
        'CF_MEILISEARCH_API_KEY': "it's a secret",
        'CF_SEARCH_INDEX_INTERVAL': '30',
    }
    values = evaluate(load('_settings_block_search', env)())
    check('选中 meilisearch 时逐项写入',
          values.get('CF_PROVIDER_SEARCH') == 'meilisearch'
          and values.get('CF_MEILISEARCH_URL') == 'http://meilisearch.internal:7700'
          and values.get('CF_MEILISEARCH_API_KEY') == "it's a secret"
          and values.get('CF_SEARCH_INDEX_INTERVAL') == 30,
          repr(values))

    env = {'CF_ENABLE_SEARCH': 'true', 'CF_SEARCH_INDEX_INTERVAL': 'soon'}
    try:
        load('_settings_block_search', env)()
        check('索引间隔不是数字时启动失败', False, '被接受了')
    except Exception:
        check('索引间隔不是数字时启动失败', True)

    env = {'CF_ENABLE_SEARCH': 'true', 'CF_SEARCH_INDEX_TEXT_MAX_BYTES': '0'}
    try:
        load('_settings_block_search', env)()
        check('正文体积上限为 0 时启动失败', False, '被接受了')
    except Exception:
        check('正文体积上限为 0 时启动失败', True)


def test_external_sources():
    print('── _settings_block_external_sources')
    block = load('_settings_block_external_sources', {})

    check('开关关闭时不写任何内容', block() == '', repr(block()))

    env = {'CF_ENABLE_EXTERNAL_SOURCES': 'true'}
    try:
        values = evaluate(load('_settings_block_external_sources', env)())
    except Exception as e:
        check('开关打开时可以被加载', False, '%s: %s' % (type(e).__name__, e))
        return

    check('开关打开时可以被加载', True)
    # 这一项是这个能力的安全边界：默认必须是"只有那一个前缀"，不是"随便哪里"。
    check('默认根前缀是列表且只含 /shared/external',
          values.get('CF_EXTERNAL_SOURCES_ROOTS') == ['/shared/external'],
          repr(values.get('CF_EXTERNAL_SOURCES_ROOTS')))

    env = {'CF_ENABLE_EXTERNAL_SOURCES': 'true',
           'CF_EXTERNAL_SOURCES_ROOTS': '/mnt/nas:/shared/external'}
    values = evaluate(load('_settings_block_external_sources', env)())
    check('冒号分隔的多个前缀逐项写入',
          values.get('CF_EXTERNAL_SOURCES_ROOTS') == ['/mnt/nas',
                                                      '/shared/external'],
          repr(values.get('CF_EXTERNAL_SOURCES_ROOTS')))

    # 下面三项都是"配置错了必须起不来"，而不是"回落到某个默认值"。
    # 空值回落成默认是最坏的一种：运维以为自己限制了范围，实际没有；
    # 而 '/' 通过则等于管理接口可以把整个容器文件系统登记成外部源。
    for name, raw in [('留空时启动失败', ''),
                      ('只有分隔符时启动失败', ':::'),
                      ('包含 / 时启动失败', '/shared/external:/'),
                      ('相对路径时启动失败', 'shared/external')]:
        env = {'CF_ENABLE_EXTERNAL_SOURCES': 'true',
               'CF_EXTERNAL_SOURCES_ROOTS': raw}
        try:
            load('_settings_block_external_sources', env)()
            check(name, False, '%r 被接受了' % raw)
        except Exception:
            check(name, True)


def test_fileop_seafile_conf():
    """seafile.conf 的 [cloudfile] 段 —— C 侧读的那份。

    这一段和 seahub_settings.py 那些不同：它不是 Python，所以 exec 不了，
    只能按行断言。但价值一样——写入生命周期的测试 provider 能拒绝写入，
    "以为关着其实开着"和"以为开着其实关着"都得是能被检查出来的。
    """
    print('── _seafile_conf_cloudfile_lines')
    build = load('_seafile_conf_cloudfile_lines', {})

    def lines(env):
        return ''.join(load('_seafile_conf_cloudfile_lines', env)())

    base = lines({})
    check('默认能力开关与测试 provider 全为 false',
          base.count(' = false\n')
          == len(build.__globals__['CF_FEATURE_SWITCHES']) + 1,
          # Capabilities are read from bootstrap.py, never duplicated here.
          # The one additional line is the non-product fileop test provider.
          repr(base))
    check('测试 provider 默认关闭',
          'fileop_test_provider_enabled = false' in base, repr(base))
    check('关闭时不写标记与 journal',
          'fileop_test_refuse_token' not in base
          and 'fileop_test_journal' not in base, repr(base))

    on = lines({'CF_FILEOP_TEST_PROVIDER': 'true'})
    check('打开后写入三项',
          'fileop_test_provider_enabled = true' in on
          and 'fileop_test_refuse_token = cf-refuse' in on
          and 'fileop_test_journal = /shared/cf-fileop-journal.log' in on,
          repr(on))

    # 观察模式：标记显式留空。这不是"没配"而是"配成不拒绝"，回落到默认值会让
    # 门禁的阶段 1 在建夹具时就被拒——而那恰好是被测操作之一。
    observe = lines({'CF_FILEOP_TEST_PROVIDER': 'true',
                     'CF_FILEOP_TEST_REFUSE_TOKEN': ''})
    check('标记显式留空时不回落到默认值',
          'fileop_test_refuse_token = \n' in observe, repr(observe))

    custom = lines({'CF_FILEOP_TEST_PROVIDER': 'true',
                    'CF_FILEOP_TEST_REFUSE_TOKEN': 'blocked',
                    'CF_FILEOP_TEST_JOURNAL': '/shared/j.log'})
    check('标记与 journal 可覆盖',
          'fileop_test_refuse_token = blocked' in custom
          and 'fileop_test_journal = /shared/j.log' in custom, repr(custom))

    # provider 按路径组件比较，给它一个路径而不是组件是配置错误，不是拒绝规则。
    try:
        lines({'CF_FILEOP_TEST_PROVIDER': 'true',
               'CF_FILEOP_TEST_REFUSE_TOKEN': 'a/b'})
        check('标记里带 / 时启动失败', False, '没有抛异常')
    except Exception:
        check('标记里带 / 时启动失败', True)

    try:
        lines({'CF_FILEOP_TEST_PROVIDER': 'true',
               'CF_FILEOP_TEST_JOURNAL': 'relative.log'})
        check('journal 是相对路径时启动失败', False, '没有抛异常')
    except Exception:
        check('journal 是相对路径时启动失败', True)

    # 能力开关和它互不干扰：一个是产品能力，一个是门禁仪器。
    both = lines({'CF_ENABLE_DIR_ACL': 'true',
                  'CF_FILEOP_TEST_PROVIDER': 'true'})
    check('能力开关与测试 provider 各自独立',
          'dir_acl_enabled = true' in both
          and 'fileop_test_provider_enabled = true' in both, repr(both))

    lock = lines({'CF_ENABLE_FILE_LOCK': 'true'})
    check('文件锁启用时固定选择 CE 锁后端',
          'file_lock_enabled = true' in lock
          and 'lock_backend = cloudfile' in lock, repr(lock))

    try:
        lines({'CF_ENABLE_FILE_LOCK': 'true', 'CF_LOCK_BACKEND': 'pro'})
        check('CE 镜像拒绝 Pro 锁后端', False, '没有抛异常')
    except Exception:
        check('CE 镜像拒绝 Pro 锁后端', True)

    del build


def main():
    print(__doc__.splitlines()[0])
    print()
    test_sso()
    test_search()
    test_external_sources()
    test_upstream_packages()
    test_fileop_seafile_conf()
    print()
    if failures:
        print('\033[31m%d 项失败\033[0m' % len(failures))
        return 1
    print('\033[32m全部通过\033[0m')
    return 0


if __name__ == '__main__':
    sys.exit(main())
