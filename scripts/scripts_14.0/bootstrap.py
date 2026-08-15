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
    'CF_ENABLE_SEARCH',
    'CF_ENABLE_FILE_PREVIEW',
    'CF_ENABLE_ONLYOFFICE',
    'CF_ENABLE_FILE_LOCK',
    'CF_ENABLE_WATCH',
    'CF_ENABLE_CONVERT_EXPORT',
    'CF_ENABLE_CHECKOUT',
    'CF_ENABLE_LOCAL_APP',
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
    body += _settings_block_search()
    body += _settings_block_external_sources()
    body += _settings_block_office()
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

    client_id = get_conf('CF_SSO_OAUTH_CLIENT_ID', '').strip()
    if client_id:
        def boolean(name, default):
            raw = get_conf(name, default).strip().lower()
            if raw not in ('true', 'false'):
                raise Exception('%s must be true or false' % name)
            return raw == 'true'

        insecure = boolean('CF_SSO_OAUTH_INSECURE', 'false')

        def endpoint(name, required=True):
            """Return a safe OAuth endpoint or fail while startup is visible."""
            from urllib.parse import urlsplit

            value = get_conf(name, '').strip()
            if not value:
                if required:
                    raise Exception('%s is required when OAuth login is enabled'
                                    % name)
                return ''

            parsed = urlsplit(value)
            allowed_schemes = ('http', 'https') if insecure else ('https',)
            if parsed.scheme not in allowed_schemes or not parsed.hostname:
                transport = 'http(s)' if insecure else 'https'
                raise Exception('%s must be an absolute %s URL, got %r'
                                % (name, transport, value))
            if parsed.username or parsed.password or parsed.fragment:
                raise Exception('%s must not contain userinfo or a fragment'
                                % name)
            return value

        proto = get_proto()
        host = get_conf('SEAFILE_SERVER_HOSTNAME', 'seafile.example.com')

        # Derived rather than configured. A redirect URL that disagrees with
        # the deployment's own hostname fails at the identity provider, which
        # reports it as a generic "invalid redirect_uri" -- a long way from the
        # typo that caused it, and in a place the operator cannot see logs.
        redirect_url = '%s://%s/oauth/callback/' % (proto, host)

        client_secret = get_conf('CF_SSO_OAUTH_CLIENT_SECRET', '').strip()
        if not client_secret:
            raise Exception('CF_SSO_OAUTH_CLIENT_SECRET is required when '
                            'CF_SSO_OAUTH_CLIENT_ID is set')

        authorization_url = endpoint('CF_SSO_OAUTH_AUTHORIZATION_URL')
        token_url = endpoint('CF_SSO_OAUTH_TOKEN_URL')
        user_info_url = endpoint('CF_SSO_OAUTH_USER_INFO_URL')
        logout_url = endpoint('CF_SSO_OAUTH_LOGOUT_URL', required=False)
        provider = get_conf('CF_SSO_OAUTH_PROVIDER', '').strip()
        if not provider:
            raise Exception('CF_SSO_OAUTH_PROVIDER is required when OAuth '
                            'login is enabled')

        scope = get_conf('CF_SSO_OAUTH_SCOPE', 'openid email profile').split()
        if not scope:
            raise Exception('CF_SSO_OAUTH_SCOPE must list at least one scope')

        uid_claim = get_conf('CF_SSO_OAUTH_UID_CLAIM', 'sub').strip()
        email_claim = get_conf('CF_SSO_OAUTH_EMAIL_CLAIM', 'email').strip()
        name_claim = get_conf('CF_SSO_OAUTH_NAME_CLAIM', 'name').strip()
        if not uid_claim or not email_claim:
            raise Exception('CF_SSO_OAUTH_UID_CLAIM and '
                            'CF_SSO_OAUTH_EMAIL_CLAIM must not be empty')

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
            % (insecure,),
            'OAUTH_CLIENT_ID = %r' % client_id,
            'OAUTH_CLIENT_SECRET = %r' % client_secret,
            'OAUTH_AUTHORIZATION_URL = %r' % authorization_url,
            'OAUTH_TOKEN_URL = %r' % token_url,
            'OAUTH_USER_INFO_URL = %r' % user_info_url,
            'OAUTH_SCOPE = %r' % scope,
            'OAUTH_PROVIDER = %r' % provider,
            'OAUTH_REDIRECT_URL = %r' % redirect_url,
            'OAUTH_ATTRIBUTE_MAP = %r' % (attribute_map,),
            # Seahub redirects an OAuth-authenticated user's local logout to
            # this configured RP-initiated logout endpoint.  Authentik's
            # end-session URL is supplied by the operator; no provider-
            # specific protocol code is introduced here.
            'OAUTH_LOGOUT_URL = %r' % logout_url,
            'OAUTH_CREATE_UNKNOWN_USER = %r'
            % boolean('CF_SSO_OAUTH_CREATE_UNKNOWN_USER', 'true'),
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


