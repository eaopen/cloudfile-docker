#!/usr/bin/env python3
#coding: UTF-8

"""
Bootstraping seafile server, letsencrypt (verification & cron job).
"""

import argparse
import json
import os
from os.path import abspath, basename, exists, dirname, join, isdir
import shutil
import sys
import uuid
import time

from utils import (
    call, get_conf, get_install_dir, loginfo, logwarning,
    get_script, render_template, get_seafile_version, eprint,
    cert_has_valid_days, get_version_stamp_file, update_version_stamp,
    wait_for_mysql, wait_for_nginx, read_version_stamp, is_pro_version
)

seafile_version = get_seafile_version()
installdir = get_install_dir()
topdir = dirname(installdir)
shared_seafiledir = '/shared/seafile'
ssl_dir = '/shared/ssl'
generated_dir = '/bootstrap/generated'


def gen_custom_dir():
    dst_custom_dir = '/shared/seafile/seahub-data/custom'
    custom_dir = join(installdir, 'seahub/media/custom')
    if not exists(dst_custom_dir):
        os.mkdir(dst_custom_dir)
        call('rm -rf %s' % custom_dir)
        call('ln -sf %s %s' % (dst_custom_dir, custom_dir))

def is_https():
    return get_conf('SEAFILE_SERVER_LETSENCRYPT', 'false').lower() == 'true'

def get_proto():
    proto = 'https' if is_https() else 'http'
    seafile_server_proto = get_conf('SEAFILE_SERVER_PROTOCOL', 'http')
    if seafile_server_proto == 'https':
        proto = 'https'
    return proto

def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument('--parse-ports', action='store_true')

    return ap.parse_args()

# CloudFile: every CF_ENABLE_* switch, defaulting to off. Turning them all off
# has to restore native CE behaviour -- that is the acceptance criterion that
# keeps upgrades cheap -- so nothing here may default to true.
CF_FEATURE_SWITCHES = (
    'CF_ENABLE_SSO',
    'CF_ENABLE_DIR_ACL',
    'CF_ENABLE_AUDIT',
    'CF_ENABLE_METADATA',
    'CF_ENABLE_TAGS',
    'CF_ENABLE_MEILISEARCH',
    'CF_ENABLE_ONLYOFFICE',
    'CF_ENABLE_CHECKOUT',
    'CF_ENABLE_S3_STORAGE',
    'CF_ENABLE_EXTERNAL_SOURCES',
)


CF_BEGIN = '# --- CloudFile (generated, do not edit) ---'
CF_END = '# --- end CloudFile ---'


def cf_enabled(name):
    return get_conf(name, 'false').lower() == 'true'


def _replace_block(path, begin, end, body):
    """Rewrite the region between `begin` and `end`, appending it if absent.

    Written on every start rather than only at first bootstrap, because
    init_seafile_server() returns early once seafile-data exists -- so a
    switch flipped in .env would otherwise never take effect. Replacing a
    delimited block instead of appending keeps repeated starts idempotent and
    leaves an operator's own edits elsewhere in the file alone.
    """
    lines = []
    if exists(path):
        with open(path, 'r') as fp:
            lines = fp.readlines()

    out, skipping = [], False
    for line in lines:
        if line.strip() == begin:
            skipping = True
            continue
        if skipping:
            if line.strip() == end:
                skipping = False
            continue
        out.append(line)

    while out and out[-1].strip() == '':
        out.pop()

    with open(path, 'w') as fp:
        fp.writelines(out)
        if out:
            fp.write('\n\n')
        fp.write(begin + '\n')
        fp.write(body)
        fp.write(end + '\n')


