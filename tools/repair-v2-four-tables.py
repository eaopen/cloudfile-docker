#!/usr/bin/env python3
"""Explicit DEV-only four-table conversion; never a startup migration.

Keep original tables and a private persistent backup. Ordinary upload/download
must not acquire Checkout sessions. This command does not update the legacy
ledger, delete unrelated tables, set environment variables, or auto-roll back.
Run inside the already identified cloudfile-dev container using its controlled
DB credentials; never copy credentials to command arguments or backup files.
"""
import argparse
import base64
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import sys
import uuid

DDL = "-- CloudFile V2 fresh schema. Native CE tables remain the authoritative facts.\n-- This file is independent of cloudfile.sql and the legacy migration chain.\n\nCREATE TABLE cf_library_storage (\n    repo_key VARCHAR(80) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,\n    repo_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,\n    state VARCHAR(8) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,\n    PRIMARY KEY (repo_key),\n    UNIQUE KEY library_storage_repo (repo_id),\n    CONSTRAINT library_storage_state CHECK (state IN ('reserved','active','retired'))\n) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;\n\nCREATE TABLE cf_sso_group_map (\n    provider VARCHAR(32) COLLATE utf8mb4_bin NOT NULL,\n    subject_type VARCHAR(4) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,\n    namespace VARCHAR(128) COLLATE utf8mb4_bin NOT NULL,\n    external_id VARCHAR(225) COLLATE utf8mb4_bin NOT NULL,\n    group_id BIGINT NOT NULL,\n    PRIMARY KEY (provider,subject_type,namespace,external_id),\n    UNIQUE KEY sso_native_group (group_id),\n    CONSTRAINT sso_group_type CHECK (subject_type IN ('org','role')),\n    CONSTRAINT sso_group_id CHECK (group_id > 0)\n) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;\n\nCREATE TABLE cf_dir_acl (\n    repo_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,\n    path_hash BINARY(32) NOT NULL,\n    path VARCHAR(4096) COLLATE utf8mb4_bin NOT NULL,\n    subject_type VARCHAR(4) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,\n    provider VARCHAR(32) COLLATE utf8mb4_bin NOT NULL,\n    namespace VARCHAR(128) COLLATE utf8mb4_bin NOT NULL,\n    external_id VARCHAR(225) COLLATE utf8mb4_bin NOT NULL,\n    permission VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,\n    inherit TINYINT NOT NULL,\n    share_mode TINYINT NOT NULL,\n    revision CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,\n    PRIMARY KEY (repo_id,path_hash,subject_type,provider,namespace,external_id),\n    KEY acl_shared_subject (provider,subject_type,namespace,external_id,share_mode,repo_id),\n    CONSTRAINT acl_subject_type CHECK (subject_type IN ('user','org','role')),\n    CONSTRAINT acl_permission CHECK (permission IN ('r','rw','invisible')),\n    CONSTRAINT acl_inherit CHECK (inherit IN (0,1)),\n    CONSTRAINT acl_share CHECK (share_mode IN (0,1) AND\n        (share_mode=0 OR (permission IN ('r','rw') AND path <> '/')))\n) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;\n\n-- CloudFile V2 optional Rust local editing. Fresh isolated CF-EDIT installations ONLY.\n-- The three-table V2 MVP remains unchanged unless editing is explicitly enabled.\n-- There is NO server-side Intent or editing Session table. Seafile keeps native\n-- File/Block/Commit/Branch versions; Agent Rust keeps its local pending Journal.\n-- One row per physical file path preserves generation across Checkout cycles.\nCREATE TABLE cf_edit_guard (\n    repo_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,\n    path_hash BINARY(32) NOT NULL,\n    path VARCHAR(4096) COLLATE utf8mb4_bin NOT NULL,\n    guard_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NULL,\n    generation BIGINT UNSIGNED NOT NULL DEFAULT 0,\n    owner_uid VARCHAR(225) COLLATE utf8mb4_bin NULL,\n    owner_native_user VARCHAR(255) COLLATE utf8mb4_bin NULL,\n    terminal_type VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NULL,\n    terminal_name VARCHAR(128) COLLATE utf8mb4_bin NULL,\n    checkout_ip VARCHAR(45) CHARACTER SET ascii COLLATE ascii_bin NULL,\n    proof_digest CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NULL,\n    base_file_id CHAR(40) CHARACTER SET ascii COLLATE ascii_bin NULL,\n    lease_expires_at DATETIME(6) NULL,\n    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),\n    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),\n    PRIMARY KEY (repo_id, path_hash),\n    UNIQUE KEY cf_edit_guard_id (guard_id),\n    KEY cf_edit_guard_active (repo_id, guard_id),\n    KEY cf_edit_guard_owner (owner_uid, guard_id),\n    CONSTRAINT cf_edit_terminal_type CHECK (\n        terminal_type IS NULL OR terminal_type IN ('windows','macos','linux','other')\n    ),\n    CONSTRAINT cf_edit_active_shape CHECK (\n        (guard_id IS NULL AND owner_uid IS NULL AND owner_native_user IS NULL\n         AND proof_digest IS NULL AND base_file_id IS NULL AND lease_expires_at IS NULL)\n        OR\n        (guard_id IS NOT NULL AND owner_uid IS NOT NULL AND owner_native_user IS NOT NULL\n         AND proof_digest IS NOT NULL AND base_file_id IS NOT NULL AND lease_expires_at IS NOT NULL)\n    )\n) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;\n"
TABLES = ('cf_library_storage', 'cf_sso_group_map', 'cf_dir_acl', 'cf_edit_guard')
TARGET_COLUMNS = {
 'cf_library_storage': ('repo_key','repo_id','state'),
 'cf_sso_group_map': ('provider','subject_type','namespace','external_id','group_id'),
 'cf_dir_acl': ('repo_id','path_hash','path','subject_type','provider','namespace','external_id','permission','inherit','share_mode','revision'),
 'cf_edit_guard': ('repo_id','path_hash','path','guard_id','generation','owner_uid','owner_native_user','terminal_type','terminal_name','checkout_ip','proof_digest','base_file_id','lease_expires_at','created_at','updated_at'),
}