def _settings_block_search():
    """Which search backend answers a query, or nothing when CF_ENABLE_SEARCH
    is off.

    Whether SeaSearch itself is configured is written separately, into
    seafevents.conf -- see the `[SEASEARCH]` block below, which this switch
    also gates. This block only ever writes CF_PROVIDER_SEARCH (empty, the
    default, meaning SeaSearch/native) and the Meilisearch settings that
    matter when an operator sets it to 'meilisearch'. See docs/search.md.
    """
    if not cf_enabled('CF_ENABLE_SEARCH'):
        return ''

    def positive_int(name, default):
        raw = get_conf(name, str(default))
        try:
            value = int(raw)
        except ValueError:
            raise Exception('%s must be an integer' % name)
        if value <= 0:
            raise Exception('%s must be positive' % name)
        return value

    lines = [
        'CF_PROVIDER_SEARCH = %r' % get_conf('CF_PROVIDER_SEARCH', ''),
        'CF_MEILISEARCH_URL = %r'
        % get_conf('CF_MEILISEARCH_URL', 'http://meilisearch:7700'),
        'CF_MEILISEARCH_API_KEY = %r' % get_conf('CF_MEILISEARCH_API_KEY', ''),
        'CF_SEARCH_INDEX_INTERVAL = %r'
        % positive_int('CF_SEARCH_INDEX_INTERVAL', 60),
        'CF_SEARCH_INDEX_TEXT_MAX_BYTES = %r'
        % positive_int('CF_SEARCH_INDEX_TEXT_MAX_BYTES', 1024 * 1024),
    ]
    return '\n'.join(lines) + '\n'


def _settings_block_external_sources():
    """Where an external source's root may live, or nothing when the switch is off.

    Only one setting, and it is the capability's security boundary: an external
    source is an SMB/NFS share the operator mounted on the host and bind-mounted
    into the container, so this list separates "a share ops chose to expose"
    from "any path in the container".

    An empty value is refused rather than passed through. Empty would reach
    cloudfile_ext as "no prefixes configured", and the one reading that must
    never be possible is the inverted one -- an admin API that can register / as
    an external source. Failing here means a bad .env stops the deployment while
    somebody is looking at it, instead of at the first request.

    See docs/external-sources.md section three.
    """
    if not cf_enabled('CF_ENABLE_EXTERNAL_SOURCES'):
        return ''

    def positive_int(name, default):
        raw = get_conf(name, str(default))
        try:
            value = int(raw)
        except ValueError:
            raise Exception('%s must be an integer' % name)
        if value <= 0:
            raise Exception('%s must be positive' % name)
        return value

    raw = get_conf('CF_EXTERNAL_SOURCES_ROOTS', '/shared/external')
    roots = [part.strip() for part in raw.split(':') if part.strip()]
    if not roots:
        raise Exception('CF_EXTERNAL_SOURCES_ROOTS must list at least one '
                        'absolute path')
    for root in roots:
        if not root.startswith('/'):
            raise Exception('CF_EXTERNAL_SOURCES_ROOTS entries must be '
                            'absolute paths, got %r' % root)
        if root == '/':
            raise Exception('CF_EXTERNAL_SOURCES_ROOTS must not contain "/"; '
                            'point it at a directory holding nothing but '
                            'mounts')

    return ('CF_EXTERNAL_SOURCES_ROOTS = %r\n'
            'CF_EXTERNAL_SCAN_INTERVAL = %r\n'
            'CF_EXTERNAL_SCAN_MAX_DIRS = %r\n'
            'CF_EXTERNAL_SCAN_MAX_FILES = %r\n') % (
                roots,
                positive_int('CF_EXTERNAL_SCAN_INTERVAL', 60),
                positive_int('CF_EXTERNAL_SCAN_MAX_DIRS', 20),
                positive_int('CF_EXTERNAL_SCAN_MAX_FILES', 2000),
            )


