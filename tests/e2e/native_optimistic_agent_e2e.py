"""Isolated real Seafile Native Branch test of optimistic Agent session writes.

A paired device and an existing optimistic-edit session are fixtures here.
The actual Hub device proof + raw HTTP adapter is tested separately.
No production account, repository or server is touched.
"""
import base64
import hashlib
import json
from pathlib import Path
from uuid import uuid4

import native_editing_e2e as lab
from seafile.rpcclient import SearpcError
from cloudfile_extensions.local_edit.device_proof import DevicePublicKey
from cloudfile_extensions.local_edit.device_store import DeviceStore
from cloudfile_extensions.local_edit.session_store import LocalSessionStore
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

origin = "https://cloudfile.invalid"
repo = lab.rpc.create_repo("Optimistic upload Native", "Isolated device upload", lab.owner, None, 2, None, None)
path = "/optimistic-test.docx"
base_bytes = b"original local-edit version\n"
source = Path("/lab/optimistic-initial.docx")
source.write_bytes(base_bytes)
lab.rpc.post_file(repo, str(source), "/", path[1:], lab.owner)
base = lab.rpc.get_file_id_by_path(repo,path)
uid = str(uuid4())
lifecycle = "optimistic-native-fixture"
actor, provider = "employee", "fixture"
secret = ec.generate_private_key(ec.SECP256R1())
pub = secret.public_key().public_numbers()
enc = lambda raw: base64.urlsafe_b64encode(raw).decode().rstrip("=")
key = DevicePublicKey.parse(dict(kty="EC",crv="P-256",
    x=enc(pub.x.to_bytes(32,"big")),y=enc(pub.y.to_bytes(32,"big"))))

def sign(challenge):
    r,s = decode_dss_signature(secret.sign(challenge.message(),ec.ECDSA(hashes.SHA256())))
    return enc(r.to_bytes(32,"big")+s.to_bytes(32,"big"))

device = str(uuid4())
owner = dict(provider=provider,actor=actor,device_id=device)
devices,sessions = DeviceStore(),LocalSessionStore()
with lab.tx() as sql:
    devices.create_pending(sql,**owner,public_key=key)
    chall=devices.issue(sql,**owner,instance=origin,session_id=str(uuid4()),
        operation="pair",request_sha256="a"*64)
    devices.consume(sql,provider=provider,actor=actor,
        challenge=chall,signature=sign(chall))
    sql.execute("INSERT INTO cf_managed_library(repo_id,created_at) VALUES(%s,UTC_TIMESTAMP(6))",(repo,))
    sql.execute("INSERT INTO cf_resource(uid,repo_id,kind,path,path_hash,lifecycle_ref,revision,state,updated_at)"
        " VALUES(%s,%s,'file',%s,%s,%s,1,'active',UTC_TIMESTAMP(6))",
        (uid,repo,path,hashlib.sha256(path.encode()).hexdigest(),lifecycle))
    snap=dict(resource=dict(repo_id=repo,path=path,kind="file"),
        resource_uid=uid,lifecycle_ref=lifecycle,base_version=base,
        resource_revision="1",local_open_type="",mode="optimistic-edit",lease=None)
    issued=sessions.create(sql,**owner,snapshot=snap)
    kwargs=dict(**owner,session_id=issued.session_id,ticket=issued.ticket,
                current_snapshot=snap,instance=origin)
    chall=sessions.challenge(sql,**kwargs)
    sessions.claim(sql,**kwargs,challenge=chall,signature=sign(chall))
    row=sessions._row(sql,**owner,session_id=issued.session_id)

intent_id=str(uuid4())
upload_bytes=b"captured and approved ordinary local edit\n"
with lab.tx() as sql:
    sql.execute("INSERT INTO cf_optimistic_upload_intent "
        "(intent_id,session_id,device_id,repo_id,base_file_id,content_digest,"
        "snapshot_size,state,created_at) "
        "VALUES(%s,%s,%s,%s,%s,%s,%s,'prepared',UTC_TIMESTAMP(6))",
        (intent_id,issued.session_id,device,repo,base,
         hashlib.sha256(upload_bytes).hexdigest(),len(upload_bytes)))

condition=dict(path=path,expected_file_id=base,
    context=dict(provider=provider,userId=actor,epoch="d"*32),
    scopes=[dict(type="provider",provider=provider,external_id=provider),
      dict(type="user",provider=provider,external_id=actor),
      dict(type="repo",provider="cloudfile",external_id=repo)],
    agent_upload=dict(session_id=issued.session_id,device_id=device,
                      device_revision=str(row[3]),session_revision=str(row[9]),intent_id=intent_id))