def encoded(value):
 if isinstance(value, bytes): return {'base64':base64.b64encode(value).decode()}
 if isinstance(value,(datetime.date,datetime.datetime)): return {'iso':value.isoformat()}
 if isinstance(value,dict): return {k:encoded(v) for k,v in value.items()}
 if isinstance(value,(list,tuple)): return [encoded(x) for x in value]
 return value

def canonical(value):
 return json.dumps(encoded(value),ensure_ascii=False,sort_keys=True,separators=(',',':'))

def digest(rows):
 return hashlib.sha256('\n'.join(sorted(canonical(row) for row in rows)).encode()).hexdigest()

def identifier(name):
 if not re.fullmatch(r'[a-zA-Z0-9_]{1,64}',name):raise RuntimeError('invalid SQL identifier')
 return '`'+name+'`'

def definitions():
 text=re.sub(r'--[^\n]*','',DDL)
 result={}
 for statement in text.split(';'):
  if not statement.strip():continue
  m=re.match(r'\s*CREATE TABLE (cf_[a-z_]+)\s*\(',statement)
  if not m or m[1] not in TABLES or m[1] in result:raise RuntimeError('unexpected target DDL')
  result[m[1]]=statement.strip()
 if set(result)!=set(TABLES):raise RuntimeError('incomplete target DDL')
 return result