def write_cloudfile_settings():
    """Write the CloudFile block into conf/seahub_settings.py.

    cloudfile_ext registers itself through EXTRA_INSTALLED_APPS, which Seahub's
    load_local_settings appends to INSTALLED_APPS -- no patch to settings.py
    needed.

    The cf_* tables live in seafile-db rather than seahub-db because
    seaf-server and the Go fileserver have to read them and neither connects to
    seahub-db, so a second connection plus a router is set up here.
    """
    body = 'from cloudfile_ext.settings_defaults import *  # noqa\n'

    for name in CF_FEATURE_SWITCHES:
        body += '%s = %s\n' % (name, cf_enabled(name))

    # 只写标量，不要碰 DATABASES。
    #
    # seahub_settings.py 是**独立模块**：seahub 的 load_local_settings() 把它
    # import 进来再拷贝大写名字，所以它的命名空间里没有 DATABASES。早先写
    # "DATABASES['cloudfile'] = {...}" 会抛 NameError，导致**整个**
    # seahub_settings.py 加载失败、所有 CF 配置被静默丢弃——扩展框架压根没装上，
    # 而唯一的痕迹只是日志里一行 NameError。
    #
    # 第二个数据库连接与 DATABASE_ROUTERS 改由 CloudFileConfig.ready() 组装，
    # 那里能拿到真正的 settings 命名空间。
    body += (
        "CF_DATABASE_NAME = '%s'\n"
        "CF_DATABASE_USER = '%s'\n"
        "CF_DATABASE_PASSWORD = '%s'\n"
        "CF_DATABASE_HOST = '%s'\n"
        "CF_DATABASE_PORT = '%s'\n"
    ) % (
        get_conf('SEAFILE_MYSQL_DB_SEAFILE_DB_NAME', 'seafile_db'),
        get_conf('SEAFILE_MYSQL_DB_USER', 'seafile'),
        get_conf('SEAFILE_MYSQL_DB_PASSWORD', ''),
        get_conf('SEAFILE_MYSQL_DB_HOST', 'db'),
        get_conf('SEAFILE_MYSQL_DB_PORT', '3306'),
    )

    body += _settings_block_sso()
    body += _settings_block_upstream()

    _replace_block(join(topdir, 'conf', 'seahub_settings.py'),
                   CF_BEGIN, CF_END, body)