def put(expected, content):
    cond=dict(condition)
    cond["expected_file_id"]=expected
    cond["head_id"]=lab.rpc.get_repo(repo).head_cmmt_id
    tmp=Path("/lab/optimistic-snapshot")
    tmp.write_bytes(content)
    return lab.rpc.cloudfile_put_file_with_barriers(
        repo,str(tmp),"/",path[1:],lab.owner,json.dumps(cond))

def refuse(expected,content):
    head=lab.rpc.get_repo(repo).head_cmmt_id
    try:put(expected,content)
    except SearpcError:pass
    else:raise AssertionError("optimistic branch write unexpectedly succeeded")
    assert lab.rpc.get_repo(repo).head_cmmt_id==head

# A live checkout from the same user must not be overwritten by an
# optimistic agent; it is a separate editing mode and has no Checkout proof.
with lab.tx() as sql:
    g=lab.store.acquire(sql,uid=uid,repo=repo,lifecycle=lifecycle,
        actor=actor,holder="native-optimistic-editor",token="e"*64,
        mode="checkout",source="web",native_user=lab.owner,base_file_id=base)
refuse(base,b"must not overwrite active checkout")
with lab.tx() as sql:
    lab.store.release(sql,uid=uid,repo=repo,lifecycle=lifecycle,
                      actor=actor,guard_id=g["guard_id"],generation=int(g["generation"]),
                      proof=dict(holder="native-optimistic-editor",token="e"*64,
                                 credential_epoch=int(g["credential_epoch"])))
print("PASS optimistic Agent cannot bypass active Checkout",flush=True)

# Revoke the device after issuance: the final Branch transaction rechecks.
with lab.tx() as sql:
    sql.execute("UPDATE cf_local_device SET state='revoked' WHERE device_id=%s",(device,))
try:refuse(base,b"must not publish after revoked device")
finally:
    with lab.tx() as sql:
        sql.execute("UPDATE cf_local_device SET state='active' WHERE device_id=%s",(device,))
print("PASS optimistic Agent revoked device rejected by native Branch",flush=True)

refuse("f"*40,b"wrong original file version")
assert lab.rpc.get_file_id_by_path(repo,path)==base
print("PASS optimistic Agent cannot submit stale or incorrect base",flush=True)

payload=upload_bytes
published=put(base,payload)
with lab.tx() as sql:
    sql.execute("SELECT state,result_file_id,result_commit_id "
                "FROM cf_optimistic_upload_intent WHERE intent_id=%s",(intent_id,))
    state,fileid,commitid=sql.fetchone()
assert state=="published" and fileid==published and len(commitid)==40
print("PASS ordinary Intent published in same Branch transaction",flush=True)
head=lab.rpc.get_repo(repo).head_cmmt_id
assert published != base and lab.rpc.get_file_id_by_path(repo,path)==published
read=lab.condition(head,published,str(uuid4()))
read.pop("editing")
read["path"]=path
for item in read["scopes"]:
    if item["type"]=="repo":item["external_id"]=repo
ticket=lab.rpc.seafile_cloudfile_issue_read_ticket(
    repo,path,head,published,"download",lab.owner,json.dumps(read))
response=lab.requests.get("http://127.0.0.1:8082/cloudfile/read",headers={
    "Authorization":"Bearer "+ticket,
    "X-CloudFile-Filename":path[1:],
    "X-Forwarded-Proto":"https"},timeout=20)
assert response.status_code==200 and response.content==payload, (
    response.status_code,response.content[:200])
print("PASS paired optimistic Agent Native publish; full byte-identical HTTP download",flush=True)

# Existing session binds its ORIGINAL version. Native must reject a second
# one-shot upload under that stale session; never silently create new intent.
refuse(base,b"unapproved second publication")
print("PASS original optimistic session cannot silently overwrite second version",flush=True)

# The second legitimate session is tested with raw CDC blocks, not a
# duplicate ordinary upload and not an exclusive Checkout.
exec(Path("/tests/native_optimistic_cdc_e2e.py").read_text())

Path("/lab/native-optimistic-result.json").write_text(json.dumps(dict(
    scope="isolated Native device/session fixture (not installed Agent/OIDC)",
    file_id=published,head=head,original_file_id=base,
    download_sha256=hashlib.sha256(payload).hexdigest(),
    revoked_device_rejected=True,checkout_write_rejected=True,
    stale_base_rejected=True,second_write_without_new_session_rejected=True),indent=2))
