"""Isolated real native directory qualification; identity/session inputs are fixtures."""
import hashlib
import json
import os
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pymysql
import redis
import requests

sys.path[:0] = ['/hub', '/server/python', '/backend/seafile-server/seafile/lib/python3.12/site-packages']
from seafile.rpcclient import SeafServerThreadedRpcClient, SearpcError
from cloudfile_extensions.authorization.shares import DirectoryShares
from cloudfile_extensions.authorization.rules import ACLRules, digest
from cloudfile_extensions.resources.native import NativeResourceReader

rpc = SeafServerThreadedRpcClient('/lab/seafile-data/seafile.sock')
db = pymysql.connect(host=os.environ['CF_NATIVE_DB_HOST'], user='cf_lab', password='isolated-fixture-only', database='cf_lab_seafile', autocommit=True)
@contextmanager
def tx():
    db.begin()
    try:
        with db.cursor() as q:
            yield q
        db.commit()
    except BaseException:
        db.rollback()
        raise

owner, recipient = 'other@example.test', 'editor@example.test'
now = int(time.time())
scope, session, subject = 'b'*64, 's'*32, 'c'*64
with tx() as q:
    for user in (owner, recipient):
        q.execute("INSERT IGNORE INTO cf_lab_ccnet.EmailUser(email,passwd,is_staff,is_active,ctime) VALUES(%s,'unused',0,1,%s)", (user, now))
    q.execute('INSERT INTO cf_oidc_session VALUES(%s,%s,%s,NULL,%s,TIMESTAMPADD(HOUR,1,UTC_TIMESTAMP(6)))', (scope, session, subject, now))
snapshot = dict(userId='employee', context_epoch='d'*32, status='ready', fetched_at=time.time(), expires_at=time.time()+1700, source_etag='fixture-v1', subject=dict(userId='employee', status='active', etag='fixture-v1', organizations=[], roles=[], attributes={}, generated_at=datetime.now(timezone.utc).isoformat().replace('+00:00','Z')))
key = 'cf-lab:' + hashlib.sha256(json.dumps(['fixture','employee'], separators=(',',':')).encode()).hexdigest()
redis.Redis(host=os.environ['CF_NATIVE_REDIS_HOST']).set(key, json.dumps(snapshot), ex=1700)
repo = rpc.create_repo('Directory API native', 'Isolated scoped access', owner, None, 2, None, None)
rpc.post_dir(repo, '/', 'folder', owner)
tmp = Path('/lab/directory-content.txt')
tmp.write_bytes(b'directory initial bytes\n')
rpc.post_file(repo, str(tmp), '/folder', 'file.txt', owner)
rpc.post_file(repo, str(tmp), '/', 'outside.txt', owner)
assert rpc.check_permission(repo, recipient) is None
ref = dict(repo_id=repo, path='/folder', kind='dir')
recipient_subject = dict(type='user', provider='fixture', namespace='user', external_id='employee')
shares = DirectoryShares(lifecycle_reader=NativeResourceReader(rpc))
with tx() as q:
    q.execute('INSERT INTO cf_managed_library(repo_id,created_at) VALUES(%s,UTC_TIMESTAMP(6))', (repo,))
    share, _ = shares.create(q, ref, dict(path='/folder', subject=recipient_subject), actor='fixture-admin')

def condition(path=None):
    value = dict(directory_access=True, head_id=rpc.get_repo(repo).head_cmmt_id, context=dict(provider='fixture',userId='employee',epoch='d'*32), scopes=[dict(type='provider',provider='fixture',external_id='fixture'),dict(type='provider',provider='cf_oidc_'+scope[:24],external_id='cf_oidc_'+scope[:24]),dict(type='user',provider='fixture',external_id='employee'),dict(type='repo',provider='cloudfile',external_id=repo)], oidc_session=dict(scope_hash=scope,session_key=session,subject_hash=subject,sid_hash=None,authenticated_at=now))
    if path is not None:
        value['path'] = path
    return value

def ticket(path='/folder/file.txt'):
    return rpc.seafile_cloudfile_issue_read_ticket(repo, path, rpc.get_repo(repo).head_cmmt_id, rpc.get_file_id_by_path(repo,path), 'download', recipient, json.dumps(condition(path)))

def fetch(token):
    return requests.get('http://127.0.0.1:8082/cloudfile/read', headers={'Authorization':'Bearer '+token,'X-CloudFile-Filename':'file.txt','X-Forwarded-Proto':'https'}, timeout=15)

checks=[]
def passed(name):
    checks.append(name)
    print('PASS '+name, flush=True)

def denied(call):
    try:
        call()
    except SearpcError:
        return
    raise AssertionError('Expected native authorization refusal')

def write(name='file.txt'):
    value=condition()
    if name != 'file.txt':
        value['create']=True
    return rpc.cloudfile_put_file_with_barriers(repo,str(tmp),'/folder',name,recipient,json.dumps(value))

def acl(permission):
    with tx() as q:
        if permission is None:
            q.execute('DELETE FROM cf_dir_acl WHERE repo_id=%s', (repo,))
        else:
            # Preserve the single ACL's sharing/lifecycle fields when editing permissions.
            q.execute('UPDATE cf_dir_acl SET permission=%s,revision=%s WHERE repo_id=%s',
                (permission, str(uuid4()), repo))