def _settings_block_office():
    """OnlyOffice startup contract, or nothing at all when the switch is off.

    OFFICE-01: enabling OnlyOffice requires a matching, non-empty JWT on Hub
    and Document Server. Compose injects the same ONLYOFFICE_JWT_SECRET env
    into the Hub, the worker and the Document Server container, so a single
    source feeds both sides -- that is the runtime pairing proof, not a
    fingerprint endpoint. Missing or blank secret/APIJS URL fails startup
    here, while the operator is watching, rather than letting the callback
    view fall back to the legacy "empty secret means authenticated" mode that
    this plan removes.

    The renderer also needs ONLYOFFICE_APIJS_URL (upstream derives the
    converter URL from it), and CloudFile derives the trusted origin for the
    callback download from that same URL so the SSRF boundary stays tied to
    the configured Document Server rather than to a second knob.

    Iron rule: switch off writes nothing. Upstream ENABLE_ONLYOFFICE defaults
    to False and is not overridden, so a deployment that has not opted in is
    byte-for-byte native CE.
    """
    if not cf_enabled('CF_ENABLE_ONLYOFFICE'):
        return ''

    from urllib.parse import urlsplit

    secret = get_conf('ONLYOFFICE_JWT_SECRET', '').strip()
    if not secret:
        raise Exception(
            'ONLYOFFICE_JWT_SECRET is required when CF_ENABLE_ONLYOFFICE=true; '
            'set the same non-empty value on the Hub, the worker and the '
            'Document Server (compose injects one ONLYOFFICE_JWT_SECRET into '
            'all three). Missing or empty secret would otherwise let '
            'unsigned callbacks through, which is exactly what this gate '
            'removes.')

    apijs_url = get_conf('ONLYOFFICE_APIJS_URL', '').strip()
    if not apijs_url:
        raise Exception(
            'ONLYOFFICE_APIJS_URL is required when CF_ENABLE_ONLYOFFICE=true; '
            'point it at the Document Server '
            '"/web-apps/apps/api/documents/api.js" the renderer loads.')

    parsed = urlsplit(apijs_url)
    if parsed.scheme not in ('http', 'https'):
        raise Exception(
            'ONLYOFFICE_APIJS_URL must be an http(s) absolute URL, got %r'
            % apijs_url)
    if not parsed.hostname:
        raise Exception(
            'ONLYOFFICE_APIJS_URL must include a hostname, got %r' % apijs_url)
    # Normalized origin used by the callback download as its sole trust
    # boundary: scheme + hostname + effective port (omit the default port for
    # the scheme). userinfo/fragment/path never enter this value.
    default_port = 443 if parsed.scheme == 'https' else 80
    port = parsed.port
    if port and port != default_port:
        trusted_origin = '%s://%s:%d' % (parsed.scheme, parsed.hostname, port)
    else:
        trusted_origin = '%s://%s' % (parsed.scheme, parsed.hostname)

    def positive_int(name, default):
        raw = get_conf(name, str(default))
        try:
            value = int(raw)
        except ValueError:
            raise Exception('%s must be an integer' % name)
        if value <= 0:
            raise Exception('%s must be positive' % name)
        return value

    lines = [
        # Upstream gate on the renderer. Native CE default is False; we only
        # raise it when the secure configuration is complete.
        'ENABLE_ONLYOFFICE = True',
        # Same-source JWT shared with the Document Server. The callback view
        # rejects any token that does not verify under this secret, and
        # rejects every callback outright when the secret is empty.
        'ONLYOFFICE_JWT_SECRET = %r' % secret,
        # Renderer + converter endpoint. Upstream derives ONLYOFFICE_CONVERTER_URL
        # from this in seahub/onlyoffice/settings.py.
        'ONLYOFFICE_APIJS_URL = %r' % apijs_url,
        # Trusted Document Server origin for the callback download. The
        # callback download refuses any URL whose scheme+host+port differs.
        'CF_ONLYOFFICE_TRUSTED_ORIGIN = %r' % trusted_origin,
        # Bounded streaming download, with a safe default (256 MiB). The
        # callback download streams into a tempfile and fails closed when the
        # declared or actual byte count exceeds this cap.
        'CF_ONLYOFFICE_DOWNLOAD_MAX_BYTES = %r'
        % positive_int('CF_ONLYOFFICE_DOWNLOAD_MAX_BYTES', 256 * 1024 * 1024),
    ]
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

    # Tags are a specialized metadata column in the upstream schema.  Starting
    # with only the tag switch creates a UI promise with no metadata backend to
    # serve it, so reject that split configuration before Seahub starts.
    if (cf_enabled('CF_ENABLE_TAGS')
            and not cf_enabled('CF_ENABLE_METADATA')):
        raise Exception('CF_ENABLE_TAGS requires CF_ENABLE_METADATA')

    if cf_enabled('CF_ENABLE_METADATA'):
        server_url = get_conf('CF_METADATA_SERVER_URL', 'http://cloudfile-metadata:8084')
        lines += [
            'ENABLE_METADATA_MANAGEMENT = True',
            'INNER_METADATA_SERVER_URL = %r' % server_url,
        ]

    if cf_enabled('CF_ENABLE_AUDIT'):
        lines += [
            'ENABLE_FILE_AUDIT = True',
        ]

    if (cf_enabled('CF_ENABLE_CONVERT_EXPORT')
            and not get_conf('JWT_PRIVATE_KEY', '')):
        raise Exception(
            'JWT_PRIVATE_KEY is required when CF_ENABLE_CONVERT_EXPORT=true')

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


