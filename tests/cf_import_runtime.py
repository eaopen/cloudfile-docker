"""Disposable native HTTP acceptance for the independent cf-import CLI."""

import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
from urllib.parse import urlencode


def exercise(*, docker, app, request, auth, repo):
    from smoke_ce14_runtime import native_path

    tool = Path(__file__).resolve().parents[1] / "tools"
    docker("cp", str(tool / "cf-import"), app + ":/tmp/cf-import")
    docker("cp", str(tool / "cf_import.py"), app + ":/tmp/cf_import.py")
    # Both the API and signed fileserver URLs use this fixture hostname.
    docker("exec", app, "sh", "-c", "printf '127.0.0.1 cloudfile-smoke.invalid\\n' >> /etc/hosts")
    docker("exec", "-i", app, "sh", "-c", "umask 077; cat > /tmp/cf-import-token",
           input=auth["Authorization"].removeprefix("Token "))

    def cli(*args):
        result = subprocess.run(["docker", "exec", app, "python3", "/tmp/cf-import", *args],
                                text=True, capture_output=True, timeout=90)
        if result.returncode:
            raise RuntimeError("cf_import_probe=" + args[0] + ":" + result.stderr.strip()[:200])
        return json.loads(result.stdout)

    def download(path):
        response = request("/api2/repos/" + repo + "/file/?" + urlencode({"p": path}), headers=auth)
        assert response["status"] == 200
        link = native_path(json.loads(response["body"]), "files")
        received = request(link)
        assert received["status"] == 200
        return received["body"]

    with tempfile.TemporaryDirectory(prefix="cf-import-runtime-") as temporary:
        source = Path(temporary) / "source"
        selected = source / "selected"
        (selected / "子目录").mkdir(parents=True)
        (selected / "empty").mkdir()
        (selected / "子目录" / "hello.txt").write_bytes("初次导入".encode())
        (selected / "remove.txt").write_bytes(b"remain on target")
        (source / "excluded.txt").write_bytes(b"not imported")
        docker("cp", str(source), app + ":/tmp/cf-import-source")

        job = "/tmp/cf-import-job"
        cli("create", "--job-dir", job, "--source", "local:///tmp/cf-import-source/selected",
            "--repo", repo, "--target", "/History/Selected", "--server", "http://cloudfile-smoke.invalid",
            "--token-file", "/tmp/cf-import-token")
        initial = cli("check", job)
        assert initial["actions"]["add"]["entries"] == 4
        planned = cli("plan", job, "--limit", "10")
        assert len(planned["entries"]) == 4
        applied = cli("apply", job, "--exclusive")
        assert applied["status"] == "complete"
        assert applied["actions"]["add"]["done"] == 4
        assert download("/History/Selected/子目录/hello.txt") == "初次导入".encode()
        assert download("/History/Selected/remove.txt") == b"remain on target"
        missing = request("/api2/repos/" + repo + "/file/?p=/History/Selected/excluded.txt", headers=auth)
        assert missing["status"] == 404
        directory = request("/api2/repos/" + repo + "/dir/?p=/History/Selected/empty", headers=auth)
        assert directory["status"] == 200 and json.loads(directory["body"]) == []
        assert cli("check", job)["actions"] == {}

        mutate = """from pathlib import Path
import os
root=Path('/tmp/cf-import-source/selected')
target=root/'子目录'/'hello.txt'
target.write_bytes('增量修改'.encode())
stamp=target.stat().st_mtime_ns+10_000_000_000
os.utime(target,ns=(stamp,stamp))
(root/'new.bin').write_bytes(bytes(range(256))*4097)
(root/'remove.txt').unlink()
"""
        docker("exec", app, "python3", "-c", mutate)
        delta = cli("check", job)
        assert delta["actions"]["add"]["entries"] == 1
        assert delta["actions"]["delete_candidate"]["entries"] == 1
        assert delta["actions"]["modify"]["entries"] >= 1
        cli("apply", job, "--exclusive")
        assert download("/History/Selected/子目录/hello.txt") == "增量修改".encode()
        expected_new = bytes(range(256)) * 4097
        actual_new = download("/History/Selected/new.bin")
        assert hashlib.sha256(actual_new).digest() == hashlib.sha256(expected_new).digest()
        assert download("/History/Selected/remove.txt") == b"remain on target"
        assert cli("check", job)["actions"]["delete_candidate"]["entries"] == 1

        external = request("/api2/repos/" + repo + "/dir/?p=/external", "POST",
                           urlencode({"operation": "mkdir"}).encode(),
                           {**auth, "Content-Type": "application/x-www-form-urlencoded"})
        assert external["status"] in (200, 201)
        command = ["docker", "exec", app, "python3", "/tmp/cf-import", "check", job]
        blocked = subprocess.run(command, text=True, capture_output=True, timeout=30)
        assert blocked.returncode == 2 and "repository changed" in blocked.stderr
        return {"result": "passed", "native_download_checks": 5, "checks": [
            "local_scoped_mapping", "empty_directory", "excluded_source", "native_sha256_download",
            "unchanged_check", "incremental_add_modify", "delete_candidate_only", "remote_head_conflict"]}
