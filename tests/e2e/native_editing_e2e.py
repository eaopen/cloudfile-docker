"""Real native storage/publication test; trusted identity inputs are fixtures."""
import sys,json,time,hashlib,os
from pathlib import Path
from uuid import uuid4
from contextlib import contextmanager
from datetime import datetime,timezone
import pymysql,redis,requests
sys.path[:0]=['/hub','/backend/seafile-server/seafile/lib/python3.12/site-packages']
from seafile.rpcclient import SeafServerThreadedRpcClient,SearpcError
from cloudfile_extensions.editing.store import EditingStore
from cloudfile_extensions.common.errors import ContractError

db=pymysql.connect(host=os.environ['CF_NATIVE_DB_HOST'],user='cf_lab',password='isolated-fixture-only',database='cf_lab_seafile',autocommit=True)
rpc=SeafServerThreadedRpcClient('/lab/seafile-data/seafile.sock')
store=EditingStore()
@contextmanager
def tx():
    db.begin()
    try:
        with db.cursor() as q: yield q
        db.commit()
    except BaseException:
        db.rollback();raise

owner='editor@example.test'
repo=rpc.create_repo('Editing golden native','Isolated single-file test',owner,None,2,None,None)
path='/editing-golden.txt'
file=Path('/lab/S1.txt');file.write_bytes(b'initial native content\n')
rpc.post_file(repo,str(file),'/',path[1:],owner)
F1=rpc.get_file_id_by_path(repo,path)
H1=rpc.get_repo(repo).head_cmmt_id
uid=str(uuid4())
target=dict(uid=uid,repo=repo,lifecycle='native-fixture')
identity=dict(actor='employee',holder='native-lab',token='a'*64)
with tx() as q:
    # Match the production Checkout gate; marker is acquired before Branch.
    q.execute("INSERT INTO cf_managed_library(repo_id,created_at) VALUES(%s,UTC_TIMESTAMP(6))",(repo,))
    q.execute("INSERT INTO cf_resource(uid,repo_id,kind,path,path_hash,lifecycle_ref,revision,state,updated_at) VALUES(%s,%s,'file',%s,%s,%s,1,'active',UTC_TIMESTAMP(6))",(uid,repo,path,hashlib.sha256(path.encode()).hexdigest(),target['lifecycle']))
    guard=store.acquire(q,**target,**identity,mode='checkout',source='web',native_user=owner,base_file_id=F1)
proof=dict(identity,guard_id=guard['guard_id'],generation=int(guard['generation']),credential_epoch=int(guard['credential_epoch']))

now=int(time.time());scope='b'*64;session='s'*32;subject='c'*64
with tx() as q:
    q.execute("INSERT IGNORE INTO cf_lab_ccnet.EmailUser(email,passwd,is_staff,is_active,ctime) VALUES(%s,'unused',0,1,%s),(%s,'unused',0,1,%s)",(owner,now,'other@example.test',now))
    q.execute("INSERT INTO cf_oidc_session VALUES(%s,%s,%s,NULL,%s,TIMESTAMPADD(HOUR,1,UTC_TIMESTAMP(6))) ON DUPLICATE KEY UPDATE authenticated_at=VALUES(authenticated_at),expires_at=VALUES(expires_at)",(scope,session,subject,now))
pair=json.dumps(['fixture','employee'],separators=(',',':'))
key='cf-lab:'+hashlib.sha256(pair.encode()).hexdigest()
snapshot=dict(userId='employee',context_epoch='d'*32,status='ready',fetched_at=time.time(),expires_at=time.time()+1700,source_etag='fixture-v1',subject=dict(userId='employee',status='active',etag='fixture-v1',organizations=[],roles=[],attributes={},generated_at=datetime.now(timezone.utc).isoformat().replace('+00:00','Z')))
redis.Redis(host=os.environ['CF_NATIVE_REDIS_HOST']).set(key,json.dumps(snapshot),ex=1700)

def condition(head,base,intent):
    return dict(head_id=head,path=path,context=dict(provider='fixture',userId='employee',epoch='d'*32),scopes=[dict(type='provider',provider='fixture',external_id='fixture'),dict(type='provider',provider='cf_oidc_'+scope[:24],external_id='cf_oidc_'+scope[:24]),dict(type='user',provider='fixture',external_id='employee'),dict(type='repo',provider='cloudfile',external_id=repo)],oidc_session=dict(scope_hash=scope,session_key=session,subject_hash=subject,sid_hash=None,authenticated_at=now),editing=dict(repo_id=repo,resource_uid=uid,guard_id=proof['guard_id'],generation=str(proof['generation']),credential_epoch=str(proof['credential_epoch']),holder=identity['holder'],token=identity['token'],intent_id=intent,base_file_id=base))

