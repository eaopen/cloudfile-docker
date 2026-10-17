"""Start CE14 DEV using native services, preserving existing data/config."""
import os
import configparser
import json
from pathlib import Path
import signal
import subprocess
import time
from urllib.parse import urlsplit

import pymysql

from cloudfile_ext.v2.schema import FreshSchema
from cloudfile_ext.v2.native_discovery import NativeLibraryDiscovery
from web_paths import web_settings, nginx_config, read_settings
from native_config import (volume_layout, load_native_environment, native_environment,
                           verify_database_binding, require_native_ce14)


source = Path('/opt/cloudfile-v2/source')
# Fresh V2 installs Checkout Guard; reused data is never silently migrated.

shared = Path('/shared')
# Detect existing native data before creating directories or touching SQL.
root, existing = volume_layout(shared)
data, ccnet, logs = root / 'seafile-data', root / 'ccnet', root / 'logs'
conf = Path('/run/cloudfile-conf') if existing else shared / 'conf'
original = root / 'conf'

if existing:
    # Reuse CE14 native databases and objects in place; no import or schema reset.
    require_native_ce14(data)
    load_native_environment(original, os.environ)
    native_config = configparser.ConfigParser(interpolation=None)
    native_config.read(original / 'seafile.conf')
    settings = read_settings(original / 'seahub_settings.py', {
        'DATABASES', 'SECRET_KEY', 'TIME_ZONE', 'LOGIN_URL', 'LOGIN_REDIRECT_URL', 'SITE_ROOT', 'FILE_SERVER_ROOT',
        'CF_MEILISEARCH_URL', 'CF_MEILISEARCH_API_KEY', 'CF_MEILISEARCH_INDEX',
        'CF_DIRECTORY_URL', 'CF_DIRECTORY_SECRET', 'CF_DIRECTORY_KEY_ID',
        'CF_DIRECTORY_ISSUER', 'CF_DIRECTORY_AUDIENCE',
        'CF_DIRECTORY_GROUP_OWNER', 'CF_DIRECTORY_SUBJECT_TTL'})
    if not settings.get('SECRET_KEY'):
        raise ValueError('existing deployment SECRET_KEY is required')
    native_environment(native_config, settings, os.environ)
    host = os.environ['SEAFILE_MYSQL_DB_HOST']
    password = os.environ['SEAFILE_MYSQL_DB_PASSWORD']
    user = os.environ['SEAFILE_MYSQL_DB_USER']
    names = {'account': os.environ['SEAFILE_MYSQL_DB_CCNET_DB_NAME'],
             'files': os.environ['SEAFILE_MYSQL_DB_SEAFILE_DB_NAME'],
             'hub': os.environ['SEAFILE_MYSQL_DB_SEAHUB_DB_NAME']}
    public_url = os.environ.get('PUBLIC_URL') or (
        os.environ.get('SEAFILE_SERVER_PROTOCOL', 'http') + '://' + os.environ['SEAFILE_SERVER_HOSTNAME'])
    verify_database_binding(native_config, os.environ, settings)
    with pymysql.connect(host=host, port=int(os.environ.get('SEAFILE_MYSQL_DB_PORT', '3306')),
                         user=user, password=password, database=names['files'], autocommit=True) as connection:
        NativeLibraryDiscovery.check_native_schema(connection)
    # Write only ephemeral configuration after native database binding checks.
    for directory in (ccnet, logs, conf):
        directory.mkdir(parents=True, exist_ok=True)
    with (conf / 'seafile.conf').open('w') as output:
        native_config.write(output)

    # Reused CE volumes are NOT silently upgraded. Treat a verified V2 Guard
    # table as proof of Checkout support; never bypass an existing Guard.
    with pymysql.connect(host=host, port=int(os.environ.get('SEAFILE_MYSQL_DB_PORT', '3306')),
                         user=user, password=password, database=names['files'], autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM information_schema.tables "
                           "WHERE table_schema=DATABASE() AND table_name='cf_edit_guard'")
            guard_installed = cursor.fetchone()[0] == 1
        core_ddl = (source / 'seafile-server/scripts/sql/mysql/cloudfile-v2.sql').read_text()
        if guard_installed:
            FreshSchema(
                connection, core_ddl,
                edit_ddl=(source / 'seafile-server/scripts/sql/mysql/cloudfile-v2-edit.sql').read_text(),
            ).verify()
        else:
            # CE14 upgrade: add the reviewed three V2 metadata tables in-place.
            # Existing native Repo/permissions/files are untouched; unsupported
            # legacy CloudFile schema is rejected by FreshSchema.install().
            FreshSchema(connection, core_ddl).install()
