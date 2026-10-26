"""Verify additive configuration and Compose's real interpolation boundary."""
import importlib.util
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

# Include the optional search worker when asserting its generated configuration.
ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("storage_config", ROOT / "tools/ops/storage-class-config.py")
config = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(config)


class StorageClassConfigTests(unittest.TestCase):
    def setUp(self):
        self.env = {"S3_KEY_ID": "access", "S3_SECRET_KEY": 'literal${UNSET}-$-"-\\'}

    def test_add_rustfs_preserves_minio_and_local(self):
        base = config.append_class(config.fresh_classes(), "minio", "existing-minio", self.env)
        before = json.dumps(base)
        classes = config.append_class(base, "rustfs", "rustfs-standard", self.env)
        self.assertEqual(before, json.dumps(base))
        self.assertEqual(base, classes[:-1])
        for kind in config.KINDS:
            self.assertEqual("s3", classes[-1][kind]["backend"])
            self.assertEqual("rustfs:9000", classes[-1][kind]["host"])
        self.assertEqual(1, sum(c.get("is_default", False) for c in classes))

    def test_reject_duplicate_or_invalid_base(self):
        for base in ([], {}, [{"storage_id": "bad"}], config.fresh_classes() * 2):
            with self.assertRaises(ValueError):
                config.append_class(base, "rustfs", "new", self.env)
        with self.assertRaises(ValueError):
            config.append_class(config.fresh_classes(), "rustfs", "legacy-default", self.env)

    def test_explicit_endpoint_and_credentials(self):
        env = dict(self.env, S3_HOST="objects.example.com", S3_USE_HTTPS="true")
        result = config.append_class(config.fresh_classes(), "minio", "external", env)[-1]
        self.assertEqual("objects.example.com", result["blocks"]["host"])
        self.assertTrue(result["blocks"]["use_https"])
        with self.assertRaises(ValueError):
            config.append_class(config.fresh_classes(), "rustfs", "new", {})

    def test_cli_private_file_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "override.json"
            args = ["python3", str(ROOT / "tools/ops/storage-class-config.py"), "--fresh", "--output", str(out)]
            first = subprocess.run(args, env=dict(os.environ, **self.env), capture_output=True)
            self.assertEqual(0, first.returncode, first.stderr)
            self.assertEqual(0o600, out.stat().st_mode & 0o777)
            body = out.read_bytes()
            second = subprocess.run(args, env=dict(os.environ, **self.env), capture_output=True)
            self.assertNotEqual(0, second.returncode)
            self.assertEqual(body, out.read_bytes())

    def test_business_gate_selects_provider(self):
        script = (ROOT / "tools/gates/verify-local.sh").read_text()
        function = re.search(r"cap_storage_env\(\) \{.*?^\}", script, re.S | re.M).group(0)
        for provider in ("rustfs", "minio", "invalid"):
            proc = subprocess.run(["bash", "-c", function + "\ncap_storage_env"],
                                  env=dict(os.environ, CF_STORAGE_TEST_PROVIDER=provider),
                                  capture_output=True, text=True)
            if provider == "invalid":
                self.assertNotEqual(0, proc.returncode)
                continue
            self.assertEqual(0, proc.returncode, proc.stderr)
            value = next(line.split("=", 1)[1] for line in proc.stdout.splitlines()
                         if line.startswith("CF_STORAGE_CLASSES_JSON="))
            classes = json.loads(value)
            self.assertTrue(classes[0]["is_default"])
            self.assertEqual(provider, classes[1]["storage_id"])
            self.assertEqual(provider + ":9000", classes[1]["blocks"]["host"])

    @unittest.skipUnless(shutil.which("docker"), "Docker Compose required")
    def test_compose_interpolation_and_provider_profiles(self):
        classes = config.append_class(config.fresh_classes(), "rustfs", "rustfs-standard", self.env)
        with tempfile.TemporaryDirectory() as tmp:
            override = Path(tmp) / "override.json"
            override.write_text(json.dumps(config.compose_override(classes)))
            base = ["docker", "compose", "--profile", "search", "--env-file", ".env.example", "-f", "docker-compose.yml",
                    "-f", "docker-compose.auto-library-storage.yml", "-f", str(override)]
            for profile, present, absent in (("s3", "rustfs", "minio"), ("minio", "minio", "rustfs")):
                proc = subprocess.run(base + ["--profile", profile, "config", "--format", "json"],
                                      cwd=ROOT / "deploy/compose", capture_output=True, text=True)
                self.assertEqual(0, proc.returncode, proc.stderr)
                services = json.loads(proc.stdout)["services"]
                self.assertIn(present, services)
                self.assertNotIn(absent, services)
                for name in ("cloudfile", "cf-worker"):
                    # `compose config` re-escapes dollars for reusable output;
                    # Docker receives the unescaped environment value.
                    actual = json.loads(services[name]["environment"]["CF_STORAGE_CLASSES_JSON"].replace("$$", "$"))
                    self.assertEqual(classes, actual)


if __name__ == "__main__":
    unittest.main()