def receipt(intent):
    with tx() as q: return store.intent(q,uid=uid,intent_id=intent)
def current_guard():
    with tx() as q: return store.load(q,**target)

def sql_branch():
    with tx() as q:
        q.execute("SELECT commit_id FROM Branch WHERE repo_id=%s AND name='master'",(repo,))
        return q.fetchone()[0]

def lose_ack(method_name, callback):
    """Drop a real successful native reply before the application can decode it."""
    original=rpc.call_remote_func_sync
    def dropped(payload):
        raw=original(payload)
        if json.loads(payload)[0]==method_name:
            assert 'err_code' not in json.loads(raw),raw
            raise ConnectionError('injected native acknowledgement loss')
        return raw
    rpc.call_remote_func_sync=dropped
    try:
        try: callback()
        except ConnectionError: pass
        else: raise AssertionError('fault injection did not intercept native reply')
    finally: rpc.call_remote_func_sync=original
def download(expected):
    h=rpc.get_repo(repo).head_cmmt_id;f=rpc.get_file_id_by_path(repo,path)
    read=condition(h,f,str(uuid4()));read.pop('editing')
    ticket=rpc.seafile_cloudfile_issue_read_ticket(repo,path,h,f,'download',owner,json.dumps(read))
    response=requests.get('http://127.0.0.1:8082/cloudfile/read',headers={
        'Authorization':'Bearer '+ticket,'X-CloudFile-Filename':path[1:],
        'X-Forwarded-Proto':'https'},timeout=10)
    response.raise_for_status();assert response.content==expected,(response.status_code,response.content)
    return hashlib.sha256(response.content).hexdigest()

download(b'initial native content\n')
print('PASS native qualified read of initial F1',flush=True)

for user in (owner,'other@example.test'):
    try: rpc.put_file(repo,str(file),'/',path[1:],user,H1)
    except SearpcError as e: assert e.code==600,(user,e.code,str(e))
    else: raise AssertionError('checkout ordinary write allowed')
print('PASS ordinary native writes denied for owner and other',flush=True)

reports=[]
base,head=F1,H1
for n,content in [(2,b'second native content\n'),(3,b'third native content\n')]:
    tmp=Path(f'/lab/S{n}.txt');tmp.write_bytes(content);intent=str(uuid4())
    with tx() as q:
        store.prepare(q,**target,**proof,intent_id=intent,expected_file_id=base,
            staged_file_id=None,content_digest=hashlib.sha256(content).hexdigest(),action='commit',
            snapshot=dict(id=intent,size=len(content),source=tmp.name))
    publish=lambda: rpc.cloudfile_publish_edit(repo,str(tmp),'/',path[1:],owner,json.dumps(condition(head,base,intent)))
    if n==3:
        lose_ack('seafile_cloudfile_publish_edit',publish)
        result=receipt(intent)['result_file_id']
    else: result=publish()
    r=receipt(intent);g=current_guard();h=rpc.get_repo(repo).head_cmmt_id;f=rpc.get_file_id_by_path(repo,path)
    assert r['state']=='published' and r['result_file_id']==f==result and r['result_commit_id']==h
    assert sql_branch()==h
    assert f!=base and h!=head and g['base_file_id']==f and g['guard_id']==proof['guard_id'] and g['pending_intent'] is None
    downloaded=download(content)
    # Discard the returned acknowledgement and recover solely from durable SQL.
    assert receipt(intent)==r
    with tx() as q:
        q.execute('SELECT snapshot FROM cf_commit_intent WHERE intent_id=%s',(intent,))
        persisted_snapshot=json.loads(q.fetchone()[0])
    assert persisted_snapshot==dict(id=intent,size=len(content),source=tmp.name)
    reports.append(dict(stage=f'Commit S{n}',intent=r,head=h,Branch=sql_branch(),file_id=f,
        guard=store.public(g),native_owner=g['owner_native_user'],snapshot=persisted_snapshot,download_sha256=downloaded))
    base,head=f,h
    print(f'PASS real Commit S{n}: {f} / {h}',flush=True)

