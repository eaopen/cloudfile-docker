#!/usr/bin/env python3
#coding: UTF-8

"""
Bootstraping seafile server, letsencrypt (verification & cron job).
"""

import argparse
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

    body += (
        "DATABASES['cloudfile'] = {\n"
        "    'ENGINE': 'django.db.backends.mysql',\n"
        "    'NAME': '%s',\n"
        "    'USER': '%s',\n"
        "    'PASSWORD': '%s',\n"
        "    'HOST': '%s',\n"
        "    'PORT': '%s',\n"
        "    'OPTIONS': {'charset': 'utf8mb4'},\n"
        "}\n"
        "DATABASE_ROUTERS = ['cloudfile_ext.db_router.CloudFileRouter']\n"
    ) % (
        get_conf('SEAFILE_MYSQL_DB_SEAFILE_DB_NAME', 'seafile_db'),
        get_conf('SEAFILE_MYSQL_DB_USER', 'seafile'),
        get_conf('SEAFILE_MYSQL_DB_PASSWORD', ''),
        get_conf('SEAFILE_MYSQL_DB_HOST', 'db'),
        get_conf('SEAFILE_MYSQL_DB_PORT', '3306'),
    )

    _replace_block(join(topdir, 'conf', 'seahub_settings.py'),
                   CF_BEGIN, CF_END, body)


def write_cloudfile_seafile_conf():
    """Tell seaf-server whether to enforce directory ACL.

    Separate from the Seahub switch on purpose: Seahub's copy only decides what
    the UI shows, while this one governs the authoritative check that WebDAV
    and the sync client go through. Both are written from the same environment
    variable so they cannot drift apart in a compose deployment.
    """
    body = ('[cloudfile]\ndir_acl_enabled = %s\n'
            % ('true' if cf_enabled('CF_ENABLE_DIR_ACL') else 'false'))

    _replace_block(join(topdir, 'conf', 'seafile.conf'),
                   CF_BEGIN, CF_END, body)


def apply_cloudfile_schema():
    """Create the cf_* tables in seafile-db if they are missing.

    Done here rather than in the fresh-install SQL or a versioned upgrade
    script because all three entry points have to work: a new deployment, a
    version upgrade, and an existing Seafile CE installation adopting
    CloudFile. Only the last of those runs no setup or upgrade step at all, and
    without the tables the ACL check fails closed and locks everyone out.

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