def _seafile_conf_cloudfile_lines():
    """The [cloudfile] section of seafile.conf, as a list of lines.

    Pure: environment in, strings out, no file I/O. Same shape and the same
    reason as the _settings_block_* helpers -- tools/test-bootstrap-settings.py
    can execute this exact source against a synthetic .env, so the generated
    values are asserted rather than assumed. A hand-written fixture proves
    nothing; that is how DATABASES['cloudfile'] got shipped.
    """
    lines = ['[cloudfile]\n']
    for name in CF_FEATURE_SWITCHES:
        key = name[len('CF_ENABLE_'):].lower() + '_enabled'
        lines.append('%s = %s\n'
                     % (key, 'true' if cf_enabled(name) else 'false'))

    if cf_enabled('CF_ENABLE_FILE_LOCK'):
        backend = get_conf('CF_LOCK_BACKEND', 'cloudfile').lower()
        if backend != 'cloudfile':
            raise Exception('CF_LOCK_BACKEND must be cloudfile in the CE image')
        lines.append('lock_backend = cloudfile\n')

    # The write lifecycle test provider. Deliberately NOT a CF_ENABLE_* switch:
    # those are product capabilities an operator may reasonably turn on, and
    # this is an instrument for the fileop gate that must never be on in
    # production. Keeping it out of that tuple also keeps it out of the admin
    # page and the features API, both of which enumerate CF_FEATURE_SWITCHES.
    #
    # See cloudfile-server/common/cf-fileop-test.h for why it is gated at
    # runtime rather than compiled out.
    if get_conf('CF_FILEOP_TEST_PROVIDER', 'false').lower() == 'true':
        token = get_conf('CF_FILEOP_TEST_REFUSE_TOKEN', 'cf-refuse')
        # An empty token is meaningful, not missing: phase 1 of the gate runs
        # in observe mode, where the provider journals but refuses nothing.
        # So this must not fall back to the default when explicitly blank.
        if '/' in token:
            raise Exception('CF_FILEOP_TEST_REFUSE_TOKEN is a single path '
                            'component, not a path')
        journal = get_conf('CF_FILEOP_TEST_JOURNAL',
                           '/shared/cf-fileop-journal.log')
        if journal and not journal.startswith('/'):
            raise Exception('CF_FILEOP_TEST_JOURNAL must be an absolute path')
        lines += [
            'fileop_test_provider_enabled = true\n',
            'fileop_test_refuse_token = %s\n' % token,
            'fileop_test_journal = %s\n' % journal,
        ]
    else:
        lines.append('fileop_test_provider_enabled = false\n')

    return lines