intent=str(uuid4())
with tx() as q: store.prepare(q,**target,**proof,intent_id=intent,expected_file_id=base,staged_file_id=base,content_digest=hashlib.sha256(b'').hexdigest(),action='checkin-unchanged')
lose_ack('seafile_cloudfile_checkin_edit',lambda: rpc.cloudfile_checkin_edit(repo,path,owner,json.dumps(condition(head,base,intent))))
result=receipt(intent)['result_file_id']
r=receipt(intent);g=current_guard()
assert r['state']=='published' and r['result_file_id']==base==result and r['result_commit_id']==head
assert g['guard_id'] is None and g['pending_intent'] is None
assert g['generation']==proof['generation'] and g['credential_epoch']==0 and r['checked_in']
assert rpc.get_repo(repo).head_cmmt_id==head and rpc.get_file_id_by_path(repo,path)==base
assert sql_branch()==head
download(b'third native content\n')
assert receipt(intent)==r
reports.append(dict(stage='Checkin unchanged',intent=r,head=head,file_id=base,guard_id=g['guard_id'],pending_intent=g['pending_intent']))
Path('/lab/native-result.json').write_text(json.dumps(dict(repo=repo,path=path,F1=F1,H1=H1,resource_uid=uid,results=reports),indent=2))
print('PASS real native Checkout -> Commit -> Commit -> Checkin, final download S3',flush=True)

# Separate reservation for failure cases; the golden receipt remains released.
with tx() as q:
    guard=store.acquire(q,**target,**identity,mode='checkout',source='web',native_user=owner,base_file_id=base)
proof=dict(identity,guard_id=guard['guard_id'],generation=int(guard['generation']),credential_epoch=int(guard['credential_epoch']))
pending=str(uuid4());tmp=Path('/lab/S-negative.txt');tmp.write_bytes(b'preserve pending local work\n')
with tx() as q:
    store.prepare(q,**target,**proof,intent_id=pending,expected_file_id=base,staged_file_id=None,
        content_digest=hashlib.sha256(tmp.read_bytes()).hexdigest(),action='commit',
        snapshot=dict(id=pending,size=len(tmp.read_bytes()),source=tmp.name))

def refused(callback):
    try: callback()
    except SearpcError: pass
    else: raise AssertionError('native negative request unexpectedly succeeded')
    assert rpc.get_repo(repo).head_cmmt_id==head
    assert rpc.get_file_id_by_path(repo,path)==base
    assert current_guard()['guard_id']==proof['guard_id']
    assert current_guard()['pending_intent']==pending and receipt(pending)['state']=='prepared'
    assert tmp.read_bytes()==b'preserve pending local work\n'

bad=condition(head,base,pending)
refused(lambda: rpc.cloudfile_publish_edit(repo,str(tmp),'/', 'another-target.txt',owner,json.dumps(bad)))
bad.pop('path')
refused(lambda: rpc.cloudfile_publish_edit(repo,str(tmp),'/',path[1:],owner,json.dumps(bad)))
bad=condition(head,base,pending);bad['editing']['resource_uid']=str(uuid4())
refused(lambda: rpc.cloudfile_publish_edit(repo,str(tmp),'/',path[1:],owner,json.dumps(bad)))
bad=condition(head,base,pending);bad['editing']['repo_id']=str(uuid4())
refused(lambda: rpc.cloudfile_publish_edit(repo,str(tmp),'/',path[1:],owner,json.dumps(bad)))
print('PASS missing/mismatched path, repo and resource fail closed',flush=True)
refused(lambda: rpc.cloudfile_publish_edit(repo,str(tmp),'/',path[1:],owner,json.dumps(condition(H1,base,pending))))
refused(lambda: rpc.cloudfile_publish_edit(repo,str(tmp),'/',path[1:],owner,json.dumps(condition(head,F1,pending))))
print('PASS stale head and stale file proof preserve checkout and prepared intent',flush=True)
root=pymysql.connect(host=os.environ['CF_NATIVE_DB_HOST'],user='root',password='',database='cf_lab_seafile',autocommit=True)
with root.cursor() as q:
    q.execute("CREATE TRIGGER fixture_receipt_failure BEFORE UPDATE ON cf_commit_intent FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='injected native receipt failure'")
try:
    refused(lambda: rpc.cloudfile_publish_edit(repo,str(tmp),'/',path[1:],owner,json.dumps(condition(head,base,pending))))
finally:
    with root.cursor() as q: q.execute('DROP TRIGGER fixture_receipt_failure')
    root.close()
