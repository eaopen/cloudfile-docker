"""Paired identity fixtures -> Django raw upload -> real Native Branch/HTTP read.

OIDC login and platform credentials are outside this isolated native fixture.
"""
import base64,hashlib,json,os,sys,subprocess
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4
sys.path[:0]=['/hub','/tests','/backend/seafile-server/seafile/lib/python3.12/site-packages']
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from django.conf import settings
if not settings.configured: settings.configure(SECRET_KEY='isolated-fixture',DEFAULT_CHARSET='utf-8')
from django.test import RequestFactory
from cloudfile_extensions.local_edit.device_proof import DevicePublicKey
from cloudfile_extensions.local_edit.device_store import DeviceStore
from cloudfile_extensions.local_edit.session_store import LocalSessionStore
from cloudfile_extensions.local_edit.agent_runtime import AgentClaimRuntime
from cloudfile_extensions.local_edit.commit_contract import bind_request
from cloudfile_extensions.local_edit.upload_grant import seal
from cloudfile_extensions.local_edit.upload_http import AgentUploadView
import native_editing_e2e as lab

private=ec.generate_private_key(ec.SECP256R1())
def encode(value): return base64.urlsafe_b64encode(value).decode().rstrip('=')
def sign(challenge):
    r,s=decode_dss_signature(private.sign(challenge.message(),ec.ECDSA(hashes.SHA256())))
    return encode(r.to_bytes(32,'big')+s.to_bytes(32,'big'))
public=private.public_key().public_numbers()
key=DevicePublicKey.parse(dict(kty='EC',crv='P-256',x=encode(public.x.to_bytes(32,'big')),y=encode(public.y.to_bytes(32,'big'))))
devices,sessions,store=DeviceStore(),LocalSessionStore(),lab.store
device_id=str(uuid4());owner=dict(provider='fixture',actor='employee',device_id=device_id)
origin='https://cloudfile.invalid';secret=b'isolated-device-publication-secret-0001'
with lab.tx() as sql:
    devices.create_pending(sql,**owner,public_key=key)
    challenge=devices.issue(sql,**owner,instance=origin,session_id=str(uuid4()),operation='pair',request_sha256='a'*64)
    devices.consume(sql,provider='fixture',actor='employee',challenge=challenge,signature=sign(challenge))
    guard=store.acquire(sql,**lab.target,**lab.identity,mode='checkout',source='web',native_user=lab.owner,base_file_id=lab.base)
    snapshot=dict(resource=dict(repo_id=lab.repo,path=lab.path,kind='file'),resource_uid=lab.uid,
        lifecycle_ref=lab.target['lifecycle'],base_version=lab.base,resource_revision='1',local_open_type='',mode='exclusive-edit',
        lease=dict(fencing=guard['generation'],token_digest=hashlib.sha256(lab.identity['token'].encode()).hexdigest()))
    issued,created,_,_=sessions.create_exclusive(sql,**owner,snapshot=snapshot,secret=secret,token=lab.identity['token'])
    assert created
with lab.tx() as sql:
    replay,created,_,_=sessions.create_exclusive(sql,**owner,snapshot=snapshot,secret=secret,token=lab.identity['token'])
    assert not created and replay==issued
    args=dict(**owner,session_id=issued.session_id,ticket=issued.ticket,current_snapshot=snapshot,instance=origin)
    challenge=sessions.challenge(sql,**args)
    sessions.claim(sql,**args,challenge=challenge,signature=sign(challenge))
@contextmanager
def connection(): yield lab.db
runtime=object.__new__(AgentClaimRuntime);runtime.pid=os.getpid();runtime.agent2_exclusive_enabled=True
runtime.resources=SimpleNamespace(provider='fixture',connection=connection)
runtime.instance,runtime.secret,runtime.sessions=origin,secret,sessions
Path('/lab/seafile-data/httptemp').mkdir(exist_ok=True);os.environ['SEAFILE_DATA_DIR']='/lab/seafile-data'
view=AgentUploadView.as_view(runtime=runtime);results=[]
def call(method,args,deadline):
    if method=='seafile_get_repo': return {'head_cmmt_id':lab.rpc.get_repo(args[0]).head_cmmt_id}
    assert method=='seafile_cloudfile_publish_edit'
    try: result=lab.rpc.cloudfile_publish_edit(*args)
    except Exception as error:
        print('Native fixture publication failed:',type(error).__name__,str(error),flush=True)
        raise
    if lose_reply: raise ConnectionError('real native publication reply lost')
    return result
