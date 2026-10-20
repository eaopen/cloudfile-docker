"""Current V2 fresh-install default uses one mount and native per-library routing.

Read-only tests. Never starts containers, creates libraries or modifies data.
Existing .env files are deliberately not consulted or changed.
"""
import json
import os
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
        self.assertIn("CF_LIBRARY_STORAGE=auto", env)
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
            self.assertEqual("auto", process["environment"]["CF_LIBRARY_STORAGE"])
            self.assertEqual("/shared/seafile/seafile-data", process["environment"]["SEAFILE_DATA_DIR"])
            self.assertEqual("/shared/seafile/conf", process["environment"]["SEAFILE_CENTRAL_CONF_DIR"])
            self.assertEqual("false", str(process["environment"]["CF_ENABLE_S3_STORAGE"]).lower())
        self.assertEqual("", server["environment"]["SEAF_SERVER_STORAGE_TYPE"])
        self.assertEqual("", server["environment"]["CF_STORAGE_CLASSES_JSON"])
        parent = "/shared/seafile/library-storage"
        for process in (server, worker):
            mounts = [v for v in process["volumes"] if v["target"] == parent]
            self.assertEqual(1, len(mounts), "one parent mount per process")
            self.assertEqual("rw", mounts[0].get("mode", "rw"))
            self.assertFalse(mounts[0]["bind"]["create_host_path"])
        self.assertEqual(False, str(server["environment"]["CF_ENABLE_CHECKOUT"]).lower() == "true")


    @unittest.skipUnless(shutil.which("docker"), "Docker Compose CLI not installed")
    def test_base_compose_exports_native_runtime_paths_without_storage_overlay(self):
        proc = subprocess.run(
            ["docker", "compose", "--env-file", ".env.example", "-f", "docker-compose.yml", "config", "--format", "json"],
            cwd=ROOT, capture_output=True, text=True, timeout=30, check=True,
            env={**os.environ, "CF_LIBRARY_STORAGE": "", "SEAFILE_DATA_DIR": "/stale-data",
                 "SEAFILE_CENTRAL_CONF_DIR": "/stale-conf"})
        services = json.loads(proc.stdout)["services"]
        for name in ("cloudfile", "cf-worker"):
            environment = services[name]["environment"]
            self.assertEqual("/shared/seafile/seafile-data", environment["SEAFILE_DATA_DIR"])
            self.assertEqual("/shared/seafile/conf", environment["SEAFILE_CENTRAL_CONF_DIR"])
            self.assertEqual("", environment["CF_LIBRARY_STORAGE"])

    @unittest.skipUnless(shutil.which("docker"), "Docker Compose CLI not installed")
    def test_policy_flags_reach_both_processes(self):
        # .env values used to be silently dropped by Compose before bootstrap.
        for value in ("false", "true"):
            result = subprocess.run(
                ["docker", "compose", "--env-file", ".env.example", "config", "--format", "json"],
                cwd=ROOT, capture_output=True, text=True, timeout=30, check=True,
                env={**os.environ, "CLOUDFILE_AUTHORIZATION_ENABLED": value,
                     "CLOUDFILE_TRANSFER_ENABLED": value})
            data = json.loads(result.stdout)
            for name in ("cloudfile", "cf-worker"):
                environment = data["services"][name]["environment"]
                for key in ("CLOUDFILE_AUTHORIZATION_ENABLED", "CLOUDFILE_TRANSFER_ENABLED"):
                    self.assertEqual(value, str(environment[key]).lower())


if __name__ == "__main__":
    unittest.main()
