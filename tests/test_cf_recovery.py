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
        for name in ("data/db", "data/seafile", "data/minio"):
            (self.compose / name).mkdir(parents=True)
        (self.compose / "docker-compose.yml").write_text("services: {}")
        (self.compose / "data/db/sql.ibd").write_bytes(b"db-data")
        (self.compose / "data/seafile/blocks").write_bytes(b"block-v1")
        (self.compose / "data/minio/object").write_bytes(b"blob")
        (self.compose / ".env").write_text("PRIVATE_KEY=hidden\n")
        self.snapshot = self.root / "backup"
        self.restore = self.root / "restore"

    def args(self):
        return argparse.Namespace(compose_root=str(self.compose), output=str(self.snapshot),
                                  legacy_ce_only=True)

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

    def test_bulk_backup_requires_explicit_legacy_ce_scope(self):
        args = self.args()
        args.legacy_ce_only = False
        with mock.patch.object(cf_recovery, "stopped") as guard:
            with self.assertRaisesRegex(cf_recovery.RecoveryError, "--legacy-ce-only"):
                cf_recovery.backup(args)
        guard.assert_not_called()
        self.assertFalse(self.snapshot.exists())

    def test_bulk_backup_rejects_auto_local_mode(self):
        (self.compose / ".env").write_text(
            "PRIVATE_KEY=hidden\nCF_LIBRARY_STORAGE=auto\n")
        with mock.patch.object(cf_recovery, "stopped") as guard:
            with self.assertRaisesRegex(cf_recovery.RecoveryError, "auto-local"):
                cf_recovery.backup(self.args())
        guard.assert_not_called()

    def test_bulk_backup_rejects_managed_library_objects(self):
        directory = self.compose / "data/libraries/custom-key/storage/commits"
        directory.mkdir(parents=True)
        with mock.patch.object(cf_recovery, "stopped") as guard:
            with self.assertRaisesRegex(cf_recovery.RecoveryError, "per-library objects"):
                cf_recovery.backup(self.args())
        guard.assert_not_called()

    def test_bulk_backup_rejects_persisted_v2_storage_config(self):
        conf = self.compose / "data/seafile/seafile/conf/seafile.conf"
        conf.parent.mkdir(parents=True)
        conf.write_text("[cloudfile_v2]\nauto_local_root=/shared/seafile/library-storage\n")
        with mock.patch.object(cf_recovery, "stopped") as guard:
            with self.assertRaisesRegex(cf_recovery.RecoveryError, "per-library root"):
                cf_recovery.backup(self.args())
        guard.assert_not_called()

    def test_bulk_backup_rejects_persisted_s3_storage_class(self):
        conf = self.compose / "data/seafile/seafile/conf/seafile.conf"
        conf.parent.mkdir(parents=True)
        conf.write_text("[storage]\\nenable_storage_classes=true\\n")
        with mock.patch.object(cf_recovery, "stopped") as guard:
            with self.assertRaisesRegex(cf_recovery.RecoveryError, "storage classes"):
                cf_recovery.backup(self.args())
        guard.assert_not_called()

    def test_bulk_backup_rejects_s3_environment(self):
        (self.compose / ".env").write_text("CF_ENABLE_S3_STORAGE=true\\n")
        with mock.patch.object(cf_recovery, "stopped") as guard:
            with self.assertRaisesRegex(cf_recovery.RecoveryError, "S3/multiple"):
                cf_recovery.backup(self.args())
        guard.assert_not_called()

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