def _settings_block_sso():
    """SSO settings, or nothing at all when CF_ENABLE_SSO is off.

    Two halves with different owners:

    **Login is upstream's.** Seafile CE 14.0 already ships OAuth2/OIDC, SAML,
    CAS and LDAP, none of it Pro-gated. All CloudFile does is turn ENABLE_OAUTH
    on and translate a handful of .env variables into the settings upstream
    already reads -- writing a second login path would be maintaining a fork of
    something the fork already contains.

    **Group mapping is CloudFile's**, because upstream has none for a generic
    directory. Those are the CF_SSO_* / CF_PROVIDER_SSO_DIRECTORY values, read
    by cloudfile_ext.sso.

    Everything written here is a self-contained assignment -- see the note
    above about seahub_settings.py being an ordinary module.
    """
    if not cf_enabled('CF_ENABLE_SSO'):
        # The iron rule: a switch that is off leaves the deployment byte for
        # byte as native CE. In particular ENABLE_OAUTH is not written as
        # False either -- upstream's own default is False, and writing it
        # would silently override an operator who configured OAuth by hand
        # before adopting CloudFile.
        return ''

    lines = []

    client_id = get_conf('CF_SSO_OAUTH_CLIENT_ID', '')
    if client_id:
        proto = get_proto()
        host = get_conf('SEAFILE_SERVER_HOSTNAME', 'seafile.example.com')

        # Derived rather than configured. A redirect URL that disagrees with
        # the deployment's own hostname fails at the identity provider, which
        # reports it as a generic "invalid redirect_uri" -- a long way from the
        # typo that caused it, and in a place the operator cannot see logs.
        redirect_url = '%s://%s/oauth/callback/' % (proto, host)

        uid_claim = get_conf('CF_SSO_OAUTH_UID_CLAIM', 'sub')
        email_claim = get_conf('CF_SSO_OAUTH_EMAIL_CLAIM', 'email')
        name_claim = get_conf('CF_SSO_OAUTH_NAME_CLAIM', 'name')

        # Upstream's shape is {claim: (required, seahub_attr)}. The email claim
        # is the required one: seahub/oauth/views.py falls back to it when no
        # uid is mapped, and refuses the login when neither is present.
        attribute_map = {
            email_claim: (True, 'email'),
            uid_claim: (False, 'uid'),
            name_claim: (False, 'name'),
        }
        # A provider that puts the subject in `email` would otherwise lose one
        # of the two entries to the dict, and which one it loses depends on
        # insertion order.
        if uid_claim == email_claim:
            attribute_map = {email_claim: (True, 'email'),
                             name_claim: (False, 'name')}

        lines += [
            'ENABLE_OAUTH = True',
            'OAUTH_ENABLE_INSECURE_TRANSPORT = %r'
            % (get_conf('CF_SSO_OAUTH_INSECURE', 'false').lower() == 'true',),
            'OAUTH_CLIENT_ID = %r' % client_id,
            'OAUTH_CLIENT_SECRET = %r' % get_conf('CF_SSO_OAUTH_CLIENT_SECRET', ''),
            'OAUTH_AUTHORIZATION_URL = %r'
            % get_conf('CF_SSO_OAUTH_AUTHORIZATION_URL', ''),
            'OAUTH_TOKEN_URL = %r' % get_conf('CF_SSO_OAUTH_TOKEN_URL', ''),
            'OAUTH_USER_INFO_URL = %r' % get_conf('CF_SSO_OAUTH_USER_INFO_URL', ''),
            'OAUTH_SCOPE = %r' % get_conf('CF_SSO_OAUTH_SCOPE',
                                          'openid email profile').split(),
            'OAUTH_PROVIDER = %r' % get_conf('CF_SSO_OAUTH_PROVIDER', ''),
            'OAUTH_REDIRECT_URL = %r' % redirect_url,
            'OAUTH_ATTRIBUTE_MAP = %r' % (attribute_map,),
        ]

    lines += [
        'CF_PROVIDER_SSO_DIRECTORY = %r'
        % get_conf('CF_PROVIDER_SSO_DIRECTORY', ''),
        'CF_SSO_GROUP_OWNER = %r' % get_conf('CF_SSO_GROUP_OWNER', ''),
        'CF_SSO_SYNC_INTERVAL = %r' % get_conf('CF_SSO_SYNC_INTERVAL', '600'),
        # Passed through as written, including an empty string, which is how an
        # operator lifts the ceiling from a compose file where every value is
        # text. cloudfile_ext.sso.service is what interprets it.
        'CF_SSO_MAX_REMOVAL_RATIO = %r'
        % get_conf('CF_SSO_MAX_REMOVAL_RATIO', '0.5'),
        'CF_SERVICE_SSO_DIRECTORY_URL = %r'
        % get_conf('CF_SERVICE_SSO_DIRECTORY_URL', ''),
        'CF_SERVICE_SSO_DIRECTORY_SECRET = %r'
        % get_conf('CF_SERVICE_SSO_DIRECTORY_SECRET', ''),
    ]

    static = get_conf('CF_SSO_DIRECTORY_STATIC', '')
    if static:
        # A JSON string in .env, because compose has no way to express a list.
        # Parsed here rather than in Seahub so a malformed value fails at start
        # -- where the operator is watching -- instead of at the first sync.
        try:
            lines.append('CF_SSO_DIRECTORY_STATIC = %r' % (json.loads(static),))
        except ValueError as e:
            raise Exception(
                'CF_SSO_DIRECTORY_STATIC is not valid JSON: %s' % e)

    return '\n'.join(lines) + '\n'


