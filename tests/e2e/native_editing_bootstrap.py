import sys, os
from pathlib import Path
import pymysql
sys.path.insert(0, '/hub')
from cloudfile_extensions.schema.runner import SchemaRunner
c=pymysql.connect(host=os.environ['CF_NATIVE_DB_HOST'],user='root',password='',autocommit=True)
with c.cursor() as q:
    for name in ('cf_lab_ccnet','cf_lab_seafile','cf_lab_hub'):
        q.execute(f'CREATE DATABASE `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_bin')
    q.execute("CREATE USER 'cf_lab'@'%' IDENTIFIED BY 'isolated-fixture-only'")
    for name in ('cf_lab_ccnet','cf_lab_seafile','cf_lab_hub'):
        q.execute(f"GRANT ALL ON `{name}`.* TO 'cf_lab'@'%'")
    for schema, source in [('cf_lab_ccnet','ccnet'),('cf_lab_seafile','seafile')]:
        q.execute(f'USE `{schema}`')
        for statement in Path(f'/server/scripts/sql/mysql/{source}.sql').read_text().split(';'):
            if statement.strip(): q.execute(statement)
    q.execute('USE cf_lab_hub')
    q.execute('CREATE TABLE profile_profile(user VARCHAR(255) UNIQUE,login_id VARCHAR(225) UNIQUE) ENGINE=InnoDB')
    q.execute("INSERT INTO profile_profile VALUES('editor@example.test','employee'),('other@example.test','other-employee')")
    q.execute('CREATE TABLE django_session(session_key VARCHAR(40) PRIMARY KEY,expire_date DATETIME(6)) ENGINE=InnoDB')
    q.execute("INSERT INTO django_session VALUES(%s,TIMESTAMPADD(HOUR,1,UTC_TIMESTAMP(6)))",('s'*32,))
    q.execute('USE cf_lab_seafile')
SchemaRunner(c).apply()
print('isolated native schemas ready')

lab=Path('/lab')
for name in ('conf','ccnet','seafile-data'):
    (lab/name).mkdir(exist_ok=True)
(lab/'conf/seafile.conf').write_text(f"""[database]
type = mysql
host = {os.environ['CF_NATIVE_DB_HOST']}
port = 3306
user = cf_lab
password = isolated-fixture-only
db_name = cf_lab_seafile
connection_charset = utf8mb4
[cloudfile]
identity_database = cf_lab_hub
subject_redis_host = {os.environ['CF_NATIVE_REDIS_HOST']}
subject_redis_port = 6379
subject_redis_prefix = cf-lab:
file_lock_enabled = true
lock_backend = cloudfile
trusted_tls_proxies = 127.0.0.1/32
[fileserver]
port = 8082
use_go_fileserver = true
""")
(lab/'conf/ccnet.conf').write_text(f"""[Database]
ENGINE = mysql
HOST = {os.environ['CF_NATIVE_DB_HOST']}
PORT = 3306
USER = cf_lab
PASSWD = isolated-fixture-only
DB = cf_lab_ccnet
""")
