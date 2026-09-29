"""Local behavior checks for the standalone one-way importer."""

import argparse
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import cf_import


class FakeTarget:
    def __init__(self):
        self.head_value = "0" * 40
        self.directories = {"/"}
        self.files = {}

    def head(self):
        return self.head_value

    def advance(self):
        self.head_value = f"{int(self.head_value, 16) + 1:040x}"

    def dir_entries(self, path):
        if path not in self.directories:
            return None
        prefix = path.rstrip("/") + "/"
        return [name for name in self.files if name.startswith(prefix)]

    def file_exists(self, path):
        return path in self.files

    def ensure_dir(self, path, expected_head):
        if self.head() != expected_head:
            raise cf_import.ImportErrorSafe("unexpected remote HEAD")
        value = ""
        for part in cf_import.valid_parts(path, absolute=True):
            value += "/" + part
            if value not in self.directories:
                self.directories.add(value)
                self.advance()
        return self.head()

    def upload(self, path, stream, size, *, replace):
        if (path in self.files) != replace:
            raise AssertionError("incorrect create/update operation")
        data = stream.read()
        if len(data) != size:
            raise AssertionError("incorrect upload size")
        self.files[path] = data
        self.advance()

    def verify_file(self, path, size, sha256):
        data = self.files[path]
        if len(data) != size or hashlib.sha256(data).hexdigest() != sha256:
            raise cf_import.ImportErrorSafe("target mismatch")


class FakeResponse:
    def __init__(self, status, value=None, payload=b""):
        self.status_code = status
        self.value = value
        self.payload = payload

    def json(self):
        return self.value

    def iter_content(self, _):
        yield self.payload

    def close(self):
        pass


class CfImportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="cf-import-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.job = self.root / "job"
        self.token = self.root / "token"
        self.token.write_text("test-token\n")

    def create(self, *, source=None):
        args = argparse.Namespace(job_dir=str(self.job), source=source or "local://" + str(self.source),
                                  repo="00000000-0000-0000-0000-000000000001", target="/历史资料/项目 A",
                                  server="http://cloudfile.invalid", token_file=str(self.token), fileserver_origin=None,
                                  filestash_url=None, filestash_token_file=None)
        with contextlib.redirect_stdout(io.StringIO()):
            cf_import.create(args)

    def call(self, function, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            function(argparse.Namespace(job_dir=str(self.job), **kwargs))
        return json.loads(output.getvalue())

    def test_local_mapping_incremental_and_delete_candidate(self):
        (self.source / "图纸").mkdir()
        (self.source / "图纸" / "零字节.txt").write_bytes(b"")
        (self.source / "图纸" / "数据.bin").write_bytes(b"x" * (2 * 1024 * 1024 + 17))
        self.create()
        remote = FakeTarget()
        with mock.patch.object(cf_import, "Target", return_value=remote):
            first = self.call(cf_import.check)
            self.assertEqual(first["actions"]["add"]["entries"], 3)
            self.call(cf_import.apply, exclusive=True)
            self.assertEqual(remote.files["/历史资料/项目 A/图纸/零字节.txt"], b"")
            self.assertEqual(len(remote.files["/历史资料/项目 A/图纸/数据.bin"]), 2 * 1024 * 1024 + 17)
            self.assertEqual(self.call(cf_import.check)["actions"], {})

            changed = self.source / "图纸" / "数据.bin"
            changed.write_bytes(b"new")
            timestamp = changed.stat().st_mtime_ns + 10_000_000_000
            os.utime(changed, ns=(timestamp, timestamp))
            (self.source / "图纸" / "零字节.txt").unlink()
            (self.source / "图纸" / "新增.txt").write_text("新文件", encoding="utf-8")
            second = self.call(cf_import.check)
            self.assertEqual(second["actions"]["add"]["entries"], 1)
            self.assertEqual(second["actions"]["modify"]["entries"], 2)  # file and parent directory
            self.assertEqual(second["actions"]["delete_candidate"]["entries"], 1)
            self.call(cf_import.apply, exclusive=True)
            self.assertEqual(remote.files["/历史资料/项目 A/图纸/数据.bin"], b"new")
            self.assertIn("/历史资料/项目 A/图纸/零字节.txt", remote.files)
            self.assertEqual(self.call(cf_import.check)["actions"]["delete_candidate"]["entries"], 1)

    def test_remote_change_blocks_apply_and_source_symlink_blocks_check(self):
        (self.source / "file.txt").write_text("source")
        self.create()
        remote = FakeTarget()
        with mock.patch.object(cf_import, "Target", return_value=remote):
            self.call(cf_import.check)
            remote.advance()
            with self.assertRaisesRegex(cf_import.ImportErrorSafe, "repository changed"):
                self.call(cf_import.apply, exclusive=True)
            (self.source / "link").symlink_to(self.token)
            with self.assertRaisesRegex(cf_import.ImportErrorSafe, "link or special"):
                self.call(cf_import.check)

    def test_retry_after_precommit_failure_and_fail_closed_after_unknown_commit(self):
        (self.source / "one.txt").write_bytes(b"one")
        (self.source / "two.txt").write_bytes(b"two")
        self.create()
        remote = FakeTarget()
        original_upload = remote.upload
        calls = 0

        def fail_before_commit(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise cf_import.ImportErrorSafe("injected transport failure")
            return original_upload(*args, **kwargs)

        with mock.patch.object(cf_import, "Target", return_value=remote):
            self.call(cf_import.check)
            remote.upload = fail_before_commit
            with self.assertRaisesRegex(cf_import.ImportErrorSafe, "transport failure"):
                self.call(cf_import.apply, exclusive=True)
            self.assertEqual(len(remote.files), 1)
            status = self.call(cf_import.status)["plan"]
            self.assertEqual(status["status"], "running")
            self.assertEqual(status["actions"]["add"]["done"], 1)
            remote.upload = original_upload
            self.call(cf_import.apply, exclusive=True)
            self.assertEqual(len(remote.files), 2)

        (self.source / "three.txt").write_bytes(b"three")
        with mock.patch.object(cf_import, "Target", return_value=remote):
            self.call(cf_import.check)

            def fail_after_commit(*args, **kwargs):
                original_upload(*args, **kwargs)
                raise cf_import.ImportErrorSafe("response lost after commit")

            remote.upload = fail_after_commit
            with self.assertRaisesRegex(cf_import.ImportErrorSafe, "response lost"):
                self.call(cf_import.apply, exclusive=True)
            remote.upload = original_upload
            with self.assertRaisesRegex(cf_import.ImportErrorSafe, "repository changed"):
                self.call(cf_import.apply, exclusive=True)

    def test_filestash_source_listing_and_streamed_read(self):
        data = "Filestash 来源".encode()
        calls = []

        class Session:
            def request(self, method, url, **kwargs):
                calls.append((method, url, kwargs["headers"]["Authorization"]))
                parsed = urlparse(url)
                path = parse_qs(parsed.query)["path"][0]
                if parsed.path.endswith("/ls") and path in ("/archive", "/archive/"):
                    return FakeResponse(200, {"status": "ok", "results": [
                        {"name": "子目录", "type": "directory", "time": 1}]})
                if parsed.path.endswith("/ls") and path == "/archive/子目录/":
                    return FakeResponse(200, {"status": "ok", "results": [
                        {"name": "记录.txt", "type": "file", "time": 2, "size": len(data)}]})
                if parsed.path.endswith("/cat") and path == "/archive/子目录/记录.txt":
                    return FakeResponse(200, payload=data)
                raise AssertionError((method, url))

        config = {"source_path": "/archive", "filestash_url": "http://filestash.invalid",
                  "filestash_token_file": str(self.token)}
        source = cf_import.FilestashSource(config, Session())
        entries = list(source.entries())
        self.assertEqual(entries[-1], ("子目录/记录.txt", "file", len(data), 2_000_000))
        output = io.BytesIO()
        digest = source.copy_file("子目录/记录.txt", len(data), 2_000_000, output)
        self.assertEqual(output.getvalue(), data)
        self.assertEqual(digest, hashlib.sha256(data).hexdigest())
        self.assertTrue(all(authorization == "Bearer test-token" for _, _, authorization in calls))

    def test_upload_streams_multipart_without_buffering_file_in_request(self):
        payload = b"z" * (cf_import.CHUNK + 3)
        captured = {}

        class Session:
            def request(self, method, url, **kwargs):
                captured["method"] = method
                captured["headers"] = kwargs["headers"]
                import requests
                captured["prepared_headers"] = requests.Session().prepare_request(
                    requests.Request(method, url, data=kwargs["data"], headers=kwargs["headers"])).headers
                captured["body"] = b"".join(kwargs["data"])
                return FakeResponse(200)

        config = {"server": "http://cloudfile.invalid", "repo": "00000000-0000-0000-0000-000000000001",
                  "token_file": str(self.token), "fileserver_origin": "http://files.invalid"}
        target = cf_import.Target(config, Session())
        target.link = lambda *_: "http://files.invalid/upload-api/signed"
        target.upload("/目录/文件.txt", io.BytesIO(payload), len(payload), replace=False)
        self.assertEqual(captured["method"], "POST")
        self.assertEqual(int(captured["headers"]["Content-Length"]), len(captured["body"]))
        self.assertNotIn("Transfer-Encoding", captured["prepared_headers"])
        self.assertIn(b'filename="\xe6\x96\x87\xe4\xbb\xb6.txt"', captured["body"])
        self.assertIn(payload, captured["body"])


if __name__ == "__main__":
    unittest.main()