for index,action in enumerate(('commit','commit','checkin'),1):
    content=('device committed version %d\n'%index).encode();intent=str(uuid4())
    with lab.tx() as sql:
        guard=store.load(sql,**lab.target);row=sessions._row(sql,**owner,session_id=issued.session_id)
        saved=json.loads(row[4])
        body=dict(session_id=issued.session_id,device_id=device_id,intent_id=intent,guard_id=guard['guard_id'],
            generation=str(guard['generation']),credential_epoch=str(guard['credential_epoch']),token=lab.identity['token'],
            base_file_id=saved['base_version'],content_digest=hashlib.sha256(content).hexdigest(),snapshot_size=len(content),action=action)
        digest=bind_request(body,snapshot=saved,session_row=row,edit_guard=guard,current_native=lab.owner)
        challenge=devices.issue(sql,**owner,instance=origin,session_id=issued.session_id,operation='commit',request_sha256=digest)
        devices.consume(sql,provider='fixture',actor='employee',challenge=challenge,signature=sign(challenge))
        store.prepare(sql,**lab.target,**lab.identity,guard_id=guard['guard_id'],generation=guard['generation'],
            credential_epoch=guard['credential_epoch'],intent_id=intent,expected_file_id=body['base_file_id'],staged_file_id=None,
            content_digest=body['content_digest'],action=action,snapshot=dict(id=intent,size=len(content),source='agent2-device',
                session_id=issued.session_id,device_id=device_id))
    condition=dict(path=lab.path,context=dict(provider='fixture',userId='employee',epoch='d'*32),
        scopes=[dict(type='provider',provider='fixture',external_id='fixture'),dict(type='user',provider='fixture',external_id='employee'),dict(type='repo',provider='cloudfile',external_id=lab.repo)],
        local_commit=dict(session_id=issued.session_id,device_id=device_id,device_revision=str(row[3]),session_revision=str(row[9])),
        editing=dict(repo_id=lab.repo,resource_uid=lab.uid,guard_id=guard['guard_id'],generation=str(guard['generation']),credential_epoch=str(guard['credential_epoch']),holder=lab.identity['holder'],token=lab.identity['token'],intent_id=intent,base_file_id=body['base_file_id']))
    grant=dict(instance=origin,condition=condition,native_user=lab.owner,content_digest=body['content_digest'],snapshot_size=len(content),action=action)
    ticket=seal(secret,grant)
    def request():
        value=RequestFactory().post('/device-upload/',data=content,content_type='application/octet-stream',secure=True,HTTP_AUTHORIZATION='Bearer '+ticket,HTTP_IDEMPOTENCY_KEY=intent)
        value.META.pop('HTTP_COOKIE',None)
        return value
    lose_reply=False
    if index==1:
        before_head=lab.rpc.get_repo(lab.repo).head_cmmt_id
        mutations=[
            ("device revoked", "UPDATE cf_local_device SET state='revoked' WHERE device_id=%s", (device_id,),
             "UPDATE cf_local_device SET state='active' WHERE device_id=%s", (device_id,)),
            ("session expired", "UPDATE cf_edit_session SET expires_at=1 WHERE session_id=%s", (issued.session_id,),
             "UPDATE cf_edit_session SET expires_at=%s WHERE session_id=%s", (row[8],issued.session_id)),
            ("stale session revision", "UPDATE cf_edit_session SET revision=revision+1 WHERE session_id=%s", (issued.session_id,),
             "UPDATE cf_edit_session SET revision=%s WHERE session_id=%s", (row[9],issued.session_id)),
            ("guard expired", "UPDATE cf_edit_guard SET lease_until=UTC_TIMESTAMP(6) WHERE resource_uid=%s", (lab.uid,),
             "UPDATE cf_edit_guard SET lease_until=%s WHERE resource_uid=%s", (guard['lease_until'],lab.uid)),
            ("library readonly", "UPDATE RepoInfo SET status=1 WHERE repo_id=%s", (lab.repo,),
             "UPDATE RepoInfo SET status=0 WHERE repo_id=%s", (lab.repo,)),
        ]
        for name,sql,args,restore,restore_args in mutations:
            with lab.tx() as cursor: cursor.execute(sql,args)
            try:
                with patch('cloudfile_extensions.identity.ticket_transport._call',side_effect=call): rejected=view(request())
                assert rejected.status_code!=200,(name,rejected.content)
                assert lab.rpc.get_repo(lab.repo).head_cmmt_id==before_head
                with lab.tx() as cursor: assert store.intent(cursor,uid=lab.uid,intent_id=intent)['state']=='prepared'
                print('PASS device native rejects '+name+'; intent and Branch retained',flush=True)
            finally:
                with lab.tx() as cursor: cursor.execute(restore,restore_args)
    lose_reply=index==2
    with patch('cloudfile_extensions.identity.ticket_transport._call',side_effect=call): response=view(request())
    assert response.status_code==200,(response.status_code,response.content)
    receipt=json.loads(response.content)['intent'];head=lab.rpc.get_repo(lab.repo).head_cmmt_id
    file_id=lab.rpc.get_file_id_by_path(lab.repo,lab.path)
    assert receipt['state']=='published' and file_id==receipt['result_file_id'] and receipt['checked_in']==(action=='checkin')
    with lab.tx() as sql:
        updated=sessions._row(sql,**owner,session_id=issued.session_id);after=store.load(sql,**lab.target)
        assert json.loads(updated[4])['base_version']==file_id and updated[9]==row[9]+1
        assert updated[5]==('completed' if action=='checkin' else 'active')
        assert (after['guard_id'] is None)==(action=='checkin')
        sql.execute('SELECT commit_id FROM Branch WHERE repo_id=%s',(lab.repo,));assert sql.fetchone()[0]==head
    with patch('cloudfile_extensions.identity.ticket_transport._call',side_effect=AssertionError('duplicate publish')): repeated=view(request())
    assert repeated.status_code==200 and json.loads(repeated.content)['intent']==receipt
    read=lab.condition(head,file_id,str(uuid4()));read.pop('editing')
    ticket_read=lab.rpc.seafile_cloudfile_issue_read_ticket(lab.repo,lab.path,head,file_id,'download',lab.owner,json.dumps(read))
    downloaded=lab.requests.get('http://127.0.0.1:8082/cloudfile/read',headers={'Authorization':'Bearer '+ticket_read,'X-CloudFile-Filename':lab.path[1:],'X-Forwarded-Proto':'https'},timeout=10)
    assert downloaded.status_code==200 and downloaded.content==content
    results.append(dict(action=action,intent=receipt,file_id=file_id,head=head,session_state=updated[5],session_revision=updated[9],download_sha256=hashlib.sha256(content).hexdigest(),lost_native_reply=lose_reply,repeated_without_publication=True))
    print('PASS device native %s %d; session %s; bytes verified'%(action,index,updated[5]),flush=True)
Path('/lab/native-device-result.json').write_text(json.dumps(dict(product_scope='Paired device/current identity fixtures, Django HTTP adapter and real native storage; browser TLS/OIDC and OS credentials require platform acceptance.',native_build_info=Path('/backend/build-info.txt').read_text(),native_binary_sha256=hashlib.sha256(Path('/backend/seafile-server/seafile/bin/seaf-server').read_bytes()).hexdigest(),hub_commit=subprocess.check_output(['git','-C','/hub','rev-parse','HEAD'],text=True).strip(),negative_cases=[name for name,*_ in mutations],checkout_replay_same_session=True,device_id=device_id,session_id=issued.session_id,repo=lab.repo,results=results),indent=2))