original=ticket()
r=fetch(original)
assert r.status_code==200 and r.content==tmp.read_bytes(), (r.status_code,r.text)
passed('share alone reads real bytes without library membership')
normal = condition('/folder/file.txt')
normal.pop('directory_access')
denied(lambda: rpc.seafile_cloudfile_issue_read_ticket(repo, '/folder/file.txt',
    rpc.get_repo(repo).head_cmmt_id, rpc.get_file_id_by_path(repo, '/folder/file.txt'),
    'download', recipient, json.dumps(normal)))
passed('normal library ticket entry still requires library membership')
with tx() as q:
    q.execute('INSERT INTO SharedRepo(repo_id,from_email,to_email,permission) VALUES(%s,%s,%s,%s)',
        (repo, owner, recipient, 'r'))
normal_token = rpc.seafile_cloudfile_issue_read_ticket(repo, '/folder/file.txt',
    rpc.get_repo(repo).head_cmmt_id, rpc.get_file_id_by_path(repo, '/folder/file.txt'),
    'download', recipient, json.dumps(normal))
assert fetch(normal_token).content == tmp.read_bytes()
with tx() as q:
    q.execute('DELETE FROM SharedRepo WHERE repo_id=%s AND to_email=%s', (repo, recipient))
assert fetch(normal_token).status_code != 200
passed('normal library member reads normally and loses access after library revocation')
denied(lambda: ticket('/outside.txt'))
passed('sibling file denied')
head=rpc.get_repo(repo).head_cmmt_id
denied(write)
assert rpc.get_repo(repo).head_cmmt_id==head
passed('share alone cannot publish')
acl('rw')
tmp.write_bytes(b'directory ACL updated bytes\n')
write()
assert fetch(ticket()).content==tmp.read_bytes()
passed('directory rw ACL publishes real bytes without library membership')
normal_write = condition()
normal_write.pop('directory_access')
normal_head = rpc.get_repo(repo).head_cmmt_id
denied(lambda: rpc.cloudfile_put_file_with_barriers(repo, str(tmp), '/folder', 'file.txt',
    recipient, json.dumps(normal_write)))
assert rpc.get_repo(repo).head_cmmt_id == normal_head
passed('normal library publication entry still requires library membership')
write('created.txt')
assert fetch(ticket('/folder/created.txt')).content == tmp.read_bytes()
passed('directory rw ACL creates a new file with parent authorization')
partial = requests.get('http://127.0.0.1:8082/cloudfile/read', headers={
    'Authorization':'Bearer '+ticket(), 'X-CloudFile-Filename':'file.txt',
    'X-Forwarded-Proto':'https', 'Range':'bytes=0-8'}, timeout=15)
assert partial.status_code == 206 and partial.content == tmp.read_bytes()[:9]
passed('authorized native Range returns only requested bytes')
before_deny = ticket()
acl('none')
denied(ticket)
assert fetch(before_deny).status_code!=200
passed('explicit deny overrides share and previously issued ticket')
acl(None)
denied(ticket)
passed('ACL deletion also removes sharing qualification')
with tx() as q:
    share, _ = shares.create(q, ref, dict(path='/folder', subject=recipient_subject), actor='fixture-admin')
assert fetch(ticket()).content == tmp.read_bytes()
current=ticket()
with tx() as q:
    shares.delete(q, ref, share['id'], if_match=share['etag'])
denied(ticket)
assert fetch(current).status_code!=200
revoked_range = requests.get('http://127.0.0.1:8082/cloudfile/read', headers={
    'Authorization':'Bearer '+current, 'X-CloudFile-Filename':'file.txt',
    'X-Forwarded-Proto':'https', 'Range':'bytes=0-8'}, timeout=15)
assert revoked_range.status_code not in (200, 206)
passed('share revocation invalidates old and new native access')
with tx() as q:
    stale, _ = shares.create(q, ref, dict(path='/folder', subject=recipient_subject), actor='fixture-admin')
    q.execute('UPDATE cf_dir_acl SET lifecycle_ref=%s WHERE id=%s', ('ce14:path-birth:'+'0'*40, stale['id']))
denied(ticket)
passed('stale directory lifecycle cannot authorize native access')
with tx() as q:
    shares.delete(q, ref, stale['id'], if_match=stale['etag'])
acl('rw')
denied(ticket)
passed('positive ACL cannot bypass disabled sharing')
with tx() as q:
    shares.create(q, ref, dict(path='/folder', subject=recipient_subject), actor='fixture-admin')
assert fetch(ticket()).content==tmp.read_bytes()
passed('reenabling unified sharing restores current ACL access')
with tx() as q:
    q.execute('UPDATE cf_lab_ccnet.EmailUser SET is_active=0 WHERE email=%s', (recipient,))
denied(ticket)
passed('inactive native account cannot use shared ACL')
with tx() as q:
    q.execute('UPDATE cf_lab_ccnet.EmailUser SET is_active=1 WHERE email=%s', (recipient,))
with tx() as q:
    q.execute('UPDATE RepoInfo SET status=1 WHERE repo_id=%s',(repo,))
head=rpc.get_repo(repo).head_cmmt_id
denied(write)
assert rpc.get_repo(repo).head_cmmt_id==head
passed('hard readonly overrides rw ACL at native publication')
Path('/lab/directory-result.json').write_text(json.dumps(dict(repo=repo,checks=checks,scope='Real native RPC, SQL policy and fileserver bytes; identity/session are trusted fixtures, no browser or live OIDC acceptance'),indent=2))