def _settings_block_upstream():
    """Translate the packaged CE-only enterprise settings from ``.env``.

    These settings belong to Seahub, not cloudfile_ext.  Keeping their
    translation here gives operators a declarative compose contract while
    preserving a native CE installation when every package switch is off.
    Values that have a structured upstream shape are JSON in ``.env`` and are
    parsed here, so an invalid policy fails at boot rather than disappearing in
    Seahub's local-settings error handling.
    """
    def json_object(name, default=''):
        raw = get_conf(name, default)
        if not raw:
            return {}
        try:
            value = json.loads(raw)
        except ValueError as e:
            raise Exception('%s is not valid JSON: %s' % (name, e))
        if not isinstance(value, dict):
            raise Exception('%s must be a JSON object' % name)
        return value

    def required(name):
        value = get_conf(name, '')
        if not value:
            raise Exception('%s is required when its package is enabled' % name)
        return value

    lines = []

    if cf_enabled('CF_LDAP_ENABLED'):
        lines += [
            'ENABLE_LDAP = True',
            'LDAP_SERVER_URL = %r' % required('CF_LDAP_SERVER_URL'),
            'LDAP_BASE_DN = %r' % required('CF_LDAP_BASE_DN'),
            'LDAP_ADMIN_DN = %r' % required('CF_LDAP_ADMIN_DN'),
            'LDAP_ADMIN_PASSWORD = %r' % required('CF_LDAP_ADMIN_PASSWORD'),
            'LDAP_LOGIN_ATTR = %r' % required('CF_LDAP_LOGIN_ATTR'),
            'LDAP_PROVIDER = %r' % get_conf('CF_LDAP_PROVIDER', 'ldap'),
            'LDAP_FILTER = %r' % get_conf('CF_LDAP_FILTER', ''),
            'LDAP_CONTACT_EMAIL_ATTR = %r'
            % get_conf('CF_LDAP_CONTACT_EMAIL_ATTR', ''),
        ]

    if cf_enabled('CF_ADFS_ENABLED'):
        attribute_mapping = json_object('CF_ADFS_ATTRIBUTE_MAPPING_JSON')
        if not attribute_mapping:
            raise Exception('CF_ADFS_ATTRIBUTE_MAPPING_JSON is required when its package is enabled')
        lines += [
            'ENABLE_ADFS_LOGIN = True',
            'SAML_REMOTE_METADATA_URL = %r'
            % required('CF_ADFS_REMOTE_METADATA_URL'),
            'SAML_ATTRIBUTE_MAPPING = %r' % (attribute_mapping,),
            'SAML_PROVIDER_IDENTIFIER = %r'
            % get_conf('CF_ADFS_PROVIDER_IDENTIFIER', 'saml'),
            'SAML_XMLSEC_BINARY_PATH = %r'
            % get_conf('CF_ADFS_XMLSEC_BINARY_PATH', '/usr/bin/xmlsec1'),
            'SAML_CERTS_DIR = %r'
            % get_conf('CF_ADFS_CERTS_DIR', '/opt/seafile/seahub-data/certs'),
        ]

    if cf_enabled('CF_SHIBBOLETH_ENABLED'):
        lines += [
            # Shibboleth is an authenticated reverse-proxy integration.  The
            # proxy must strip client supplied headers and set this one only
            # after the Shibboleth SP validated the request.
            'ENABLE_SHIB_LOGIN = True',
            'ENABLE_REMOTE_USER_AUTHENTICATION = True',
            'REMOTE_USER_HEADER = %r'
            % get_conf('CF_SHIBBOLETH_REMOTE_USER_HEADER', 'HTTP_REMOTE_USER'),
            'REMOTE_USER_ATTRIBUTE_MAP = %r'
            % (json_object('CF_SHIBBOLETH_ATTRIBUTE_MAP_JSON'),),
            'SHIBBOLETH_AFFILIATION_ROLE_MAP = %r'
            % (json_object('CF_SHIBBOLETH_AFFILIATION_ROLE_MAP_JSON'),),
            'SHIBBOLETH_LOGOUT_URL = %r'
            % get_conf('CF_SHIBBOLETH_LOGOUT_URL', ''),
            'SHIBBOLETH_LOGOUT_RETURN = %r'
            % get_conf('CF_SHIBBOLETH_LOGOUT_RETURN', ''),
        ]

    role_permissions = json_object('CF_ROLE_PERMISSIONS_JSON')
    if role_permissions:
        lines.append('ENABLED_ROLE_PERMISSIONS = %r' % (role_permissions,))
    admin_role_permissions = json_object('CF_ADMIN_ROLE_PERMISSIONS_JSON')
    if admin_role_permissions:
        lines.append('ENABLED_ADMIN_ROLE_PERMISSIONS = %r'
                     % (admin_role_permissions,))

    if cf_enabled('CF_TWO_FACTOR_ENABLED'):
        days = get_conf('CF_TWO_FACTOR_DEVICE_REMEMBER_DAYS', '90')
        try:
            days = int(days)
        except ValueError:
            raise Exception('CF_TWO_FACTOR_DEVICE_REMEMBER_DAYS must be an integer')
        if days < 0:
            raise Exception('CF_TWO_FACTOR_DEVICE_REMEMBER_DAYS must not be negative')
        lines += [
            'ENABLE_TWO_FACTOR_AUTH = True',
            'TWO_FACTOR_DEVICE_REMEMBER_DAYS = %r' % days,
        ]

    return '\n'.join(lines) + ('\n' if lines else '')


