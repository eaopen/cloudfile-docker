"""Offline safety checks. Synthetic bytes are NOT full Seafile restore acceptance."""
import argparse
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "migrate"))
import cf_recovery


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.compose = self.root / "compose"
        for name in ("data/db", "data/seafile", "data/minio", "data/libraries/repo-a/storage/blocks"):
            (self.compose / name).mkdir(parents=True)
        (self.compose / "docker-compose.yml").write_text("services: {}")
        (self.compose / "data/db/sql.ibd").write_bytes(b"db-data")
        (self.compose / "data/seafile/blocks").write_bytes(b"block-v1")
        (self.compose / "data/minio/object").write_bytes(b"blob")
        (self.compose / "data/libraries/repo-a/storage/blocks/part").write_bytes(b"managed-library-block")
        (self.compose / ".env").write_text(
            "PRIVATE_KEY=hidden\nCF_LIBRARY_STORAGE=auto\nCF_LIBRARY_STORAGE_HOST_DIR=./data/libraries\n")
        self.snapshot = self.root / "backup"
        self.restore = self.root / "restore"

    def args(self):
        return argparse.Namespace(compose_root=str(self.compose), output=str(self.snapshot))

    def test_backup_verify_restore_and_hash_protection(self):
        with mock.patch.object(cf_recovery, "stopped") as guard:
            cf_recovery.backup(self.args())
            guard.assert_called_once()
        report = cf_recovery.check_manifest(self.snapshot)
        self.assertTrue(report["files"])
        cf_recovery.restore(argparse.Namespace(snapshot=str(self.snapshot),
                                               destination=str(self.restore)))
        self.assertEqual(b"db-data", (self.restore / "data/db/sql.ibd").read_bytes())
        self.assertEqual(b"block-v1", (self.restore / "data/seafile/blocks").read_bytes())
        self.assertTrue(report["managed_local"])
        self.assertEqual(b"managed-library-block",
                         (self.restore / "data/libraries/repo-a/storage/blocks/part").read_bytes())
        self.assertTrue((self.restore / ".env").is_file())
        with self.assertRaises(cf_recovery.RecoveryError):
            cf_recovery.restore(argparse.Namespace(snapshot=str(self.snapshot),
                                                   destination=str(self.restore)))
        (self.snapshot / "data/db/sql.ibd").write_bytes(b"tampered")
        with self.assertRaisesRegex(cf_recovery.RecoveryError, "checksums"):
            cf_recovery.check_manifest(self.snapshot)

    def test_missing_required_and_symlink_refused(self):
        (self.compose / "data/seafile/escape").symlink_to(self.compose / ".env")
        with mock.patch.object(cf_recovery, "stopped"):
            with self.assertRaisesRegex(cf_recovery.RecoveryError, "symbolic"):
                cf_recovery.backup(self.args())

    def test_nondefault_managed_root_refuses_incomplete_backup(self):
        (self.compose / ".env").write_text(
            "CF_LIBRARY_STORAGE=auto\nCF_LIBRARY_STORAGE_HOST_DIR=/outside/libraries\n")
        with mock.patch.object(cf_recovery, "stopped"):
            with self.assertRaisesRegex(cf_recovery.RecoveryError, "external CF_LIBRARY_STORAGE_HOST_DIR"):
                cf_recovery.backup(self.args())
        self.assertFalse(self.snapshot.exists())

    def test_persisted_nondefault_auto_root_refuses_backup(self):
        conf = self.compose / "data/seafile/seafile/conf/seafile.conf"
        conf.parent.mkdir(parents=True)
        conf.write_text("[cloudfile_v2]\nauto_local_root=/outside/libraries\n")
        with mock.patch.object(cf_recovery, "stopped"):
            with self.assertRaisesRegex(cf_recovery.RecoveryError, "nondefault V2"):
                cf_recovery.backup(self.args())

    def test_missing_auto_managed_root_refuses_backup(self):
        import shutil
        shutil.rmtree(self.compose / "data/libraries")
        with mock.patch.object(cf_recovery, "stopped"):
            with self.assertRaisesRegex(cf_recovery.RecoveryError, "managed library root"):
                cf_recovery.backup(self.args())

    def test_legacy_ce_can_snapshot_without_auto_root(self):
        import shutil
        shutil.rmtree(self.compose / "data/libraries")
        (self.compose / ".env").write_text("PRIVATE_KEY=hidden\n")
        with mock.patch.object(cf_recovery, "stopped"):
            cf_recovery.backup(self.args())
        self.assertFalse(cf_recovery.check_manifest(self.snapshot)["managed_local"])

    def test_running_or_unverifiable_compose_refused(self):
        with mock.patch.object(cf_recovery.subprocess, "run") as runner:
            runner.return_value.returncode = 0
            runner.return_value.stdout = "active-container-id\n"
            with self.assertRaisesRegex(cf_recovery.RecoveryError, "running"):
                cf_recovery.stopped(self.compose)
            runner.return_value.stdout = ""
            runner.return_value.returncode = 1
            with self.assertRaisesRegex(cf_recovery.RecoveryError, "running"):
                cf_recovery.stopped(self.compose)

    def test_source_destination_overlap_refused(self):
        with self.assertRaisesRegex(cf_recovery.RecoveryError, "overlap"):
            cf_recovery.disjoint(self.compose, self.compose / "nested")


if __name__ == "__main__":
    unittest.main()
