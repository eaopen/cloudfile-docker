"""Execute production cache/provenance shell functions against disposable packages."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build/seafile_14.0"
SCRIPT = ROOT / "build/cloudfile_14.0/cloudfile-build.sh"
sys.path.insert(0, str(BUILD))
from package_provenance import (RECORD_NAME, REQUIRED_FILES, capture_sources,
                                verify_package)


def production_function(name):
    """Select declarations only, leaving all production commands unchanged."""
    found = re.search(r"^function " + re.escape(name) + r"\(\) \{\n.*?^\}",
                      SCRIPT.read_text(), re.MULTILINE | re.DOTALL)
    if found is None:
        raise AssertionError("missing production function: " + name)
    return found.group(0)


class ReceiptCacheTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.current = self.root / "builder"
        self.sources = self.root / "sources"
        self.current.mkdir()
        self.sources.mkdir()
        self.version = "14.0.8-storage-test"
        self.package = self.current / ("seafile-server-" + self.version)
        self.package.mkdir()
        for name in REQUIRED_FILES:
            path = self.package / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"installed fixture bytes")
        lock = json.loads((ROOT / "tests/fixtures/source-lock.json").read_text())
        for name, source in lock["sources"].items():
            path = self.sources / name
            path.mkdir()
            subprocess.run(["git", "init", "-q", str(path)], check=True)
            subprocess.run(["git", "-C", str(path), "-c", "user.name=Cache Test",
                            "-c", "user.email=cache-test@example.invalid", "commit",
                            "--quiet", "--allow-empty", "-m", "fixture source"], check=True)
            source["ref"] = subprocess.check_output(
                ["git", "-C", str(path), "rev-parse", "HEAD"], text=True).strip()
        lock["docker_commit"] = "1" * 40
        self.receipt = self.root / "build-receipt.json"
        self.document = {"schema": 2, "version": self.version, "lock": lock,
                         "image": None, "tests": {}}
        for name in ("local_storage", "objstore"):
            self.document["tests"][name] = {
                "status": "passed", "command": "fixture " + name,
                "log_sha256": hashlib.sha256(name.encode()).hexdigest()}
        self.save_receipt()
        (self.current / "captured-sources.json").write_text(
            json.dumps(capture_sources(self.receipt, self.sources)))
        for name in ("cloudfile-build.sh", "cloudfile-build.py"):
            shutil.copyfile(SCRIPT.parent / name, self.current / name)

    def save_receipt(self):
        self.receipt.write_text(json.dumps(self.document))

    def shell(self, function, jobs="1"):
        declarations = "\n".join(production_function(name) for name in
                                 ("source_fingerprint", "dist_fingerprint", "write_build_info"))
        return subprocess.run(["bash", "-c", "set -euo pipefail\n" + declarations
                               + "\n" + function], capture_output=True, text=True,
                              env={**os.environ, "current_dir": str(self.current),
                                   "repo_root": str(ROOT), "code_path": str(self.sources),
                                   "version": self.version, "receipt": str(self.receipt),
                                   "CF_BUILD_JOBS": jobs})

    def assert_shell_ok(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_matching_pristine_cache_is_verified_then_restamped(self):
        first = self.shell("write_build_info")
        self.assert_shell_ok(first)
        previous = verify_package(self.package, self.receipt)["package_sha256"]
        result = self.shell("write_build_info", jobs="2")
        self.assert_shell_ok(result)
        self.assertIn("jobs: 2\n", (self.package / "cloudfile-build-info.txt").read_text())
        record = verify_package(self.package, self.receipt)
        self.assertEqual(record["manifest"], self.document["lock"])
        self.assertNotEqual(record["package_sha256"], previous)

    def test_modified_cache_bytes_are_rejected_before_provenance_is_removed(self):
        self.assert_shell_ok(self.shell("write_build_info"))
        proof = (self.package / RECORD_NAME).read_bytes()
        info = (self.package / "cloudfile-build-info.txt").read_bytes()
        (self.package / REQUIRED_FILES[0]).write_bytes(b"tampered cached binary")
        result = self.shell("write_build_info", jobs="2")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.package / RECORD_NAME).read_bytes(), proof)
        self.assertEqual((self.package / "cloudfile-build-info.txt").read_bytes(), info)
        with self.assertRaisesRegex(ValueError, "content differs"):
            verify_package(self.package, self.receipt)

    def test_docker_recipe_change_invalidates_dist_with_identical_sources(self):
        sources_before = self.shell("source_fingerprint")
        first = self.shell("dist_fingerprint")
        repeated = self.shell("dist_fingerprint")
        for result in (sources_before, first, repeated):
            self.assert_shell_ok(result)
        self.assertEqual(first.stdout, repeated.stdout)
        self.document["lock"]["docker_commit"] = "2" * 40
        self.save_receipt()
        after = self.shell("dist_fingerprint")
        self.assert_shell_ok(after)
        self.assertEqual(sources_before.stdout, self.shell("source_fingerprint").stdout)
        self.assertNotEqual(first.stdout, after.stdout)
        self.assertRegex(after.stdout.strip(), r"^[0-9a-f]{64}$")

    def test_real_storage_runner_exports_reachable_shared_fixture(self):
        # Keep the actual runner and receipt reader/writer; replace only the
        # C/Go test executables at their process boundary, without compiling.
        runner_dir = self.root / "recipe/build/cloudfile_14.0"
        runner_dir.mkdir(parents=True)
        (runner_dir.parent / "seafile_14.0").symlink_to(BUILD, target_is_directory=True)
        docs = self.root / "recipe/docs/features"
        docs.mkdir(parents=True)
        (docs / "automatic-local-storage-cases.json").symlink_to(
            ROOT / "docs/features/automatic-local-storage-cases.json")
        runner = runner_dir / "run-storage-tests.sh"
        shutil.copyfile(SCRIPT.parent / runner.name, runner)
        server = self.sources / "seafile-server"
        (server / "tests/local_storage").mkdir(parents=True)
        (server / "tests/local_storage/run.sh").write_text(
            'test -s "${CF_AUTO_STORAGE_CASES:?shared fixture missing}"\n'
            'printf "C boundary fixture reachable\\n"\n')
        (server / "fileserver").mkdir()
        binary = self.root / "bin"
        binary.mkdir()
        go = binary / "go"
        go.write_text('#!/bin/bash\nset -euo pipefail\n'
                      'test -s "${CF_AUTO_STORAGE_CASES:?shared fixture missing}"\n'
                      'test "$1" = test\nprintf "Go boundary fixture reachable\\n"\n')
        go.chmod(0o755)
        result = subprocess.run(["bash", str(runner), str(self.receipt), str(server)],
                                capture_output=True, text=True,
                                env={**os.environ, "PATH": str(binary) + os.pathsep + os.environ["PATH"],
                                     "CF_TEST_BIND_MOUNTS": "0", "CF_AUTO_STORAGE_CASES": "/missing"})
        self.assert_shell_ok(result)
        self.assertIn("C boundary fixture reachable", result.stdout)
        self.assertIn("Go boundary fixture reachable", result.stdout)
        receipt = json.loads(self.receipt.read_text())
        for name in ("local_storage", "objstore"):
            self.assertEqual(receipt["tests"][name]["status"], "passed")
            log = runner_dir / "test-results" / (name + ".log")
            self.assertEqual(receipt["tests"][name]["log_sha256"],
                             hashlib.sha256(log.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