def write_cloudfile_seafile_conf():
    """Mirror the capability switches into seafile.conf for seaf-server.

    Seahub's copy only decides what the UI shows; this one governs the
    authoritative checks that WebDAV and the sync client go through. Both are
    derived from the same environment variables so they cannot drift apart.

    The key name is derived mechanically -- CF_ENABLE_DIR_ACL becomes
    dir_acl_enabled -- so a new capability needs no change here.
    """
    lines = ['[cloudfile]\n']
    for name in CF_FEATURE_SWITCHES:
        key = name[len('CF_ENABLE_'):].lower() + '_enabled'
        lines.append('%s = %s\n'
                     % (key, 'true' if cf_enabled(name) else 'false'))

    _replace_block(join(topdir, 'conf', 'seafile.conf'),
                   CF_BEGIN, CF_END, ''.join(lines))


def write_seafile_env():
    """生成 conf/.env —— Seafile 14.0 的 seafile.sh 启动前必须读到它。

    14.0 的 seafile.sh 里 set_env_config() 在 JWT_PRIVATE_KEY 未设置时会去读
    ${central_config_dir}/.env，读不到就 "Error: .env file not found" 并退出
    255。而现有流程里没有任何一步生成它：setup-seafile-mysql.py 不写，
    上游的 docker bootstrap 也不写——上游 14.0 的部署方式是让运维在 compose
    里手工传这些变量。

    对一条 `docker compose up -d` 就该跑起来的部署来说，让运维手工准备一个
    密钥不合适，所以在这里生成。JWT_PRIVATE_KEY 必须随机且跨重启稳定，因此
    只在缺失时生成，之后一直复用——conf/ 挂在 /shared 上，会持久化。

    文件由 bash `source` 读取，所以值都保持 shell 安全（十六进制、简单标识符）。
    """
    import secrets

    path = join(topdir, 'conf', '.env')

    existing = {}
    if exists(path):
        with open(path) as fp:
            for line in fp:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, _, value = line.partition('=')
                    existing[key.strip()] = value.strip()

    jwt_key = existing.get('JWT_PRIVATE_KEY') or secrets.token_hex(32)

    values = [
        ('JWT_PRIVATE_KEY', jwt_key),
        ('SEAFILE_MYSQL_DB_CCNET_DB_NAME',
         get_conf('SEAFILE_MYSQL_DB_CCNET_DB_NAME', 'ccnet_db')),
        ('SEAFILE_MYSQL_DB_SEAFILE_DB_NAME',
         get_conf('SEAFILE_MYSQL_DB_SEAFILE_DB_NAME', 'seafile_db')),
        ('SEAFILE_MYSQL_DB_SEAHUB_DB_NAME',
         get_conf('SEAFILE_MYSQL_DB_SEAHUB_DB_NAME', 'seahub_db')),
        ('SEAFILE_SERVER_PROTOCOL', get_proto()),
        ('SEAFILE_SERVER_HOSTNAME',
         get_conf('SEAFILE_SERVER_HOSTNAME', 'seafile.example.com')),
        ('SITE_ROOT', get_conf('SITE_ROOT', '/')),
        ('ENABLE_GO_FILESERVER', get_conf('ENABLE_GO_FILESERVER', 'true')),
        ('ENABLE_SEAFDAV', get_conf('ENABLE_SEAFDAV', 'true')),
    ]

    with open(path, 'w') as fp:
        fp.write('# 由 CloudFile bootstrap 每次启动生成。\n')
        fp.write('# JWT_PRIVATE_KEY 只在首次创建，之后保持不变。\n')
        for key, value in values:
            fp.write('%s=%s\n' % (key, value))

    os.chmod(path, 0o600)


