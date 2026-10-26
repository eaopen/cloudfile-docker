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

# Include the optional search worker when asserting its generated configuration.
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
            ["docker", "compose", "--profile", "search", "--env-file", ".env.example", "config", "--format", "json"],
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
            # Compose JSON may omit explicit false from the normalized form.
            # The deployment overlay must still declare it for safe mounts.
            self.assertFalse(mounts[0].get("bind", {}).get("create_host_path", False))
        self.assertEqual(2, (ROOT / "docker-compose.auto-library-storage.yml")
                         .read_text().count("create_host_path: false"))
        self.assertEqual(False, str(server["environment"]["CF_ENABLE_CHECKOUT"]).lower() == "true")


    @unittest.skipUnless(shutil.which("docker"), "Docker Compose CLI not installed")
    def test_base_compose_exports_native_runtime_paths_without_storage_overlay(self):
        proc = subprocess.run(
            ["docker", "compose", "--profile", "search", "--env-file", ".env.example", "-f", "docker-compose.yml", "config", "--format", "json"],
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
    def test_retired_policy_flags_never_reach_processes(self):
        # 2690dcc 起七类旧授权机制退出，Compose 不再向应用和 worker 注入这些变量。
        # 显式写进 .env 也不得复活：否则"配置了但被静默丢弃"和"配置真的生效"两种
        # 状态会再次混淆，运维无法从环境判断当前权限链走哪条。
        retired = (
            "CLOUDFILE_AUTHORIZATION_ENABLED",
            "CLOUDFILE_TRANSFER_ENABLED",
            "CLOUDFILE_POLICY_CONFIG_JSON",
            "CLOUDFILE_POLICY_WORKER_HOOKS",
        )
        result = subprocess.run(
            ["docker", "compose", "--profile", "search", "--env-file", ".env.example", "config", "--format", "json"],
            cwd=ROOT, capture_output=True, text=True, timeout=30, check=True,
            env={**os.environ, **{key: "true" for key in retired}})
        data = json.loads(result.stdout)
        for name in ("cloudfile", "cf-worker"):
            environment = data["services"][name]["environment"]
            for key in retired:
                self.assertNotIn(key, environment)


if __name__ == "__main__":
    unittest.main()
