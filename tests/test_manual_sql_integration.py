#!/usr/bin/env python3
"""Disposable database integration test. Publishes no ports, reads no DEV secrets.

Requires an existing mariadb:11.4 image on the selected test host. All fixtures
are synthetic; the uniquely named container and tmpfs are removed in finally.
"""
from pathlib import Path
import json,subprocess,base64
import argparse
root=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description='Verify manual SQL on a disposable no-network MariaDB container; never target an existing DB')
parser.add_argument('--hub',type=Path,default=root.parent/'cloudfile-hub')
parser.add_argument('--ssh-host',help='Optional test host with an existing mariadb:11.4 image')
options=parser.parse_args()
folder=root/'database/v2/20261021-four-table-baseline';hub=options.hub
pack={p.name:p.read_text() for p in folder.glob('*.sql')}
statements=[]
for pat in ('006*.json','008*.json','029*.json'):
 for p in (hub/'cloudfile_extensions/schema/migrations').glob(pat):
  for step in json.loads(p.read_text())['steps']:
   sql=step['sql']
   if any(sql.startswith('CREATE TABLE '+t+' ') for t in ('cf_sso_group_map','cf_dir_acl','cf_edit_guard')):statements.append(sql+';')
core=pack['00-create.sql'];import re
storage=re.search(r'CREATE TABLE cf_library_storage \([\s\S]*?\) ENGINE[^;]+;',core)[0]
fixture='\n'.join([storage,*statements])+'''
ALTER TABLE cf_dir_acl ADD COLUMN share_mode TINYINT NOT NULL DEFAULT 0,
 ADD COLUMN lifecycle_ref VARCHAR(512) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL DEFAULT '';
INSERT INTO cf_library_storage VALUES ('fixture:key','01234567-89ab-cdef-0123-456789abcdef','active');
INSERT INTO cf_sso_group_map(provider,subject_type,namespace,external_id,group_id,name) VALUES ('fixture','org','directory','dept1',7,'Fixture department');
INSERT INTO cf_dir_acl(id,repo_id,path,path_hash,kind,subject_type,provider,namespace,external_id,subject_hash,permission,inherit,revision)
VALUES ('11111111-1111-1111-1111-111111111111','01234567-89ab-cdef-0123-456789abcdef','/fixture',SHA2('/fixture',256),'dir','org','fixture','directory','dept1',SHA2('fixture-subject',256),'rw',1,'22222222-2222-2222-2222-222222222222');
'''
pack['fixture']=fixture
pack['gate_source']=(root/'scripts/scripts_14.0/cloudfile_schema.py').read_text()
script='pack='+repr(pack)+'\n'+r'''
import subprocess,uuid,time,json
name='cf-v2-sql-test-'+uuid.uuid4().hex[:10]
def sql(value,db=None,ok=True):
 cmd=['docker','exec','-i',name,'mariadb','-uroot','--skip-ssl','--batch','--skip-column-names']
 if db:cmd.append(db)
 r=subprocess.run(cmd,input=value,text=True,capture_output=True,timeout=30)
 if ok and r.returncode:
  # Fixture data and SQL definitions only; connection has no secrets and no ports.
  print('SQL_TEST_ERROR',r.stderr[-1500:]);raise RuntimeError('isolated SQL failed')
 if not ok and not r.returncode:raise RuntimeError('unsafe SQL unexpectedly succeeded')
 return r.stdout.strip()
try:
 r=subprocess.run(['docker','run','--detach','--pull=never','--name',name,'--network','none','--tmpfs','/var/lib/mysql:rw,size=768m','-e','MARIADB_ALLOW_EMPTY_ROOT_PASSWORD=1','mariadb:11.4'],capture_output=True,text=True,timeout=30)
 if r.returncode:raise RuntimeError('isolated MariaDB could not start')
 for _ in range(90):
  ready=subprocess.run(['docker','exec',name,'mariadb-admin','-uroot','ping'],capture_output=True,timeout=5)
  if ready.returncode==0 and subprocess.run(['docker','exec',name,'cat','/proc/1/comm'],capture_output=True,text=True,timeout=5).stdout.strip()=='mariadbd':break
  time.sleep(.5)
 else:raise RuntimeError('isolated MariaDB readiness timeout')
 sql('CREATE DATABASE fresh CHARACTER SET utf8mb4; CREATE DATABASE old_layout CHARACTER SET utf8mb4; CREATE DATABASE guarded CHARACTER SET utf8mb4; CREATE DATABASE lifecycle CHARACTER SET utf8mb4; CREATE DATABASE seahub_fixture CHARACTER SET utf8mb4; CREATE DATABASE old_layout_archive; CREATE DATABASE lifecycle_archive; CREATE DATABASE guarded_archive;')
 sql(pack['00-create.sql'],'fresh');sql(pack['50-verify.sql'],'fresh');print('PASS fresh initialization and verification',flush=True)
 sql(pack['fixture'],'old_layout')
 sql("SET @cf_upgrade_archive_database='old_layout_archive'; SET @cf_upgrade_writers_stopped=1;\n"+pack['10-upgrade-029-042.sql'],'old_layout');sql(pack['50-verify.sql'],'old_layout')
 result=sql("SELECT (SELECT COUNT(*) FROM cf_library_storage),(SELECT COUNT(*) FROM cf_sso_group_map),(SELECT COUNT(*) FROM cf_dir_acl),LENGTH(path_hash),permission,inherit,group_id FROM cf_dir_acl JOIN cf_sso_group_map USING(provider,subject_type,namespace,external_id);",'old_layout')
 if result!='1\t1\t1\t32\trw\t1\t7':raise RuntimeError('migration identity or data mismatch')
 print('PASS old layout migration, native group identity and ACL bytes',flush=True)
 sql("SET @cf_upgrade_archive_database='old_layout_archive'; SET @cf_upgrade_writers_stopped=1;\n"+pack['10-upgrade-029-042.sql'],'old_layout',ok=False)
 sql(pack['50-verify.sql'],'old_layout');print('PASS repeat rejected without destroying target or backups',flush=True)
 sql('ALTER TABLE cf_edit_guard DROP INDEX cf_edit_guard_active;','fresh');sql(pack['50-verify.sql'],'fresh',ok=False);print('PASS missing index rejected',flush=True)
 sql(pack['fixture'],'guarded')
 sql("INSERT INTO cf_edit_guard(resource_uid,repo_id,lifecycle_ref,generation,credential_epoch) VALUES ('33333333-3333-3333-3333-333333333333','01234567-89ab-cdef-0123-456789abcdef','fixture-life',7,1);",'guarded')
 sql("SET @cf_upgrade_archive_database='guarded_archive'; SET @cf_upgrade_writers_stopped=1;\n"+pack['10-upgrade-029-042.sql'],'guarded',ok=False)
 if sql('SELECT generation FROM cf_edit_guard;','guarded')!='7':raise RuntimeError('guard identity lost')
 print('PASS nonempty Guard rejected and generation preserved',flush=True)
 sql(pack['fixture'],'lifecycle');sql("UPDATE cf_dir_acl SET lifecycle_ref='fixture-life';",'lifecycle')
 sql("SET @cf_upgrade_archive_database='lifecycle_archive'; SET @cf_upgrade_writers_stopped=1;\n"+pack['10-upgrade-029-042.sql'],'lifecycle',ok=False)
 sql("SET @cf_upgrade_archive_database='lifecycle_archive'; SET @cf_upgrade_writers_stopped=1; SET @cf_upgrade_accept_path_acl=1;\n"+pack['10-upgrade-029-042.sql'],'lifecycle');sql(pack['50-verify.sql'],'lifecycle');print('PASS lifecycle conversion requires explicit acknowledgement',flush=True)
 sql('CREATE TABLE repo_metadata(id INT); CREATE TABLE repo_tags_repotags(id INT); CREATE TABLE base_userstarredfiles(id INT);','seahub_fixture')
 sql('SET @cf_upgrade_writers_stopped=1;\n'+pack['20-seahub-compat.sql'],'seahub_fixture');sql('SET @cf_upgrade_writers_stopped=1;\n'+pack['20-seahub-compat.sql'],'seahub_fixture');print('PASS explicit Seahub compatibility SQL and replay',flush=True)
 # Exercise the real startup checker over actual DB output; no driver dependency.
 import types
 gate=types.ModuleType('gate');exec(pack['gate_source'],gate.__dict__)
 class Cursor:
  def __enter__(self):return self
  def __exit__(self,*args):pass
  def execute(self,query,args=()):
   if not query.startswith('SELECT '):raise RuntimeError('startup wrote SQL')
   if args:query=query.replace('%s',"'"+args[0]+"'")
   self.rows=[]
   for line in sql(query,'old_layout').splitlines():
    values=[]
    for part in line.split('\t'):
     values.append(None if part=='NULL' else int(part) if part.isdigit() else part)
    self.rows.append(tuple(values))
  def fetchall(self):return tuple(self.rows)
 class Connection:
  def cursor(self):return Cursor()
 gate.verify_v2_schema(Connection());print('PASS read-only startup gate against migrated MariaDB',flush=True)
finally:
 subprocess.run(['docker','rm','--force',name],capture_output=True,timeout=30)
 print('isolated temporary database removed',flush=True)
'''
r=subprocess.run((['ssh','-o','BatchMode=yes',options.ssh_host,'python3'] if options.ssh_host else ['python3']),input=script,text=True,capture_output=True,timeout=150)
print(r.stdout);print('integration_exit',r.returncode)
if r.returncode:print(r.stderr[-1500:])
raise SystemExit(r.returncode)
