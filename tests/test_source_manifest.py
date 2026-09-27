import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


BUILD_DIR = Path(__file__).resolve().parents[1] / "build" / "seafile_14.0"
SCRIPT = BUILD_DIR / "source_manifest.py"
SPEC = importlib.util.spec_from_file_location("source_manifest", SCRIPT)
SOURCE_MANIFEST = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SOURCE_MANIFEST)

OVERRIDE_SCRIPT = BUILD_DIR / "source_override.py"
OVERRIDE_SPEC = importlib.util.spec_from_file_location("source_override", OVERRIDE_SCRIPT)
SOURCE_OVERRIDE = importlib.util.module_from_spec(OVERRIDE_SPEC)
OVERRIDE_SPEC.loader.exec_module(SOURCE_OVERRIDE)


class SourceManifestTest(unittest.TestCase):
    def test_build_script_fails_closed_and_supports_pinned_local_sources(self):
        script = (BUILD_DIR / "seafile-build.sh").read_text(encoding="utf-8")

        self.assertIn("set -euo pipefail", script)
        self.assertIn("CLOUDFILE_SERVER_SOURCE", script)
        self.assertIn("CLOUDFILE_HUB_SOURCE", script)

    def test_local_image_builder_is_fail_closed_and_labels_source_pins(self):
        script = (BUILD_DIR / "build-local-image.sh").read_text(encoding="utf-8")

        self.assertIn("set -euo pipefail", script)
        self.assertIn("com.cloudfile.source.seafile-server", script)
        self.assertIn("com.cloudfile.source.seahub", script)
        self.assertNotIn("docker push", script)

    def test_release_manifest_is_valid_and_pins_cloudfile_sources(self):
        manifest = SOURCE_MANIFEST.load_manifest(BUILD_DIR / "release.json")

        self.assertEqual(manifest["product_version"], "v0.2")
        self.assertEqual(manifest["seafile_version"], "14.0.8")
        self.assertEqual(
            manifest["sources"]["seahub"]["url"],
            "https://github.com/eaopen/cloudfile-hub.git",
        )
        self.assertRegex(manifest["sources"]["seahub"]["ref"], r"^[0-9a-f]{40}$")
        self.assertEqual(
            manifest["sources"]["seafile-server"]["url"],
            "https://github.com/eaopen/cloudfile-server.git",
        )

    def test_incomplete_source_set_is_rejected(self):
        manifest = json.loads((BUILD_DIR / "release.json").read_text(encoding="utf-8"))
        del manifest["sources"]["seahub"]

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "release.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(ValueError):
                SOURCE_MANIFEST.load_manifest(path)


class SourceOverrideTest(unittest.TestCase):
    def create_checkout(self, directory):
        source = Path(directory) / "source"
        source.mkdir()
        subprocess.run(("git", "init", "-q", str(source)), check=True)
        subprocess.run(("git", "-C", str(source), "config", "user.name", "CloudFile Test"), check=True)
        subprocess.run(("git", "-C", str(source), "config", "user.email", "cloudfile-test@example.invalid"), check=True)
        (source / "README.md").write_text("fixture\n", encoding="utf-8")
        subprocess.run(("git", "-C", str(source), "add", "README.md"), check=True)
        subprocess.run(("git", "-C", str(source), "commit", "-qm", "fixture"), check=True)
        commit = subprocess.run(
            ("git", "-C", str(source), "rev-parse", "HEAD"),
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        return source, commit

    def test_accepts_clean_checkout_at_exact_release_pin(self):
        with tempfile.TemporaryDirectory() as directory:
            source, commit = self.create_checkout(directory)

            self.assertEqual(SOURCE_OVERRIDE.validate_override(source, commit), source.resolve())

    def test_rejects_dirty_checkout(self):
        with tempfile.TemporaryDirectory() as directory:
            source, commit = self.create_checkout(directory)
            (source / "README.md").write_text("changed\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "clean worktree"):
                SOURCE_OVERRIDE.validate_override(source, commit)

    def test_rejects_checkout_at_different_commit(self):
        with tempfile.TemporaryDirectory() as directory:
            source, _ = self.create_checkout(directory)

            with self.assertRaisesRegex(ValueError, "does not match release pin"):
                SOURCE_OVERRIDE.validate_override(source, "0" * 40)


if __name__ == "__main__":
    unittest.main()