def apply_cloudfile_schema():
    """Create the cf_* tables in seafile-db if they are missing.

    Done here rather than in the fresh-install SQL or a versioned upgrade
    script because all three entry points have to work: a new deployment, a
    version upgrade, and an existing Seafile CE installation adopting
    CloudFile. Only the last of those runs no setup or upgrade step at all, and
    a capability whose tables are missing fails closed and locks everyone out.

    The baseline ships no schema at all, so the file is simply absent and this
    logs and returns; capabilities bring their own cloudfile.sql.

    Every statement is IF NOT EXISTS, so running it on every start is cheap and
    safe.
    """
    schema = join(installdir, 'sql', 'mysql', 'cloudfile.sql')
    if not exists(schema):
        logwarning('CloudFile schema %s not found; skipping' % schema)
        return

    import pymysql

    with open(schema) as fp:
        # Strip comments before splitting: a ';' inside one would otherwise
        # cut a statement in half.
        body = '\n'.join(line for line in fp.read().splitlines()
                         if not line.strip().startswith('--'))

    statements = [s.strip() for s in body.split(';') if s.strip()]
    if not statements:
        return

    conn = pymysql.connect(
        host=get_conf('SEAFILE_MYSQL_DB_HOST', 'db'),
        port=int(get_conf('SEAFILE_MYSQL_DB_PORT', '3306')),
        user=get_conf('SEAFILE_MYSQL_DB_USER', 'seafile'),
        password=get_conf('SEAFILE_MYSQL_DB_PASSWORD', ''),
        database=get_conf('SEAFILE_MYSQL_DB_SEAFILE_DB_NAME', 'seafile_db'),
        charset='utf8mb4',
    )
    try:
        with conn.cursor() as cursor:
            for statement in statements:
                cursor.execute(statement)
        conn.commit()
    finally:
        conn.close()


def write_cloudfile_config():
    """Apply CloudFile configuration. Safe to call on every start."""
    loginfo('Applying CloudFile configuration')
    write_seafile_env()
    write_cloudfile_settings()
    write_cloudfile_seafile_conf()
    apply_cloudfile_schema()


