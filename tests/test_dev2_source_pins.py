"""Standalone source-lock contract tests; no external repositories or network."""
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[1]
CHECK = ROOT / "tools/verify-v2-source-pins.py"


def invoke(*args):
    return subprocess.run(
        [sys.executable, str(CHECK), *map(str, args)],
        capture_output=True, text=True, check=False,
    )


def init_repo(folder):
    folder.mkdir()
    subprocess.run(["git", "-C", str(folder), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(folder), "config", "user.email", "tests@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(folder), "config", "user.name", "CloudFile Test"], check=True)
    # Equal trees committed in the same second can have identical SHAs.
    # Distinguish repositories so a cross-repository pin swap is detectable.
    (folder / "README").write_text(f"baseline: {folder.name}", encoding="utf-8")
    subprocess.run(["git", "-C", str(folder), "add", "README"], check=True)
    subprocess.run(["git", "-C", str(folder), "commit", "-qm", "baseline"], check=True)
    return subprocess.check_output(["git", "-C", str(folder), "rev-parse", "HEAD"], text=True).strip()


class PinContractTest(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.workspace = Path(self.tmp.name)
        self.server = init_repo(self.workspace / "cloudfile-server")
        self.hub = init_repo(self.workspace / "cloudfile-hub")
        self.assertNotEqual(self.server, self.hub)
        self.manifest = self.workspace / "release.yaml"

    def manifest_for(self, server=None, hub=None):
        self.manifest.write_text(
            "forks:\n  cloudfile_server:\n    ref: " + (server or self.server) +
            "\n  cloudfile_hub:\n    ref: " + (hub or self.hub) + "\n",
            encoding="utf-8",
        )

    def check(self):
        return invoke("--manifest", self.manifest, "--workspace", self.workspace)

    def test_exact_git_heads_are_accepted(self):
        self.manifest_for()
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(self.hub, result.stdout)
        self.assertIn(self.server, result.stdout)

    def test_changed_or_branch_ref_is_rejected(self):
        self.manifest_for(server=self.hub)
        result = self.check()
        self.assertEqual(result.returncode, 1)
        self.assertIn("does not match pinned", result.stderr)
        self.manifest_for(server="dev2")
        self.assertEqual(self.check().returncode, 1)

    def test_missing_checkout_fails_closed(self):
        self.manifest_for()
        (self.workspace / "cloudfile-server" / ".git").rename(
            self.workspace / "cloudfile-server" / ".git-disabled"
        )
        result = self.check()
        self.assertEqual(result.returncode, 1)
        self.assertIn("unavailable", result.stderr)


if __name__ == "__main__":
    unittest.main()