def write_cloudfile_seafile_conf():
    """Mirror the capability switches into seafile.conf for seaf-server.

    Seahub's copy only decides what the UI shows; this one governs the
    authoritative checks that WebDAV and the sync client go through. Both are
    derived from the same environment variables so they cannot drift apart.

    The key name is derived mechanically -- CF_ENABLE_DIR_ACL becomes
    dir_acl_enabled -- so a new capability needs no change here.
    """
    lines = _seafile_conf_cloudfile_lines()

    # Keep the S3 configuration in the same restart-safe generated block as
    # the feature switches.  The server processes need these values in
    # seafile.conf; leaving them only in compose would make a restart silently
    # fall back to the local filesystem.
    if cf_enabled('CF_ENABLE_S3_STORAGE'):
        storage_type = get_conf('SEAF_SERVER_STORAGE_TYPE', '').lower()
        if storage_type not in ('s3', 'multiple'):
            raise Exception('SEAF_SERVER_STORAGE_TYPE must be s3 or multiple when CF_ENABLE_S3_STORAGE=true')
        if storage_type == 'multiple':
            classes = get_conf('CF_STORAGE_CLASSES_JSON', '')
            if not classes:
                raise Exception('CF_STORAGE_CLASSES_JSON is required when SEAF_SERVER_STORAGE_TYPE=multiple')
            try:
                classes = json.loads(classes)
            except ValueError as e:
                raise Exception('CF_STORAGE_CLASSES_JSON is not valid JSON: %s' % e)
            if not isinstance(classes, list) or not classes:
                raise Exception('CF_STORAGE_CLASSES_JSON must be a non-empty JSON array')
            classes_path = join(topdir, 'conf', 'seafile_storage_classes.json')
            with open(classes_path, 'w') as fp:
                json.dump(classes, fp, indent=2, sort_keys=True)
                fp.write('\n')
            os.chmod(classes_path, 0o600)
            lines += [
                '\n[storage]\n',
                'enable_storage_classes = true\n',
                'storage_classes_file = %s\n' % classes_path,
            ]
            for section in ('commit_object_backend', 'fs_object_backend', 'block_backend'):
                lines.append('\n[%s]\nname = multiple\n' % section)
            _replace_block(join(topdir, 'conf', 'seafile.conf'),
                           CF_BEGIN, CF_END, ''.join(lines))
            return

        values = {
            'bucket': None,
            'key_id': get_conf('S3_KEY_ID', ''),
            'key': get_conf('S3_SECRET_KEY', ''),
            'host': get_conf('S3_HOST', ''),
            'use_v4_signature': get_conf('S3_USE_V4_SIGNATURE', 'true'),
            'aws_region': get_conf('S3_AWS_REGION', 'us-east-1'),
            'use_https': get_conf('S3_USE_HTTPS', 'true'),
            'path_style_request': get_conf('S3_PATH_STYLE_REQUEST', 'true'),
            'connection_timeout': get_conf('CF_S3_CONNECTION_TIMEOUT', '10'),
            'request_timeout': get_conf('CF_S3_REQUEST_TIMEOUT', '60'),
            'max_retries': get_conf('CF_S3_MAX_RETRIES', '2'),
        }
        for name in ('key_id', 'key', 'host'):
            if not values[name]:
                raise Exception('S3_%s is required when CF_ENABLE_S3_STORAGE=true' % name.upper())
        for section, env_name in (
                ('commit_object_backend', 'S3_COMMIT_BUCKET'),
                ('fs_object_backend', 'S3_FS_BUCKET'),
                ('block_backend', 'S3_BLOCK_BUCKET')):
            bucket = get_conf(env_name, '')
            if not bucket:
                raise Exception('%s is required when CF_ENABLE_S3_STORAGE=true' % env_name)
            lines.append('\n[%s]\nname = s3\n' % section)
            lines.append('bucket = %s\n' % bucket)
            for name, value in values.items():
                if name != 'bucket':
                    lines.append('%s = %s\n' % (name, value))

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

    configured_jwt_key = get_conf('JWT_PRIVATE_KEY', '')
    if (existing.get('JWT_PRIVATE_KEY') and configured_jwt_key
            and existing['JWT_PRIVATE_KEY'] != configured_jwt_key):
        raise Exception('JWT_PRIVATE_KEY does not match the persisted Seafile key')
    jwt_key = existing.get('JWT_PRIVATE_KEY') or configured_jwt_key or secrets.token_hex(32)

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