def project(table,rows):
 result=[]
 for row in rows:
  value={name:row[name] for name in TARGET_COLUMNS[table] if name in row}
  if table=='cf_dir_acl':
   if row.get('kind','dir')!='dir':raise RuntimeError('file ACL has no lossless target mapping')
   value['path_hash']=hashlib.sha256(row['path'].encode()).digest()
   previous=row['path_hash']
   if isinstance(previous,str):previous=bytes.fromhex(previous)
   if previous!=value['path_hash']:raise RuntimeError('source ACL hash is inconsistent')
   if str(uuid.UUID(row['revision']))!=row['revision']:raise RuntimeError('invalid ACL revision')
  if table=='cf_edit_guard':
   # Empty installed Guard was verified. Do not invent a conversion for old
   # generation, intent or credential state when a row appears concurrently.
   raise RuntimeError('Guard is no longer empty; explicit lease conversion required')
  if set(value)!=set(TARGET_COLUMNS[table]):raise RuntimeError('source columns cannot be mapped')
  result.append(value)
 return result

def freeze_writers():
 stopped=[]
 # Freeze DB-using services only, after requests have had time to drain.
 # The migration process itself is excluded. Resume in finally, never rollback.
 try:
  for proc in Path('/proc').iterdir():
   if not proc.name.isdigit() or int(proc.name)==os.getpid():continue
   try:name=(proc/'comm').read_text().strip()
   except (OSError,ProcessLookupError):continue
   if name in ('seaf-server','fileserver','seafevents','gunicorn','python','python3','seafile-control') or name.startswith('gunicorn'):
    pid=int(proc.name)
    try:os.kill(pid,signal.SIGSTOP);stopped.append(pid)
    except ProcessLookupError:pass
  return stopped
 except BaseException:
  resume_writers(stopped);raise

def resume_writers(stopped):
 for pid in stopped:
  try:os.kill(pid,signal.SIGCONT)
  except ProcessLookupError:pass

