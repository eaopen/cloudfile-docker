"""Standalone offline Seafile library tests: no DB, Docker or CloudFile service."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "ops" / "seafile-library-offline.py"
spec = importlib.util.spec_from_file_location("offline", SCRIPT)
offline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(offline)

REPO = "f2af601c-8f44-4eb1-ac10-0402783d142d"


class OfflineLibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.top = Path(self.tmp.name)
        self.native = self.top / "seafile-data"
        self.managed = self.top / "libraries"
        self.native.mkdir()
        self.managed.mkdir()
        self.export_parent = self.top / "exports"
        self.export_parent.mkdir()
        self.fsck = self.top / "fake-fsck"
        self.fsck.write_text("""#!/usr/bin/env python3
from pathlib import Path
import sys
args = sys.argv[1:]
get = lambda k: args[args.index(k) + 1]
repo = args[-1]
data = Path(get('-d'))
assert (data / 'storage/commits' / repo).is_dir()
assert 'cloudfile_v2' not in (Path(get('-F')) / 'seafile.conf').read_text()
path = Path(get('--export')) / (repo[:8] + '_test_owner')
path.mkdir()
(path / 'file.txt').write_text('Hello Seafile!')
""")
        self.fsck.chmod(0o700)

    def layout(self, root, *, key=None):
        base = root / key if key else root
        for kind in offline.KINDS:
            (base / "storage" / kind / REPO).mkdir(parents=True)
        (base / "storage/commits" / REPO / "ab").mkdir()
        (base / "storage/commits" / REPO / "ab" / "cd").write_bytes(b"commit")

    def locate(self):
        return offline.find_library(REPO, str(self.native), str(self.managed))

    def test_native_and_managed_layout_without_cloudfile_database(self):
        self.layout(self.native)
        self.assertEqual("seafile-native", self.locate()["backend"])
        import shutil
        shutil.rmtree(self.native / "storage")
        self.layout(self.managed, key="project-a")
        self.assertEqual("auto-local", self.locate()["backend"])
        self.assertEqual("project-a", self.locate()["repo_key"])

    def test_explicit_missing_managed_mount_never_falls_back(self):
        self.layout(self.native)
        missing = self.top / "missing-mount"
        with self.assertRaisesRegex(offline.LibraryError, "storage root is not accessible"):
            offline.find_library(REPO, str(self.native), str(missing))
        # A CE-only operator can omit the managed root instead of asking the
        # tool to guess whether an explicitly named mount is missing.
        self.assertEqual("seafile-native",
                         offline.find_library(REPO, str(self.native), None)["backend"])

    def test_cli_inspect_native_ce_without_managed_root(self):
        import json
        self.layout(self.native)
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "inspect", "--repo-id", REPO,
             "--seafile-data", str(self.native)],
            capture_output=True, text=True)
        self.assertEqual(0, proc.returncode, proc.stderr)
        self.assertEqual("seafile-native", json.loads(proc.stdout)["backend"])

    def test_ambiguous_and_missing_repo_rejected(self):
        with self.assertRaisesRegex(offline.LibraryError, "not found"):
            self.locate()
        self.layout(self.managed, key="project-a")
        self.layout(self.native)
        with self.assertRaisesRegex(offline.LibraryError, "ambiguous"):
            self.locate()
        with self.assertRaisesRegex(offline.LibraryError, "complete UUID"):
            offline.find_library("not-a-repo", str(self.native), str(self.managed))

    def test_symlinks_never_rename_the_object_source(self):
        target = self.top / "elsewhere"
        (target / "storage/commits" / REPO).mkdir(parents=True)
        (self.managed / "project-a").symlink_to(target)
        with self.assertRaisesRegex(offline.LibraryError, "not found"):
            self.locate()
        (self.managed / "project-a").unlink()
        alt = self.top / "managed-link"
        alt.symlink_to(self.managed)
        with self.assertRaisesRegex(offline.LibraryError, "parent must not be a symbolic"):
            offline.find_library(REPO, str(self.native), str(alt))

    def test_explicit_single_repo_export_and_verify(self):
        self.layout(self.managed, key="custom-project")
        output = self.export_parent / "repo-one"
        cmd = ["export", "--repo-id", REPO, "--seafile-data", str(self.native),
               "--library-root", str(self.managed), "--seaf-fsck", str(self.fsck),
               "--output-dir", str(output)]
        run = subprocess.run([sys.executable, str(SCRIPT)] + cmd,
                             capture_output=True, text=True)
        self.assertEqual(0, run.returncode, run.stderr)
        self.assertTrue((output / (REPO[:8] + "_test_owner") / "file.txt").exists())
        self.assertFalse((self.managed / "custom-project/tmpfiles").exists())
        self.assertEqual(b"commit", (self.managed / "custom-project/storage/commits" / REPO / "ab/cd").read_bytes())
        with self.assertRaisesRegex(offline.LibraryError, "exists"):
            offline.export_library(type("A", (), dict(
                repo_id=REPO, seafile_data=str(self.native),
                library_root=str(self.managed), seaf_fsck=str(self.fsck),
                output_dir=str(output))))
        summary = offline.verify_export(type("A", (), dict(repo_id=REPO, output_dir=str(output), hash=True)))
        self.assertEqual(1, summary["file_count"])
        self.assertEqual(len(b"Hello Seafile!"), summary["total_bytes"])
        self.assertEqual(64, len(summary["tree_sha256"]))

    def test_inspect_does_not_export_or_copy_all_libraries(self):
        self.layout(self.native)
        run = subprocess.run([sys.executable, str(SCRIPT), "inspect",
                              "--seafile-data", str(self.native),
                              "--library-root", str(self.managed)], capture_output=True)
        self.assertNotEqual(0, run.returncode)  # exact UUID is mandatory
        self.assertEqual([], list(self.export_parent.iterdir()))
        self.assertEqual("seafile-native", self.locate()["backend"])
        self.assertEqual([], list(self.export_parent.iterdir()))


if __name__ == "__main__":
    unittest.main()