def apply_metadata_schema_compatibility():
    """Repair the upstream 14.0 metadata schema when the capability is on.

    Seahub 14.0's ``RepoMetadata`` model unconditionally reads
    ``summary_enabled``, but its fresh-install SQL and 14.0 upgrade SQL both
    omit that column.  This makes even the status endpoint return 500 on a
    new installation before an operator has enabled any AI feature.

    Keep the narrowly scoped compatibility migration here rather than editing
    the upstream SQL files: it must also cover an existing CE deployment that
    adopts CloudFile without running Seafile's versioned upgrade scripts.  It
    is gated by the metadata capability, checks the actual schema first, and
    is safe on every restart.
    """
    if not (cf_enabled('CF_ENABLE_METADATA') or cf_enabled('CF_ENABLE_TAGS')):
        return

    import pymysql

    conn = pymysql.connect(
        host=get_conf('SEAFILE_MYSQL_DB_HOST', 'db'),
        port=int(get_conf('SEAFILE_MYSQL_DB_PORT', '3306')),
        user=get_conf('SEAFILE_MYSQL_DB_USER', 'seafile'),
        password=get_conf('SEAFILE_MYSQL_DB_PASSWORD', ''),
        database=get_conf('SEAFILE_MYSQL_DB_SEAHUB_DB_NAME', 'seahub_db'),
        charset='utf8mb4',
    )
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                'SELECT 1 FROM information_schema.TABLES '
                'WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s',
                ('repo_metadata',))
            if not cursor.fetchone():
                logwarning('repo_metadata is missing; cannot apply metadata schema compatibility')
                return

            cursor.execute(
                'SELECT 1 FROM information_schema.COLUMNS '
                'WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s '
                'AND COLUMN_NAME = %s',
                ('repo_metadata', 'summary_enabled'))
            if not cursor.fetchone():
                cursor.execute(
                    'ALTER TABLE `repo_metadata` '
                    'ADD COLUMN `summary_enabled` TINYINT(1) NOT NULL DEFAULT 0')
                cursor.execute(
                    'ALTER TABLE `repo_metadata` '
                    'ADD KEY `key_repo_metadata_summary_enabled` (`summary_enabled`)')
                loginfo('Added missing repo_metadata.summary_enabled compatibility column')
        conn.commit()
    finally:
        conn.close()