else:
    host, password, user = os.environ['DB_HOST'], os.environ['DB_PASSWORD'], 'cfv2'
    names = {'account': 'cfv2_ccnet', 'files': 'cfv2_seafile', 'hub': 'cfv2_seahub'}
    public_url = os.environ['PUBLIC_URL']
    for directory in (data, ccnet, logs, conf):
        directory.mkdir(parents=True, exist_ok=True)
    for directory in (shared / 'library-storage', shared / 'seahub-data'):
        directory.mkdir(parents=True, exist_ok=True)
    for attempt in range(60):
        try:
            connection = pymysql.connect(host=host, user='root', password=os.environ['DB_ROOT_PASSWORD'], autocommit=True,
                client_flag=pymysql.constants.CLIENT.MULTI_STATEMENTS)
            break
        except pymysql.err.OperationalError:
            if attempt == 59:
                raise
            time.sleep(2)
    with connection:
        with connection.cursor() as cursor:
            cursor.execute('CREATE USER IF NOT EXISTS %s@%s IDENTIFIED BY %s', (user, '%', password))
            for kind, filename in (
                    ('account', source / 'seafile-server/scripts/sql/mysql/ccnet.sql'),
                    ('files', source / 'seafile-server/scripts/sql/mysql/seafile.sql'),
                    ('hub', source / 'seahub/sql/mysql.sql')):
                cursor.execute('SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME=%s', (names[kind],))
                missing = cursor.fetchone() is None
                cursor.execute('CREATE DATABASE IF NOT EXISTS ' + names[kind] + ' CHARACTER SET utf8mb4')
                cursor.execute('GRANT ALL ON `' + names[kind].replace('_', '\\_') + '`.* TO %s@%s', (user, '%'))
                if missing:
                    cursor.execute('USE ' + names[kind])
                    cursor.execute(filename.read_text())
                    while cursor.nextset():
                        pass
    with pymysql.connect(host=host, user=user, password=password, database=names['files'], autocommit=True) as connection:
        FreshSchema(
            connection,
            (source / 'seafile-server/scripts/sql/mysql/cloudfile-v2.sql').read_text(),
            edit_ddl=(source / 'seafile-server/scripts/sql/mysql/cloudfile-v2-edit.sql').read_text(),
        ).install()
    (conf / 'seafile.conf').write_text(f'''[database]
type=mysql
host={host}
port=3306
user={user}
password={password}
db_name={names['files']}
ccnet_db_name={names['account']}
connection_charset=utf8mb4
[fileserver]
use_go_fileserver=true
port=8082
[cloudfile_v2]
auto_local_root=/shared/library-storage
''')
    settings = {'SECRET_KEY': os.environ['DJANGO_SECRET_KEY']}
    # Fresh deployments may seed native OAuth/OIDC settings before first boot.
    # Retain them on restart rather than silently disabling the login provider.
    settings.update(read_settings(conf / 'seahub_settings.py', {'LOGIN_URL', 'LOGIN_REDIRECT_URL'}))

# Discovery always runs at startup, using the same CE database and registered storage path.
# Existing V2 schema is checked first. Never create replacement Repo IDs.
with pymysql.connect(host=host, port=int(os.environ.get('SEAFILE_MYSQL_DB_PORT', '3306')),
                     user=user, password=password, database=names['files'],
                     charset='utf8mb4', autocommit=True) as connection:
    NativeLibraryDiscovery.check_native_schema(connection)
    discovery = NativeLibraryDiscovery(connection)
    native_repo_ids = [item['repo_id'] for item in discovery.scan()]
    print('CloudFile V2 native library discovery:', discovery.reconcile(), flush=True)
    unresolved = discovery.unresolved_registry_count()
    if unresolved:
        print('CloudFile V2 needs operator review: registered libraries missing from '
              'Repo, RepoTrash and GarbageRepos:', unresolved, flush=True)

# Hub detects Checkout from the same installed Guard schema as native services.
if os.environ.get('JWT_PRIVATE_KEY'):
    settings['JWT_PRIVATE_KEY'] = os.environ['JWT_PRIVATE_KEY']

# Directory is a trusted external connection, not a feature flag. Preserve
# seeded connection/security settings and allow deployment secret injection.
for key in ('CF_DIRECTORY_URL', 'CF_DIRECTORY_SECRET', 'CF_DIRECTORY_KEY_ID',
            'CF_DIRECTORY_ISSUER', 'CF_DIRECTORY_AUDIENCE', 'CF_DIRECTORY_GROUP_OWNER'):
    if key in os.environ:
        settings[key] = os.environ[key]
if 'CF_DIRECTORY_SUBJECT_TTL' in os.environ:
    settings['CF_DIRECTORY_SUBJECT_TTL'] = int(os.environ['CF_DIRECTORY_SUBJECT_TTL'])
settings['CF_ACL_PROVIDER'] = 'etech'
settings['CF_ACL_SUBJECT_ENSURE'] = 'cloudfile_ext.v2.etech_directory.ensure_subject'


settings['ENABLE_OAUTH'] = bool(settings.get('OAUTH_CLIENT_ID') and settings.get('OAUTH_CLIENT_SECRET'))

for key in ('CF_MEILISEARCH_URL', 'CF_MEILISEARCH_API_KEY', 'CF_MEILISEARCH_INDEX'):
    if key in os.environ:
        settings[key] = os.environ[key]

settings.update(web_settings(public_url, settings, existing=existing))
nginx_template = Path('/opt/cloudfile-v2/nginx.conf.template').read_text()
Path('/etc/nginx/nginx.conf').write_text(nginx_config(nginx_template, settings['SITE_ROOT']))

