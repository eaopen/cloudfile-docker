"""v0.6: fresh-install default uses one mount and auto-local per library.

Read-only tests. Never starts containers, creates libraries or modifies data.
Existing .env files are deliberately not consulted or changed.
"""
import json
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1] / "deploy" / "compose"


class StorageDefaultTests(unittest.TestCase):
    def test_fresh_install_template_selects_overlay(self):
        env = (ROOT / ".env.example").read_text()
        self.assertIn("COMPOSE_FILE=docker-compose.yml:docker-compose.auto-library-storage.yml", env)
        self.assertIn("CF_LIBRARY_STORAGE_HOST_DIR=./data/libraries", env)
        self.assertTrue((ROOT / "docker-compose.auto-library-storage.yml").is_file())
        # This is the only template switch. Existing persisted .env values are
        # not rewritten just because a new version of .env.example ships.

    @unittest.skipUnless(shutil.which("docker"), "Docker Compose CLI not installed")
    def test_merged_new_install_compose_contract(self):
        proc = subprocess.run(
            ["docker", "compose", "--env-file", ".env.example", "config", "--format", "json"],
            cwd=ROOT, capture_output=True, text=True, timeout=30, check=False)
        self.assertEqual(0, proc.returncode, proc.stderr[-1000:])
        data = json.loads(proc.stdout)
        server = data["services"]["cloudfile"]
        worker = data["services"]["cf-worker"]
        for process in (server, worker):
            self.assertEqual("multiple", process["environment"]["SEAF_SERVER_STORAGE_TYPE"])
            self.assertEqual("true", str(process["environment"]["CF_ENABLE_S3_STORAGE"]).lower())
        classes = json.loads(server["environment"]["CF_STORAGE_CLASSES_JSON"])
        self.assertEqual(["legacy-default", "auto-local"], [c["storage_id"] for c in classes])
        self.assertTrue(classes[0]["is_default"])
        self.assertFalse(classes[1]["is_default"])
        self.assertTrue(classes[1]["is_auto"])
        parent = "/shared/seafile/library-storage"
        legacy = "/shared/seafile/seafile-data"
        for kind in ("fs", "commits", "blocks"):
            self.assertEqual({"backend": "fs", "dir": legacy}, classes[0][kind])
            self.assertEqual({"backend": "fs", "dir": parent}, classes[1][kind])
        for process in (server, worker):
            mounts = [v for v in process["volumes"] if v["target"] == parent]
            self.assertEqual(1, len(mounts), "one parent mount per process")
            self.assertEqual("rw", mounts[0].get("mode", "rw"))
        self.assertEqual(False, str(server["environment"]["CF_ENABLE_CHECKOUT"]).lower() == "true")


if __name__ == "__main__":
    unittest.main()