def apply_tag_schema_compatibility():
    """Add the CloudFile is_system column to the upstream repo_tags table.

    P2-07 classifies repo tags as system (admin-managed, read-only) or user
    (rw-editable). The marker lives on the upstream ``repo_tags_repotags`` table
    in seahub-db, which is owned by Seahub's own SQL rather than by CloudFile, so
    -- like ``apply_metadata_schema_compatibility`` -- this repairs the schema
    here instead of editing the upstream SQL files.

    Unlike the metadata compatibility shim this is NOT gated on the tags switch:
    ``is_system`` is a field on the always-imported ``RepoTags`` model, so Django
    SELECTs it on every native repo-tags query regardless of ``CF_ENABLE_TAGS``.
    A missing column would therefore 500 the endpoint even with all switches off.
    The column defaults to 0, which is exactly native CE behaviour (no system
    tags), so adding it unconditionally changes no semantics. It must cover fresh
    installs, upgrades and an existing CE deployment adopting CloudFile, so it
    checks the actual schema first and is safe to run on every start.
    """
    import pymysql

    conn = pymysql.connect(
        host=get_conf('SEAFILE_MYSQL_DB_HOST', 'db'),
        port=int(get_conf('SEAFILE_MYSQL_DB_PORT', '3306')),
        user=get_conf('SEAFILE_MYSQL_DB_USER', 'seafile'),
        password=get_conf('SEAFILE_MYSQL_DB_PASSWORD', ''),
        database=get_conf('SEAFILE_MYSQL_DB_SEAHUB_DB_NAME', 'seahub_db'),
        charset='utf8mb4',
    )
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                'SELECT 1 FROM information_schema.TABLES '
                'WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s',
                ('repo_tags_repotags',))
            if not cursor.fetchone():
                logwarning('repo_tags_repotags is missing; cannot apply tag schema compatibility')
                return

            cursor.execute(
                'SELECT 1 FROM information_schema.COLUMNS '
                'WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s '
                'AND COLUMN_NAME = %s',
                ('repo_tags_repotags', 'is_system'))
            if not cursor.fetchone():
                cursor.execute(
                    'ALTER TABLE `repo_tags_repotags` '
                    'ADD COLUMN `is_system` TINYINT(1) NOT NULL DEFAULT 0')
                cursor.execute(
                    'ALTER TABLE `repo_tags_repotags` '
                    'ADD KEY `repo_tags_repotags_is_system` (`is_system`)')
                loginfo('Added repo_tags_repotags.is_system compatibility column')
        conn.commit()
    finally:
        conn.close()


def _set_ini_value(lines, start, end, key, value):
    """Set `key = value` within lines[start:end], appending if absent.

    Returns the (possibly shifted) end index of the section, since appending
    grows the list.
    """
    for i in range(start, end):
        if lines[i].split('=', 1)[0].strip() == key:
            lines[i] = '%s = %s\n' % (key, value)
            return end
    lines.insert(end, '%s = %s\n' % (key, value))
    return end + 1


def write_seafevents_search_config():
    """Point seafevents at SeaSearch, gated on CF_ENABLE_SEARCH.

    Written on every start (called from write_cloudfile_config()), unlike the
    old code this replaces, which lived in init_seafile_server() and only ever
    ran once, at first install. init_seafile_server() returns early once
    seafile-data exists, so anything written only there can never react to a
    switch an operator flips afterwards -- silently: seafevents would carry on
    reading whatever [SEASEARCH] section fresh-install wrote forever. That is
    the same trap write_cloudfile_settings() exists to avoid; see this file's
    module docstring / AGENTS.md's "配置在每次启动时重写" note.

    CF_ENABLE_SEARCH off (the default) writes `enabled = false`, so a
    deployment that has not opted in behaves like native CE -- the section can
    exist in seafevents.conf either way, only its `enabled` value governs
    HAS_FILE_SEASEARCH (seahub/utils/__init__.py's check_seasearch_enabled()).
    See docs/search.md.
    """
    path = join(topdir, 'conf', 'seafevents.conf')
    if not exists(path):
        return

    with open(path, 'r') as fp:
        fp_lines = fp.readlines()

    values = {
        'enabled': 'true' if cf_enabled('CF_ENABLE_SEARCH') else 'false',
        'seasearch_url': 'http://seasearch:4080',
        'seasearch_token': get_conf('CF_SEASEARCH_TOKEN', ''),
        # Upstream's own default. Overridable because it directly bounds how
        # long an e2e/capability test has to wait for SeaSearch to pick up a
        # newly written file -- 10 minutes is a fine default for a real
        # deployment and unusable for a CI job.
        'interval': get_conf('CF_SEASEARCH_INTERVAL', '10m'),
    }

    if '[SEASEARCH]\n' not in fp_lines:
        fp_lines += [
            '\n[SEASEARCH]\n',
            'enabled = %s\n' % values['enabled'],
            'seasearch_url = %s\n' % values['seasearch_url'],
            'seasearch_token = %s\n' % values['seasearch_token'],
            'interval = %s\n' % values['interval'],
            '\n',
            '# if you would like to enable full-text indexing (i.e., search for document content), also set the option below to true (support from 13.0 Pro)\n',
            'index_office_pdf = true\n',
        ]
    else:
        section_index = fp_lines.index('[SEASEARCH]\n') + 1
        end = len(fp_lines)
        for i in range(section_index, len(fp_lines)):
            if fp_lines[i].startswith('['):
                end = i
                break
        for key in ('enabled', 'seasearch_url', 'seasearch_token', 'interval'):
            end = _set_ini_value(fp_lines, section_index, end, key, values[key])

    with open(path, 'w') as fp:
        fp.writelines(fp_lines)


