"""Installed-byte and source-pin checks before local Docker image assembly."""

# Keep regression tests runnable on dev162 Python 3.6 as well as CI Python.

import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest


BUILD = Path(__file__).resolve().parents[1] / "build" / "seafile_14.0"
sys.path.insert(0, str(BUILD))
from package_provenance import (RECORD_NAME, REQUIRED_FILES, capture_sources,
                                package_digest, verify_package, write_provenance)
from source_manifest import load_manifest


class PackageProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.manifest = load_manifest(BUILD.parents[1] / "tests/fixtures/source-lock.json")
        self.manifest_path = self.root / "release.json"
        self.manifest_path.write_text(json.dumps(self.manifest))
        self.package = self.root / "package"
        self.package.mkdir()
        for name in REQUIRED_FILES:
            path = self.package / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"installed fixture bytes")
        (self.package / "seafile/lib/core-link.so").symlink_to("libcloudfile_acl.so.1")
        self.captured = dict(schema=1, manifest=self.manifest,
            source_commits={name: value["ref"] for name, value in self.manifest["sources"].items()})

    def stamp(self):
        return write_provenance(self.package, self.captured, self.manifest_path)

    def test_complete_package_survives_copy_and_is_bound_to_actual_bytes(self):
        record = self.stamp()
        copy = self.root / "copied"
        shutil.copytree(self.package, copy, symlinks=True)
        self.assertEqual(verify_package(copy, self.manifest_path), record)
        (copy / REQUIRED_FILES[0]).write_bytes(b"different native bytes")
        with self.assertRaisesRegex(ValueError, "content differs"):
            verify_package(copy, self.manifest_path)
        self.assertEqual(verify_package(self.package, self.manifest_path), record)

    def test_missing_provenance_or_required_binary_cannot_be_labeled(self):
        with self.assertRaisesRegex(ValueError, "lacks build provenance"):
            verify_package(self.package, self.manifest_path)
        (self.package / REQUIRED_FILES[0]).unlink()
        with self.assertRaisesRegex(ValueError, "required installed file"):
            self.stamp()
        self.assertFalse((self.package / RECORD_NAME).exists())

    def test_changed_manifest_cannot_relabel_old_package(self):
        self.stamp()
        self.manifest["sources"]["seahub"]["ref"] = "b" * 40
        self.manifest_path.write_text(json.dumps(self.manifest))
        with self.assertRaisesRegex(ValueError, "differs from the release manifest"):
            verify_package(self.package, self.manifest_path)

    def test_execute_modes_added_files_and_symlink_targets_are_measured(self):
        before = package_digest(self.package)
        native = self.package / REQUIRED_FILES[0]
        native.chmod(native.stat().st_mode ^ 0o100)
        self.assertNotEqual(package_digest(self.package), before)
        self.stamp()
        link = self.package / "seafile/lib/core-link.so"
        link.unlink()
        link.symlink_to("other-target")
        with self.assertRaisesRegex(ValueError, "content differs"):
            verify_package(self.package, self.manifest_path)
        link.unlink()
        link.symlink_to("libcloudfile_acl.so.1")
        (self.package / "extra.py").write_text("unrecorded")
        with self.assertRaisesRegex(ValueError, "content differs"):
            verify_package(self.package, self.manifest_path)

    def test_bad_source_set_symlink_stamp_and_restamping_are_rejected(self):
        self.captured["source_commits"]["seahub"] = "b" * 40
        with self.assertRaisesRegex(ValueError, "incorrect source commit"):
            self.stamp()
        self.captured["source_commits"]["seahub"] = self.manifest["sources"]["seahub"]["ref"]
        self.stamp()
        with self.assertRaisesRegex(ValueError, "rebuild rather than restamp"):
            self.stamp()
        target = self.package / RECORD_NAME
        renamed = self.root / "record.json"
        target.rename(renamed)
        target.symlink_to(renamed)
        with self.assertRaisesRegex(ValueError, "lacks build provenance"):
            verify_package(self.package, self.manifest_path)

    def test_source_capture_requires_clean_exact_immutable_checkouts(self):
        sources = self.root / "sources"
        sources.mkdir()
        source = sources / "template"
        subprocess.run(["git", "init", "-q", str(source)], check=True)
        subprocess.run(["git", "-C", str(source), "config", "user.name", "CloudFile Test"], check=True)
        subprocess.run(["git", "-C", str(source), "config", "user.email", "test@example.invalid"], check=True)
        (source / "code.py").write_text("fixture")
        subprocess.run(["git", "-C", str(source), "add", "."], check=True)
        subprocess.run(["git", "-C", str(source), "commit", "-qm", "fixture"], check=True)
        pin = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], universal_newlines=True).strip()
        for name in self.manifest["sources"]:
            shutil.copytree(source, sources / name)
            self.manifest["sources"][name]["ref"] = pin
        self.manifest_path.write_text(json.dumps(self.manifest))
        captured = capture_sources(self.manifest_path, sources)
        self.assertEqual(set(captured["source_commits"].values()), {pin})
        (sources / "seahub" / "untracked.py").write_text("unexpected")
        with self.assertRaisesRegex(ValueError, "untracked files"):
            capture_sources(self.manifest_path, sources)
        (sources / "seahub" / "untracked.py").unlink()
        (sources / "seahub" / "code.py").write_text("changed")
        with self.assertRaisesRegex(ValueError, "modifications"):
            capture_sources(self.manifest_path, sources)
        self.manifest["sources"]["libsearpc"]["ref"] = "v3.3-latest"
        self.manifest_path.write_text(json.dumps(self.manifest))
        with self.assertRaisesRegex(ValueError, "immutable"):
            capture_sources(self.manifest_path, sources)

    def test_failed_focused_tests_reject_receipt(self):
        self.stamp()
        receipt = {"schema": 2, "lock": self.manifest, "tests": {}}
        self.manifest_path.write_text(json.dumps(receipt))
        with self.assertRaisesRegex(ValueError, "successful focused test evidence"):
            verify_package(self.package, self.manifest_path)
        for name in ("local_storage", "objstore"):
            receipt["tests"][name] = {"status": "passed", "command": "fixture", "log_sha256": "a" * 64}
        self.manifest_path.write_text(json.dumps(receipt))
        verify_package(self.package, self.manifest_path)
        receipt["tests"]["objstore"]["status"] = "failed"
        self.manifest_path.write_text(json.dumps(receipt))
        with self.assertRaisesRegex(ValueError, "successful focused test evidence"):
            verify_package(self.package, self.manifest_path)

    def test_missing_web_console_entry_point_is_rejected(self):
        (self.package / "seahub/thirdpart/bin/gunicorn").unlink()
        with self.assertRaisesRegex(ValueError, "gunicorn"):
            self.stamp()


if __name__ == "__main__":
    unittest.main()
