"""Disposable real CE14 C/Go startup and byte tests, not directory ACL acceptance."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import tempfile
import time
from uuid import uuid4

import pymysql
import redis
import requests

from cloudfile_ext.v2.identity import NativeIdentity
from cloudfile_ext.v2.memberships import GroupCatalog, Memberships
from cloudfile_ext.v2.schema import FreshSchema, TABLES


def run():
    source = Path(os.environ['CF_V2_SOURCE'])
    prefix = Path(os.environ['CF_V2_PREFIX'])
    sql_host = os.environ['CF_TEST_DB_HOST']
    sql_port = int(os.environ.get('CF_TEST_DB_PORT', '3306'))
    admin = pymysql.connect(host=sql_host, port=sql_port, user='root', charset='utf8mb4', autocommit=True)
    names = {kind: 'cfv2_runtime_' + uuid4().hex for kind in ('account', 'hub', 'files')}
    database_user, database_password = 'cfv2run_' + uuid4().hex[:16], secrets.token_urlsafe(32)
    processes, handles = [], []
    client, connection, cache_key = None, None, None
    files = {'account': source / 'seafile-server/scripts/sql/mysql/ccnet.sql',
             'hub': source / 'seahub/sql/mysql.sql', 'files': source / 'seafile-server/scripts/sql/mysql/seafile.sql'}
    try:
        with admin.cursor() as cursor:
            for kind, name in names.items():
                cursor.execute('CREATE DATABASE ' + name + ' CHARACTER SET utf8mb4')
                cursor.execute('USE ' + name)
                cursor.execute('SET FOREIGN_KEY_CHECKS=0')
                for match in re.finditer(r'CREATE TABLE[\s\S]+?;', files[kind].read_text()):
                    cursor.execute(match[0])
                cursor.execute('SET FOREIGN_KEY_CHECKS=1')
            cursor.execute('CREATE USER %s@%s IDENTIFIED BY %s', (database_user, '%', database_password))
            for name in names.values():
                cursor.execute('GRANT ALL ON `' + name.replace('_', '\\_') + '`.* TO %s@%s', (database_user, '%'))
        connection = pymysql.connect(host=sql_host, port=sql_port, user=database_user, password=database_password,
                                     database=names['files'], charset='utf8mb4', autocommit=True)
        FreshSchema(connection, (source / 'seafile-server/scripts/sql/mysql/cloudfile-v2.sql').read_text()).install()
        with tempfile.TemporaryDirectory(prefix='cfv2-native-runtime-') as temporary:
            root = Path(temporary)
            conf, ccnet, data = root / 'conf', root / 'ccnet', root / 'seafile-data'
            for directory in (conf, ccnet, data):
                directory.mkdir()
            (conf / 'seafile.conf').write_text(f'''[database]
type=mysql
host={sql_host}
port={sql_port}
user={database_user}
password={database_password}
db_name={names['files']}
ccnet_db_name={names['account']}
connection_charset=utf8mb4
[fileserver]
use_go_fileserver=true
port=8082
''')
            os.environ.update(SEAFILE_DATA_DIR=str(data), SEAFILE_CENTRAL_CONF_DIR=str(conf),
                SEAFILE_MYSQL_DB_HOST=sql_host, SEAFILE_MYSQL_DB_PORT=str(sql_port), SEAFILE_MYSQL_DB_USER=database_user,
                SEAFILE_MYSQL_DB_PASSWORD=database_password,
                SEAFILE_MYSQL_DB_CCNET_DB_NAME=names['account'], SEAFILE_MYSQL_DB_SEAFILE_DB_NAME=names['files'],
                JWT_PRIVATE_KEY=secrets.token_urlsafe(48), CACHE_PROVIDER='redis', ENABLE_GO_FILESERVER='true')
            for label, command in (
                ('server', [str(prefix / 'bin/seaf-server'), '-F', str(conf), '-c', str(ccnet), '-d', str(data), '-l', str(root / 'server.log'), '-f']),
                ('fileserver', [str(prefix / 'bin/fileserver'), '-F', str(conf), '-d', str(data), '-l', str(root / 'fileserver.log')])):
                handle = (root / (label + '.stderr')).open('w')
                handles.append(handle)
                processes.append(subprocess.Popen(command, stdout=handle, stderr=handle))
            deadline = time.monotonic() + 30
            while True:
                try:
                    if not (data / 'seafile.sock').exists():
                        raise ConnectionError('RPC not ready')
                    with socket.create_connection(('127.0.0.1', 8082), timeout=1):
                        break
                except OSError:
                    if time.monotonic() >= deadline or any(p.poll() is not None for p in processes):
                        for log in root.glob('*.log'):
                            print(log.name, log.read_text()[-6000:])
                        for log in root.glob('*.stderr'):
                            print(log.name, log.read_text()[-6000:])
                        raise RuntimeError('native CE14 services did not start') from None
                    time.sleep(.2)
            from seaserv import ccnet_api, seafile_api
            owner = 'native-owner@example.test'
            assert ccnet_api.add_emailuser(owner, '!', 0, 1) == 0
            def create_account(username):
                assert ccnet_api.add_emailuser(username, '!', 0, 1) == 0
            identity = NativeIdentity(connection, account_schema=names['account'], hub_schema=names['hub'],
                                      issuer='https://idp.example.test/', create_account=create_account)
            username = identity.bind(subject='oidc-subject', uid='uid-runtime', login_name='E001')
            assert identity.bind(subject='oidc-subject', uid='uid-runtime', login_name='E999') == username
            catalog = GroupCatalog(connection, account_schema=names['account'], provider='etech',
                create_group=lambda name: ccnet_api.create_group(name, owner))
            group = catalog.ensure('role', 'role', 'r1', 'Runtime role')
            subject = dict(userId='uid-runtime', status='active', attributes={'login_name': 'E999'},
                organizations=[], organization_ancestors=[], roles=[dict(namespace='role', external_id='r1')],
                etag='runtime', generated_at=datetime.now(timezone.utc).isoformat())
            client = redis.Redis(host=os.environ['REDIS_HOST'])
            projector = Memberships(connection, client, identity, account_schema=names['account'], provider='etech', fetch=lambda uid: subject)
            cache_key = projector._key('uid-runtime', username)
            projector.ensure('uid-runtime', username)
            repo = seafile_api.create_repo('Fresh native V2 runtime', '', owner)
            assert repo and seafile_api.get_repo(repo).id == repo
            assert seafile_api.check_permission(repo, username) is None
            assert seafile_api.set_group_repo(repo, group, owner, 'rw') == 0
            assert seafile_api.check_permission(repo, username) == 'rw'
            assert seafile_api.post_dir(repo, '/', 'project', username) == 0
            before = seafile_api.get_repo(repo).head_cmmt_id
            content = b'CloudFile V2 native CE14 upload and download\n' * 4096
            token = seafile_api.get_fileserver_access_token(repo, json.dumps({'parent_dir': '/project'}), 'upload', username, False)
            reply = requests.post('http://127.0.0.1:8082/upload-api/' + token,
                data={'parent_dir': '/project'}, files={'file': ('proof.txt', content)}, timeout=30)
            assert reply.status_code == 200, (reply.status_code, reply.text)
            after = seafile_api.get_repo(repo).head_cmmt_id
            assert before != after
            file_id = seafile_api.get_file_id_by_path(repo, '/project/proof.txt')
            assert file_id
            token = seafile_api.get_fileserver_access_token(repo, file_id, 'download', username, False)
            url = 'http://127.0.0.1:8082/files/' + token + '/proof.txt'
            downloaded = requests.get(url, timeout=30)
            assert downloaded.status_code == 200 and downloaded.content == content
            ranged = requests.get(url, headers={'Range': 'bytes=17-89'}, timeout=30)
            assert ranged.status_code == 206 and ranged.content == content[17:90]
            assert seafile_api.rename_file(repo, '/project', 'proof.txt', 'renamed.txt', username) == 0
            assert seafile_api.get_file_id_by_path(repo, '/project/renamed.txt') == file_id
            assert seafile_api.del_file(repo, '/project', json.dumps(['renamed.txt']), username) == 0
            assert not seafile_api.get_file_id_by_path(repo, '/project/renamed.txt')
            subject.update(roles=[], generated_at=datetime.now(timezone.utc).isoformat())
            projector.ensure('uid-runtime', username, force=True)
            assert seafile_api.check_permission(repo, username) is None
            with connection.cursor() as cursor:
                cursor.execute('SHOW TABLES')
                assert {row[0] for row in cursor.fetchall() if row[0].startswith('cf_')} == TABLES
            print(json.dumps(dict(native_c_started=True, native_go_started=True, native_rpc_accounts=True,
                uid_rename_stable=True, group_projection_and_revocation=True, native_repo_create=True,
                native_group_share=True, http_upload_bytes=len(content), branch_commit_changed=True,
                http_download_bytes=len(content), http_range=True, rename=True, delete=True,
                extension_tables=sorted(TABLES), oidc_login_verified=False, directory_acl_verified=False), sort_keys=True))
            # Shut down before removing private temporary files/databases.
            for process in reversed(processes):
                process.terminate()
                process.wait(timeout=10)
            processes.clear()
    finally:
        for process in reversed(processes):
            process.terminate()
            process.wait(timeout=10)
        for handle in handles:
            handle.close()
        if client is not None:
            if cache_key: client.delete(cache_key)
            client.close()
        if connection is not None:
            connection.close()
        with admin.cursor() as cursor:
            for name in names.values():
                cursor.execute('DROP DATABASE IF EXISTS ' + name)
            cursor.execute('DROP USER IF EXISTS %s@%s', (database_user, '%'))
        admin.close()


if __name__ == '__main__':
    run()
