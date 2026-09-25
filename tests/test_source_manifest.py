import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


BUILD_DIR = Path(__file__).resolve().parents[1] / "build" / "seafile_14.0"
SCRIPT = BUILD_DIR / "source_manifest.py"
SPEC = importlib.util.spec_from_file_location("source_manifest", SCRIPT)
SOURCE_MANIFEST = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SOURCE_MANIFEST)


class SourceManifestTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
