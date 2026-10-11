"""Real optimistic CDC publication on the same resource after full publication.

Executed by native_optimistic_agent_e2e.py in the isolated native test process,
sharing its paired device fixture and current repo.
"""
A = b"A" * (7 * 1024 * 1024)
B = b"B" * (8 * 1024 * 1024)
C = b"C" * (5 * 1024 * 1024)
blocks = (A, B, C)
large = b"".join(blocks)
ids = [hashlib.sha1(x).hexdigest() for x in blocks]

def cdc_id(parts):
    raw = '{"block_ids": [' + ", ".join(
        json.dumps(hashlib.sha1(x).hexdigest()) for x in parts
    ) + '], "size": ' + str(sum(map(len, parts))) + ', "type": 1, "version": 1}'
    return hashlib.sha1(raw.encode()).hexdigest()

with lab.tx() as sql:
    newsnap = dict(snap, base_version=published)
    newer = sessions.create(sql, **owner, snapshot=newsnap)
    arguments = dict(**owner, session_id=newer.session_id, ticket=newer.ticket,
                     current_snapshot=newsnap, instance=origin)
    challenge = sessions.challenge(sql, **arguments)
    sessions.claim(sql, **arguments, challenge=challenge, signature=sign(challenge))
    newerrow = sessions._row(sql, **owner, session_id=newer.session_id)
    cdc_intent = str(uuid4())
    sql.execute("INSERT INTO cf_optimistic_upload_intent "
        "(intent_id,session_id,device_id,repo_id,base_file_id,content_digest,"
        "snapshot_size,state,created_at) "
        "VALUES(%s,%s,%s,%s,%s,%s,%s,'prepared',UTC_TIMESTAMP(6))",
        (cdc_intent, newer.session_id, device, repo, published,
         hashlib.sha256(large).hexdigest(), len(large)))

for part, blockid in zip(blocks, ids):
    snapshot_file = Path("/lab/optimistic-cdc-" + blockid)
    snapshot_file.write_bytes(part)
    try:
        assert lab.rpc.cloudfile_stage_raw_block(repo, blockid, str(snapshot_file), lab.owner) == 0
    finally:
        snapshot_file.unlink(missing_ok=True)
assert json.loads(lab.rpc.check_repo_blocks_missing(repo, json.dumps(ids))) == []

conditions = dict(condition, head_id=head, expected_file_id=published)
conditions["agent_upload"] = dict(
    session_id=newer.session_id, device_id=device,
    device_revision=str(newerrow[3]), session_revision=str(newerrow[9]),
    intent_id=cdc_intent)

old_head = lab.rpc.get_repo(repo).head_cmmt_id
try:
    lab.rpc.cloudfile_publish_optimistic_blocks(
        repo, json.dumps(list(reversed(ids))), str(len(large)),
        "/", path[1:], lab.owner, json.dumps(conditions))
except Exception:
    pass
else:
    raise AssertionError("Unordered optimistic CDC should not publish")
assert lab.rpc.get_repo(repo).head_cmmt_id == old_head
with lab.tx() as sql:
    sql.execute("SELECT state FROM cf_optimistic_upload_intent WHERE intent_id=%s", (cdc_intent,))
    assert sql.fetchone()[0] == "prepared"

cdc_published = lab.rpc.cloudfile_publish_optimistic_blocks(
    repo, json.dumps(ids), str(len(large)),
    "/", path[1:], lab.owner, json.dumps(conditions))
assert cdc_published == cdc_id(blocks) == lab.rpc.get_file_id_by_path(repo, path)
with lab.tx() as sql:
    sql.execute("SELECT state,result_file_id,result_commit_id "
                "FROM cf_optimistic_upload_intent WHERE intent_id=%s", (cdc_intent,))
    durable_cdc = sql.fetchone()
assert durable_cdc[0] == "published"
assert durable_cdc[1] == cdc_published and len(durable_cdc[2]) == 40
current_head = lab.rpc.get_repo(repo).head_cmmt_id
read_proof = lab.condition(current_head, cdc_published, str(uuid4()))
read_proof.pop("editing")
read_proof["path"] = path
for entry in read_proof["scopes"]:
    if entry["type"] == "repo":
        entry["external_id"] = repo
read_ticket = lab.rpc.seafile_cloudfile_issue_read_ticket(
    repo, path, current_head, cdc_published, "download", lab.owner,
    json.dumps(read_proof))
read_result = lab.requests.get("http://127.0.0.1:8082/cloudfile/read", headers={
    "Authorization": "Bearer " + read_ticket,
    "X-CloudFile-Filename": path[1:], "X-Forwarded-Proto": "https"}, timeout=30)
assert read_result.status_code == 200 and read_result.content == large
print("PASS ordinary Agent native CDC ordered blocks, durable Branch receipt, byte-identical HTTP read", flush=True)
