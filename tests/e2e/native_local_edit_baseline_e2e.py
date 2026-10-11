"""Native guarded manual-update baseline acceptance: original File ID wins.

This is the isolated Server fixture, not real Browser/Agent HTTPS acceptance.
"""
import json
from pathlib import Path
from uuid import uuid4

import native_editing_e2e as lab
from seafile.rpcclient import SearpcError


def submit(expected_file, content, *, expected_head=None):
    current_head = expected_head or lab.rpc.get_repo(lab.repo).head_cmmt_id
    condition = lab.condition(current_head, expected_file, str(uuid4()))
    condition.pop("editing")
    condition.pop("path")
    condition["expected_file_id"] = expected_file
    file = Path("/lab/manual-baseline-publish.txt")
    file.write_bytes(content)
    return lab.rpc.cloudfile_put_file_with_barriers(
        lab.repo, str(file), "/", lab.path[1:], lab.owner,
        json.dumps(condition, separators=(",", ":")))


baseline = lab.rpc.get_file_id_by_path(lab.repo, lab.path)
head = lab.rpc.get_repo(lab.repo).head_cmmt_id
assert baseline != lab.F1, "fixture must carry a changed file baseline"
try:
    submit(lab.F1, b"unsafe overwrite from old local copy")
except SearpcError as error:
    assert error.code == 601, (error.code, error)
else:
    raise AssertionError("stale original File ID overwritten")
assert lab.rpc.get_repo(lab.repo).head_cmmt_id == head
assert lab.rpc.get_file_id_by_path(lab.repo, lab.path) == baseline
print("PASS stale local file ID refused even with current head",flush=True)

updated = b"new local copy with correct expected original file ID\n"
result = submit(baseline, updated)
assert result == lab.rpc.get_file_id_by_path(lab.repo, lab.path)
assert lab.download(updated)
print("PASS original File ID condition publishes correct file, downloads byte-identically",flush=True)

head_after = lab.rpc.get_repo(lab.repo).head_cmmt_id
try:
    submit(baseline, updated)
except SearpcError as error:
    assert error.code == 601, (error.code, error)
else:
    raise AssertionError("identical bytes accepted stale base ID")
assert lab.rpc.get_repo(lab.repo).head_cmmt_id == head_after
print("PASS identical-content stale baseline cannot bypass version fence",flush=True)
Path("/lab/native-local-edit-result.json").write_text(json.dumps(
    dict(verified="isolated_seafile_native", original_baseline=baseline,
         updated_file_id=result, final_head=head_after,
         stale_rejected=True, current_baseline_accepted=True,
         identical_stale_rejected=True), indent=2))