settings.update({
    'DATABASES': {'default': {'ENGINE': 'django.db.backends.mysql', 'NAME': names['hub'],
                            'USER': user, 'PASSWORD': password, 'HOST': host,
                            'PORT': os.environ.get('SEAFILE_MYSQL_DB_PORT', '3306'),
                            'OPTIONS': {'charset': 'utf8mb4'}}},
    # Webpack fingerprints its bundles; use native static collection without map rehashing.
    'STORAGES': {'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
                 'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}},
    'ALLOWED_HOSTS': [urlsplit(public_url).hostname, '127.0.0.1', 'localhost', 'cloudfile-dev'],
    'CSRF_TRUSTED_ORIGINS': [public_url],
    'DEBUG': False,
})
(conf / 'seahub_settings.py').write_text('\n'.join(key + ' = ' + repr(value) for key, value in settings.items()) + '\n')
for key, value in {
    'SEAFILE_MYSQL_DB_HOST': host, 'SEAFILE_MYSQL_DB_PORT': os.environ.get('SEAFILE_MYSQL_DB_PORT', '3306'),
    'SEAFILE_MYSQL_DB_USER': user, 'SEAFILE_MYSQL_DB_PASSWORD': password,
    'SEAFILE_MYSQL_DB_CCNET_DB_NAME': names['account'], 'SEAFILE_MYSQL_DB_SEAFILE_DB_NAME': names['files'],
    'SEAFILE_MYSQL_DB_SEAHUB_DB_NAME': names['hub'], 'SEAFILE_CENTRAL_CONF_DIR': str(conf),
    'SEAFILE_CONF_DIR': str(data), 'SEAFILE_DATA_DIR': str(data), 'CCNET_CONF_DIR': str(ccnet),
    'SEAFILE_RPC_PIPE_PATH': str(data),
    # Native C/Go construct the internal Hub URL from this canonical root too.
    'SITE_ROOT': settings['SITE_ROOT'],
    'SEAHUB_LOG_DIR': str(logs), 'CACHE_PROVIDER': 'redis', 'DJANGO_SETTINGS_MODULE': 'seahub.settings',
}.items():
    os.environ[key] = value
processes = []
search_worker = None
def shutdown(*unused):
    if search_worker is not None:
        search_worker.terminate()
    for process in reversed(processes):
        process.terminate()
signal.signal(signal.SIGTERM, shutdown)
signal.signal(signal.SIGINT, shutdown)
try:
    processes.append(subprocess.Popen(['seaf-server', '-F', str(conf), '-c', str(ccnet),
        '-d', str(data), '-l', str(logs / 'seafile.log'), '-f']))
    for attempt in range(60):
        if (data / 'seafile.sock').exists():
            break
        if processes[0].poll() is not None or attempt == 59:
            raise RuntimeError('Native RPC did not start')
        time.sleep(1)
    # Use the running native reader before exposing HTTP. Native CE handles
    # commit formats, virtual repos and storage routes; CloudFile does not.
    subprocess.run(['python3', '-c',
                    'import json,sys; from seaserv import seafile_api; '
                    'from native_config import verify_native_reads; '
                    'verify_native_reads(json.load(sys.stdin), seafile_api)'],
                   input=json.dumps(native_repo_ids), text=True, check=True,
                   cwd='/opt/cloudfile-v2')
    processes.append(subprocess.Popen(['fileserver', '-F', str(conf), '-d', str(data),
        '-l', str(logs / 'fileserver.log')]))
    # The native release SQL already contains its complete schema and initial data.
    subprocess.run(['python3', 'manage.py', 'collectstatic', '--noinput', '-i', 'admin', '-i', 'termsandconditions'], check=True)
    if not existing:
        subprocess.run(['python3', '-c', '''import django,os; django.setup()
from seahub.base.accounts import User
from seahub.profile.models import Profile
try:
    User.objects.get(email=Profile.objects.convert_login_str_to_username(os.environ['ADMIN_EMAIL']))
except User.DoesNotExist:
    User.objects.create_superuser(os.environ['ADMIN_EMAIL'], os.environ['ADMIN_PASSWORD'])
'''], check=True)
    processes.append(subprocess.Popen(['gunicorn', 'seahub.wsgi:application', '--bind', '127.0.0.1:8000',
        '--workers', '2', '--timeout', '120', '--access-logfile', '-']))
    processes.append(subprocess.Popen(['nginx', '-g', 'daemon off;']))
    if settings.get('CF_MEILISEARCH_URL'):
        search_worker = subprocess.Popen(['python3', '-m', 'cloudfile_ext.v2.search.worker',
                                         '--checkpoint', str(shared / 'search-v2-checkpoint.json')])
    while all(process.poll() is None for process in processes):
        if search_worker is not None and search_worker.poll() is not None:
            # Search failures must not terminate native file services.
            print('Search worker exited; file services continue', flush=True)
            search_worker = None
        time.sleep(1)
finally:
    shutdown()
    for process in processes:
        process.wait(timeout=15)
