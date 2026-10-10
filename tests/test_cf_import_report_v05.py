"""V05-03 operator report: no hidden deletes, no blind retry of unknown writes."""
import argparse
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import cf_import
from test_cf_import import FakeTarget


class ImportReportTests(unittest.TestCase):
    def test_incremental_report_and_no_auto_delete(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            source = root / "source"
            source.mkdir()
            (source / "one.txt").write_bytes(b"one")
            job = root / "job"
            token = root / "token"
            token.write_text("secret")
            create_args = argparse.Namespace(
                job_dir=str(job), source="local://" + str(source),
                repo="00000000-0000-0000-0000-000000000001", target="/Import",
                server="http://example.invalid", token_file=str(token),
                fileserver_origin=None, filestash_url=None, filestash_token_file=None)
            with contextlib.redirect_stdout(io.StringIO()):
                cf_import.create(create_args)

            def call(operation, **kwargs):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    operation(argparse.Namespace(job_dir=str(job), **kwargs))
                return json.loads(output.getvalue())

            remote = FakeTarget()
            with mock.patch.object(cf_import, "Target", return_value=remote):
                call(cf_import.check)
                plan = call(cf_import.report)
                self.assertEqual("cloudfile.import-report.v1", plan["schema"])
                self.assertEqual(1, plan["pending_operations"])
                self.assertFalse(plan["operator_attention"])
                self.assertNotIn("secret", json.dumps(plan))
                call(cf_import.apply, exclusive=True)
                self.assertEqual(0, call(cf_import.report)["pending_operations"])
                (source / "one.txt").unlink()
                call(cf_import.check)
                deletion = call(cf_import.report)
                self.assertEqual(1, deletion["delete_candidates_retained"])
                self.assertEqual(0, deletion["pending_operations"])
                call(cf_import.apply, exclusive=True)
                self.assertIn("/Import/one.txt", remote.files)

    def test_running_state_needs_review(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            source = root / "source"
            source.mkdir()
            (source / "file").write_bytes(b"one")
            token = root / "token"
            token.write_text("secret")
            job = root / "job"
            args = argparse.Namespace(job_dir=str(job), source="local://" + str(source),
                repo="00000000-0000-0000-0000-000000000001", target="/Import",
                server="http://example.invalid", token_file=str(token),
                fileserver_origin=None, filestash_url=None, filestash_token_file=None)
            with contextlib.redirect_stdout(io.StringIO()):
                cf_import.create(args)
            db = cf_import.connect(job)
            cf_import.set_meta(db, "plan_status", "running")
            db.commit()
            db.close()
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                cf_import.report(argparse.Namespace(job_dir=str(job)))
            self.assertTrue(json.loads(output.getvalue())["operator_attention"])


if __name__ == "__main__":
    unittest.main()
