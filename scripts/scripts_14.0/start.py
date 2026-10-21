#!/usr/bin/env python3
#coding: UTF-8

"""
Starts the seafile/seahub server and watches the controller process. It is
the entrypoint command of the docker container.
"""

import json
import os
from os.path import abspath, basename, exists, dirname, join, isdir
import shutil
import sys
import time

from utils import (
    call, get_conf, get_install_dir, get_script, get_command_output,
    wait_for_mysql, setup_logging
)
from upgrade import check_upgrade
from bootstrap import init_seafile_server, write_cloudfile_config
from cloudfile import write_settings as write_cloudfile_settings
from cloudfile import write_policy_worker_hooks
from cloudfile_schema import prepare_fresh_schema, initialize_fresh_schema, verify_development_schema


shared_seafiledir = '/shared/seafile'
ssl_dir = '/shared/ssl'
generated_dir = '/bootstrap/generated'
installdir = get_install_dir()
topdir = dirname(installdir)

def watch_controller():
    maxretry = 4
    retry = 0
    while retry < maxretry:
        controller_pid = get_command_output('ps aux | grep seafile-monitor.sh | grep -v grep || true').strip()
        garbage_collector_pid = get_command_output('ps aux | grep /scripts/gc.sh | grep -v grep || true').strip()
        if not controller_pid and not garbage_collector_pid:
            retry += 1
        else:
            retry = 0
        time.sleep(5)
    print('seafile monitor exited unexpectedly.')
    sys.exit(1)

def main():
    if not exists(shared_seafiledir):
        os.mkdir(shared_seafiledir)
    rpc_pipe_dir = os.getenv('SEAFILE_RPC_PIPE_PATH')
    if rpc_pipe_dir:
        os.makedirs(rpc_pipe_dir, exist_ok=True)
    if not exists(generated_dir):
        os.makedirs(generated_dir)

    try:
        call('nginx -s reload')
    except Exception as e:
        print(e)

    wait_for_mysql()
    # A truly new volume is marked before CE creates seafile-data. Existing
    # volumes are never marked, so this marker can only authorize one-time
    # initialization, never an automatic upgrade of an existing layout.
    schema_marker = prepare_fresh_schema(shared_seafiledir)
    init_seafile_server()
    write_policy_worker_hooks(join(topdir, 'conf', 'gunicorn.conf.py'), v2=True)
    write_cloudfile_settings(join(topdir, 'conf', 'seahub_settings.py'))

    check_upgrade()

    # CloudFile config is rewritten on every start, after any upgrade has
    # rearranged conf/, so flipping a CF_ENABLE_* switch in .env takes effect
    # on restart rather than only at first bootstrap.
    write_cloudfile_config()
    # Fresh volumes create the reviewed V2 tables once. Existing layouts are
    # only verified below: development-period upgrades stay manual, and an
    # incompatible table is refused instead of being converted automatically.
    initialize_fresh_schema(schema_marker, installdir)
    verify_development_schema(installdir)
    # Legacy defaults must load before the native extension overrides.
    write_cloudfile_settings(join(topdir, 'conf', 'seahub_settings.py'))

    os.chdir(installdir)

    admin_pw = {
        'email': get_conf('INIT_SEAFILE_ADMIN_EMAIL', 'me@example.com'),
        'password': get_conf('INIT_SEAFILE_ADMIN_PASSWORD', 'asecret'),
    }
    password_file = join(topdir, 'conf', 'admin.txt')
    with open(password_file, 'w') as fp:
        json.dump(admin_pw, fp)


    try:
        non_root = os.getenv('NON_ROOT', default='') == 'true'
        if non_root:
            call('su -p seafile -c "{} start"'.format(get_script('seafile.sh')))
            call('su -p seafile -c "{} start"'.format(get_script('seahub.sh')))
        else:
            call('{} start'.format(get_script('seafile.sh')))
            call('{} start'.format(get_script('seahub.sh')))
    finally:
        if exists(password_file):
            os.unlink(password_file)

    print('seafile server is running now.')
    try:
        watch_controller()
    except KeyboardInterrupt:
        print('Stopping seafile server.')
        sys.exit(0)

if __name__ == '__main__':
    setup_logging()
    main()
