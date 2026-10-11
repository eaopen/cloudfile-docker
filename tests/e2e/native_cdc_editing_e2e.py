"""Real Seafile storage test for CloudFile guarded CDC CommitBlocks.

Uses the same upstream native libsearpc and guarded Branch CAS as full-file
publish_edit; no generic commitonly token, no production database. It verifies
that raw block staging is pathless, edits have the same durable CommitIntent
receipt and a second version uploads *only new* block data.

Trusted OIDC actors are isolated fixtures. This is NOT installed Agent E2E.
"""
import hashlib
import json
from pathlib import Path
from uuid import uuid4

import native_editing_e2e as lab


def sha1(payload):
    return hashlib.sha1(payload).hexdigest()


def file_object_id(parts):
    names = ", ".join(json.dumps(sha1(b)) for b in parts)
    raw = '{"block_ids": [' + names + '], "size": ' + str(sum(map(len, parts))) + ', "type": 1, "version": 1}'
    return hashlib.sha1(raw.encode('utf-8')).hexdigest()


repo, target, actor = lab.repo, lab.target, lab.identity
base = lab.rpc.get_file_id_by_path(repo, lab.path)
head = lab.rpc.get_repo(repo).head_cmmt_id
with lab.tx() as cursor:
    guard = lab.store.acquire(cursor, **target, **actor, mode="checkout",
                              source="web", native_user=lab.owner,
                              base_file_id=base)
proof = dict(actor, guard_id=guard["guard_id"],
             generation=int(guard["generation"]),
             credential_epoch=int(guard["credential_epoch"]))

# Reuse nontrivial stored blocks on the second version. Seafile block storage
# SHA-1 names refer to raw bytes, not to the user's local filename.
A = b"A" * (7 * 1024 * 1024)
B = b"B" * (8 * 1024 * 1024)
C = b"C" * (5 * 1024 * 1024)
D = b"D" * (5 * 1024 * 1024)
reports = []
total_sent = 0

for i, (parts, action) in enumerate((((A, B, C), "commit"),
                                      ((A, B, D), "checkin")), 1):
    content = b"".join(parts)
    ids = [sha1(part) for part in parts]
    assert len(set(ids)) == len(ids)
    missing = json.loads(lab.rpc.check_repo_blocks_missing(repo, json.dumps(ids)))
    want = ids if i == 1 else [sha1(D)]
    assert missing == want, (missing, want)
    stage_bytes = 0
    for id, part in zip(ids, parts):
        if id not in missing:
            continue
        path = Path("/lab/cdc-block-" + id)
        path.write_bytes(part)
        try:
            assert lab.rpc.cloudfile_stage_raw_block(repo, id, str(path), lab.owner) == 0
        finally:
            path.unlink(missing_ok=True)
        stage_bytes += len(part)
    total_sent += stage_bytes
    assert json.loads(lab.rpc.check_repo_blocks_missing(repo, json.dumps(ids))) == []

    # One attempt to stage a block under an incorrect SHA-1 must fail.
    if i == 1:
        bad_path = Path("/lab/cdc-wrong-block")
        bad_path.write_bytes(b"unsafe not matching the supplied identity")
        try:
            try:
                lab.rpc.cloudfile_stage_raw_block(repo, ids[0], str(bad_path), lab.owner)
            except Exception:
                pass
            else:
                raise AssertionError("Accepted a staged block whose SHA-1 is wrong")
        finally:
            bad_path.unlink(missing_ok=True)

    intent = str(uuid4())
    with lab.tx() as cursor:
        lab.store.prepare(cursor, **target, **proof, intent_id=intent,
                          expected_file_id=base, staged_file_id=None,
                          content_digest=hashlib.sha256(content).hexdigest(),
                          action=action,
                          snapshot=dict(id=intent, size=len(content),
                                        source="cdc-native-fixture"))
    condition = lab.condition(head, base, intent)
    condition["editing"].update(
        guard_id=proof["guard_id"],
        generation=str(proof["generation"]),
        credential_epoch=str(proof["credential_epoch"]),
        holder=actor["holder"], token=actor["token"])

    # A valid manifest in the wrong order is NOT a valid current version.
    before = lab.rpc.get_repo(repo).head_cmmt_id
    try:
        lab.rpc.cloudfile_publish_edit_blocks(repo, json.dumps(list(reversed(ids))),
            str(len(content)), "/", lab.path[1:], lab.owner, json.dumps(condition))
    except Exception:
        pass
    else:
        raise AssertionError("Mismatched ordered block manifest published")
    assert lab.rpc.get_repo(repo).head_cmmt_id == before
    assert lab.receipt(intent)["state"] == "prepared"

    # The real guarded native publisher builds the canonical Seafile file
    # object from the ordered block IDs and linearizes the receipt in Branch.
    result = lab.rpc.cloudfile_publish_edit_blocks(repo, json.dumps(ids),
        str(len(content)), "/", lab.path[1:], lab.owner, json.dumps(condition))
    row = lab.receipt(intent)
    published = lab.rpc.get_file_id_by_path(repo, lab.path)
    assert row["state"] == "published"
    assert published == result == row["result_file_id"] == file_object_id(parts), (
        published, result, row["result_file_id"], file_object_id(parts))
    assert row["checked_in"] is (action == "checkin")
    assert lab.rpc.get_repo(repo).head_cmmt_id != head
    assert lab.download(content) == hashlib.sha256(content).hexdigest()
    # Repeated original Intent cannot change the already-committed Branch.
    final_head = lab.rpc.get_repo(repo).head_cmmt_id
    with lab.tx() as cursor:
        state = lab.store.load(cursor, **target)
        assert (state["guard_id"] is None) == (action == "checkin")
        assert state["pending_intent"] is None
        assert state["base_file_id"] == (None if action == "checkin" else published)
    reports.append(dict(action=action, result_file_id=published,
        staged_bytes=stage_bytes, snapshot_bytes=len(content),
        intent_id=intent, checked_in=row["checked_in"], native_branch=final_head))
    print("PASS guarded native CDC", action, "bytes", len(content),
          "new raw bytes", stage_bytes, "seafile object", published, flush=True)
    base, head = published, final_head

assert total_sent < sum(r["snapshot_bytes"] for r in reports)
assert reports[1]["staged_bytes"] == len(D)
result = dict(status="PASSED_IN_ISOLATED_NATIVE_SERVER",
              note="Device/OIDC identity is a fixture; GUI HTTPS and macOS/Windows credentials not tested",
              first_file_id=reports[0]["result_file_id"],
              final_file_id=reports[-1]["result_file_id"],
              total_staged_bytes=total_sent,
              full_upload_baseline=sum(r["snapshot_bytes"] for r in reports),
              items=reports)
Path("/lab/native-cdc-result.json").write_text(json.dumps(result, indent=2))
print("PASS Native direct CDC two versions and final Checkin with persisted receipts", flush=True)