def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--apply',action='store_true')
 parser.add_argument('--expected-database',required=True)
 parser.add_argument('--backup-root',default='/shared/schema-backups')
 args=parser.parse_args()
 import pymysql
 conn=pymysql.connect(host=os.environ['SEAFILE_MYSQL_DB_HOST'],port=int(os.environ.get('SEAFILE_MYSQL_DB_PORT','3306')),user=os.environ['SEAFILE_MYSQL_DB_USER'],password=os.environ['SEAFILE_MYSQL_DB_PASSWORD'],database=os.environ['SEAFILE_MYSQL_DB_SEAFILE_DB_NAME'],charset='utf8mb4',autocommit=True,connect_timeout=5,read_timeout=30,write_timeout=30,cursorclass=pymysql.cursors.DictCursor)
 stopped=[];switched=False;receipt={}
 try:
  with conn.cursor() as q:
   q.execute('SELECT DATABASE() AS db')
   if q.fetchone()['db']!=args.expected_database:raise RuntimeError('database identity mismatch')
   q.execute("SELECT GET_LOCK('cloudfile.dev.v2.four-table-repair',0) AS acquired")
   if q.fetchone()['acquired']!=1:raise RuntimeError('another repair is running')
   q.execute('SET SESSION lock_wait_timeout=10')
   q.execute("SET SESSION sql_mode=CONCAT(@@sql_mode,',STRICT_ALL_TABLES')")
   source={};create={}
   for table in TABLES:
    q.execute('SHOW CREATE TABLE '+identifier(table));create[table]=q.fetchone()['Create Table']
    q.execute('SELECT * FROM '+identifier(table));source[table]=q.fetchall()
   q.execute("SELECT COUNT(*) AS n FROM information_schema.KEY_COLUMN_USAGE WHERE REFERENCED_TABLE_SCHEMA=DATABASE() AND REFERENCED_TABLE_NAME IN (%s,%s,%s,%s)",TABLES)
   if q.fetchone()['n']:raise RuntimeError('foreign key dependency needs an explicit migration')
   target={t:project(t,rows) for t,rows in source.items()}
   receipt={'source_counts':{t:len(rows) for t,rows in source.items()},'source_digests':{t:digest(rows) for t,rows in source.items()},'target_digests':{t:digest(rows) for t,rows in target.items()},'ddl_sha256':hashlib.sha256(DDL.encode()).hexdigest(),'database':args.expected_database,'apply':args.apply,'switched':False}
   print(json.dumps(receipt,sort_keys=True),flush=True)
   if not args.apply:return
   stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid.uuid4().hex[:6]
   backup_root=Path(args.backup_root);backup_root.mkdir(parents=True,exist_ok=True,mode=0o700)
   backup=backup_root/('four-tables-'+stamp+'.json')
   # Export under private permissions before any table-changing statement.
   fd=os.open(str(backup),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
   with os.fdopen(fd,'w') as out:
    out.write(canonical({'receipt':receipt,'create':create,'rows':source}));out.flush();os.fsync(out.fileno())
   stages={t:'cfv2_new_'+stamp+'_'+t[3:] for t in TABLES}
   backups={t:'cfv2_old_'+stamp+'_'+t[3:] for t in TABLES}
   for table,statement in definitions().items():
    q.execute(statement.replace('CREATE TABLE '+table,'CREATE TABLE '+identifier(stages[table]),1))
   stopped=freeze_writers()
   # Re-read after freezing, because discovery and backup happened while live.
   # Any concurrent change aborts before copying or renaming an original table.
   for table in TABLES:
    q.execute('SHOW CREATE TABLE '+identifier(table))
    if q.fetchone()['Create Table']!=create[table]:raise RuntimeError('source DDL changed during preparation')
    q.execute('SELECT * FROM '+identifier(table))
    if digest(q.fetchall())!=receipt['source_digests'][table]:raise RuntimeError('source data changed during preparation')
   for table,rows in target.items():
    cols=TARGET_COLUMNS[table]
    if rows:q.executemany('INSERT INTO '+identifier(stages[table])+' ('+','.join(identifier(c) for c in cols)+') VALUES ('+','.join(['%s']*len(cols))+')',[tuple(row[c] for c in cols) for row in rows])
    q.execute('SELECT '+','.join(identifier(c) for c in cols)+' FROM '+identifier(stages[table]))
    if digest(q.fetchall())!=receipt['target_digests'][table]:raise RuntimeError('staged data verification failed')
   # One atomic RENAME switches all four names together. No DROP, no loss of
   # old data, and no automatic rollback that could erase subsequent writes.
   parts=[]
   for table in TABLES:parts.extend((identifier(table)+' TO '+identifier(backups[table]),identifier(stages[table])+' TO '+identifier(table)))
   q.execute('RENAME TABLE '+','.join(parts));switched=True
   receipt.update(switched=True,backup_file=str(backup),backup_tables=backups)
   for table in TABLES:
    cols=TARGET_COLUMNS[table]
    q.execute('SELECT '+','.join(identifier(c) for c in cols)+' FROM '+identifier(table))
    if digest(q.fetchall())!=receipt['target_digests'][table]:raise RuntimeError('post-switch data verification failed')
   receipt_path=backup_root/('four-tables-'+stamp+'-receipt.json')
   fd=os.open(str(receipt_path),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
   with os.fdopen(fd,'w') as out:json.dump(receipt,out,sort_keys=True);out.flush();os.fsync(out.fileno())
   print(json.dumps(receipt,sort_keys=True),flush=True)
 finally:
  resume_writers(stopped)
  conn.close()

if __name__=='__main__':
 try:main()
 except Exception as error:
  # SQL errors may embed row values or connection secrets. Emit only a class
  # and numeric driver code; private data remains in the controlled backup.
  code=error.args[0] if error.args and isinstance(error.args[0],int) else None
  print(json.dumps({'repair_failed':type(error).__name__,'sql_code':code,'reason':str(error) if type(error) is RuntimeError else 'private driver details withheld'}),flush=True)
  raise SystemExit(1)