def write_seafevents_audit_config():
    """Point seafevents at file-audit collection, gated on CF_ENABLE_AUDIT.

    This is the read/download/preview access log (Seafile Pro's FileAudit),
    distinct from CloudFile's own commit-diff operation log (the Activity
    table behind /cloudfile/audit/). Upstream CE ships the whole data path --
    seahub publishes 'seahub.audit' events, seafevents' FileAuditEventHandler
    persists them to the FileAudit table when [Audit] enabled=true -- but the
    section is never written, so seafevents never registers the handler and
    the table stays empty. Writing it on every start (not just first install)
    keeps a switch flip in .env effective, mirroring write_seafevents_search_config().
    """
    path = join(topdir, 'conf', 'seafevents.conf')
    if not exists(path):
        return

    with open(path, 'r') as fp:
        fp_lines = fp.readlines()

    values = {
        'enabled': 'true' if cf_enabled('CF_ENABLE_AUDIT') else 'false',
    }

    # is_audit_enabled()/init_message_handlers() accept either [Audit] or
    # [AUDIT]; canonicalise on [Audit] and reuse whichever is already present.
    if '[Audit]\n' not in fp_lines and '[AUDIT]\n' not in fp_lines:
        fp_lines += [
            '\n[Audit]\n',
            'enabled = %s\n' % values['enabled'],
            '\n',
        ]
    else:
        section_index = fp_lines.index('[Audit]\n') + 1 \
            if '[Audit]\n' in fp_lines else fp_lines.index('[AUDIT]\n') + 1
        end = len(fp_lines)
        for i in range(section_index, len(fp_lines)):
            if fp_lines[i].startswith('['):
                end = i
                break
        end = _set_ini_value(fp_lines, section_index, end, 'enabled', values['enabled'])

    with open(path, 'w') as fp:
        fp.writelines(fp_lines)


def write_cloudfile_config():
    """Apply CloudFile configuration. Safe to call on every start."""
    loginfo('Applying CloudFile configuration')
    write_seafile_env()
    write_cloudfile_settings()
    write_cloudfile_seafile_conf()
    write_seafevents_search_config()
    write_seafevents_audit_config()
    apply_cloudfile_schema()
    apply_metadata_schema_compatibility()
    apply_tag_schema_compatibility()


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

    # Point [INDEX FILES] at the cluster's Elasticsearch and leave it disabled
    # by default -- native upstream behaviour. CloudFile's own SeaSearch
    # section is written separately by write_seafevents_search_config(), which
    # (unlike this fresh-install-only block) runs on every start so that
    # CF_ENABLE_SEARCH takes effect on a switch flip, not only at first
    # install -- see that function's docstring.
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