def init_seafile_server():
    version_stamp_file = get_version_stamp_file()
    if exists(join(shared_seafiledir, 'seafile-data')):
        if not exists(version_stamp_file):
            update_version_stamp(os.environ['SEAFILE_VERSION'])
        # sysbol link unlink after docker finish.
        latest_version_dir='/opt/seafile/seafile-server-latest'
        current_version_dir='/opt/seafile/' + get_conf('SEAFILE_SERVER', 'seafile-server') + '-' +  read_version_stamp()
        if not exists(latest_version_dir):
            call('ln -sf ' + current_version_dir + ' ' + latest_version_dir)
        loginfo('Skip running setup-seafile-mysql.py because there is existing seafile-data folder.')
        return

    loginfo('Now running setup-seafile-mysql.py in auto mode.')
    env = {
        'SERVER_NAME': 'seafile',
        'SERVER_IP': get_conf('SEAFILE_SERVER_HOSTNAME', 'seafile.example.com'),
        'MYSQL_USER': get_conf('SEAFILE_MYSQL_DB_USER', 'seafile'),
        'MYSQL_USER_PASSWD': get_conf('SEAFILE_MYSQL_DB_PASSWORD', str(uuid.uuid4())),
        'MYSQL_USER_HOST': '%',
        'MYSQL_HOST': get_conf('SEAFILE_MYSQL_DB_HOST', 'db'),
        'MYSQL_PORT': get_conf('SEAFILE_MYSQL_DB_PORT', '3306'),
        # Default MariaDB root user has empty password and can only connect from localhost.
        'MYSQL_ROOT_PASSWD': get_conf('INIT_SEAFILE_MYSQL_ROOT_PASSWORD', ''),
        'CCNET_DB': get_conf('SEAFILE_MYSQL_DB_CCNET_DB_NAME', ''),
        'SEAFILE_DB': get_conf('SEAFILE_MYSQL_DB_SEAFILE_DB_NAME', ''),
        'SEAHUB_DB': get_conf('SEAFILE_MYSQL_DB_SEAHUB_DB_NAME', ''),
    }
    env.update(os.environ) # Allows additional configuration settings in setup-seafile-mysql.py via environment variables.

    setup_script = get_script('setup-seafile-mysql.sh')
    call('{} auto -n seafile'.format(setup_script), env=env)

    domain = get_conf('SEAFILE_SERVER_HOSTNAME', 'seafile.example.com')
    proto = get_proto()

    clsuter_mode = get_conf('CLUSTER_SERVER', 'false') == 'true'
    init_cluster = get_conf('CLUSTER_INIT_MODE', 'false') == 'true'

    with open(join(topdir, 'conf', 'seahub_settings.py'), 'a+') as fp:
        fp.write("\nTIME_ZONE = '{time_zone}'".format(time_zone=os.getenv('TIME_ZONE',default='Etc/UTC')))
        fp.write('\n')
        if clsuter_mode and init_cluster:
            fp.write(f'\nAVATAR_FILE_STORAGE = \'seahub.base.database_storage.DatabaseStorage\'')
            fp.write('\n')

    # Keep Elasticsearch available as a fallback, but use SeaSearch by default.
    if os.path.exists(join(topdir, 'conf', 'seafevents.conf')):
        with open(join(topdir, 'conf', 'seafevents.conf'), 'r') as fp:
            fp_lines = fp.readlines()
            if '[INDEX FILES]\n' in fp_lines:
                section_index = fp_lines.index('[INDEX FILES]\n') + 1
                if clsuter_mode and init_cluster:
                    insert_lines = [
                        'external_es_server = true\n',
                        f'es_host = {get_conf("CLUSTER_INIT_ES_HOST", "<your elasticsearch server HOST>")}\n',
                        f'es_port = {get_conf("CLUSTER_INIT_ES_PORT", "9200")}\n'
                    ]
                else:
                    insert_lines = [
                        'external_es_server = true\n',
                        'es_host = elasticsearch\n',
                        'es_port = 9200\n'
                    ]
                fp_lines[section_index:section_index] = insert_lines

                enabled_found = False
                for index in range(section_index, len(fp_lines)):
                    line = fp_lines[index]
                    if line.startswith('['):
                        break
                    if line.split('=', 1)[0].strip() == 'enabled':
                        fp_lines[index] = 'enabled = false\n'
                        enabled_found = True
                        break
                if not enabled_found:
                    fp_lines.insert(section_index + len(insert_lines), 'enabled = false\n')

            if '[SEASEARCH]\n' not in fp_lines:
                fp_lines.extend([
                    '\n[SEASEARCH]\n',
                    'enabled = true\n',
                    'seasearch_url = http://seasearch:4080\n',
                    'seasearch_token = <your auth token>\n',
                    'interval = 10m\n',
                    '\n',
                    '# if you would like to enable full-text indexing (i.e., search for document content), also set the option below to true (support from 13.0 Pro)\n',
                    'index_office_pdf = true\n'
                ])

        with open(join(topdir, 'conf', 'seafevents.conf'), 'w') as fp:
            fp.writelines(fp_lines)

    # Modify seafdav config
    if os.path.exists(join(topdir, 'conf', 'seafdav.conf')):
        with open(join(topdir, 'conf', 'seafdav.conf'), 'r') as fp:
            fp_lines = fp.readlines()
            if 'share_name = /\n' in fp_lines:
               replace_index = fp_lines.index('share_name = /\n')
               replace_line = 'share_name = /seafdav\n'
               fp_lines[replace_index] = replace_line
        with open(join(topdir, 'conf', 'seafdav.conf'), 'w') as fp:
            fp.writelines(fp_lines)

    # Modify seafile config
    if is_pro_version():
        # for seafile-pro-server
        with open(join(topdir, 'conf', 'seafile.conf'), 'a+') as fp:
            if clsuter_mode and init_cluster:
                fp.write('\n[cluster]')
                fp.write('\nenable = true')
                fp.write('\n')

    # After the setup script creates all the files inside the
    # container, we need to move them to the shared volume
    #
    # e.g move "/opt/seafile/seafile-data" to "/shared/seafile/seafile-data"
    files_to_copy = ['conf', 'ccnet', 'seafile-data', 'seahub-data', 'pro-data']
    for fn in files_to_copy:
        src = join(topdir, fn)
        dst = join(shared_seafiledir, fn)
        if not exists(dst) and exists(src):
            call('mv -f ' + str(src) + ' ' + str(dst))
            call('ln -sf ' + str(dst) + ' ' + str(src))

    gen_custom_dir()

    loginfo('Updating version stamp')
    update_version_stamp(os.environ['SEAFILE_VERSION'])

    # non root 
    non_root = os.getenv('NON_ROOT', default='') == 'true'
    if non_root:
        call('chmod -R a+rwx /shared/')