print('PASS native receipt SQL failure rolls back Branch, baseline and release',flush=True)
for user in (owner,'other@example.test'):
    refused(lambda: rpc.put_file(repo,str(tmp),'/',path[1:],user,head))
with tx() as q: store.cancel_prepared(q,**target,**proof,intent_id=pending)
# No-content Checkin must independently compare actual file ID against baseline.
with tx() as q:
    q.execute('UPDATE cf_edit_guard SET base_file_id=%s WHERE resource_uid=%s',(F1,uid))
    drift=str(uuid4())
    store.prepare(q,**target,**proof,intent_id=drift,expected_file_id=F1,staged_file_id=F1,content_digest=hashlib.sha256(b'').hexdigest(),action='checkin-unchanged')
pending=drift
refused(lambda: rpc.cloudfile_checkin_edit(repo,path,owner,json.dumps(condition(head,F1,drift))))
print('PASS no-content Checkin refuses baseline drift without release',flush=True)
with tx() as q:
    store.cancel_prepared(q,**target,**proof,intent_id=drift)
    q.execute('UPDATE cf_edit_guard SET base_file_id=%s WHERE resource_uid=%s',(base,uid))
    last=str(uuid4())
    store.prepare(q,**target,**proof,intent_id=last,expected_file_id=base,staged_file_id=base,content_digest=hashlib.sha256(b'').hexdigest(),action='checkin-unchanged')
rpc.cloudfile_checkin_edit(repo,path,owner,json.dumps(condition(head,base,last)))
assert current_guard()['guard_id'] is None and receipt(last)['checked_in']

# Manual lock uses native username, with a deliberately different business ID.
manual_repo=rpc.create_repo('Manual lock native','Isolated barrier semantics',owner,None,2,None,None)
rpc.post_file(manual_repo,str(file),'/',path[1:],owner)
manual_uid=str(uuid4());manual_target=dict(uid=manual_uid,repo=manual_repo,lifecycle='manual-native-fixture')
with tx() as q:
    q.execute("INSERT INTO cf_resource(uid,repo_id,kind,path,path_hash,lifecycle_ref,revision,state,updated_at) VALUES(%s,%s,'file',%s,%s,%s,1,'active',UTC_TIMESTAMP(6))",(manual_uid,manual_repo,path,hashlib.sha256(path.encode()).hexdigest(),manual_target['lifecycle']))
    manual=store.acquire(q,**manual_target,**identity,mode='file-lock',source='web',native_user=owner,base_file_id=rpc.get_file_id_by_path(manual_repo,path))
manual_head=rpc.get_repo(manual_repo).head_cmmt_id
try: rpc.put_file(manual_repo,str(tmp),'/',path[1:],'other@example.test',manual_head)
except SearpcError as e: assert e.code==600
else: raise AssertionError('manual lock allowed other native owner')
rpc.put_file(manual_repo,str(tmp),'/',path[1:],owner,manual_head)
assert rpc.get_repo(manual_repo).head_cmmt_id!=manual_head
manual_condition=condition(rpc.get_repo(manual_repo).head_cmmt_id,
    rpc.get_file_id_by_path(manual_repo,path),str(uuid4()))
manual_condition.pop('editing');manual_condition.pop('path')
manual_condition['scopes'][-1]['external_id']=manual_repo
tmp.write_bytes(b'manual owner conditional write\n')
rpc.cloudfile_put_file_with_barriers(manual_repo,str(tmp),'/',path[1:],owner,json.dumps(manual_condition))
with tx() as q:
    assert store.load(q,**manual_target)['base_file_id'] is None
    store.release(q,**manual_target,actor='employee',guard_id=manual['guard_id'],generation=int(manual['generation']))
print('PASS manual file-lock allows canonical native owner; rejects other user',flush=True)
report=json.loads(Path('/lab/native-result.json').read_text())
report['negative_cases']=['checkout plain owner/other denied','target path/repo/resource fail closed','stale head/file proof preserves intent','native receipt SQL failure rolls back publication','no-content baseline drift preserves checkout','manual native owner allowed/other denied']
report['response_loss']='Real native Commit and Checkin success replies fault-injected as lost before application decoding; durable receipts and checked_in recovered. Hub HTTP/browser retry is outside native fixture scope.'
report['product_scope']='Trusted identity/subject/session fixtures; HTTPS/OIDC issuance, policy/resource runtime, browser and Agent are not product E2E verified.'
Path('/lab/native-result.json').write_text(json.dumps(report,indent=2))
