import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "scripts_14.0" / "cloudfile.py"
SPEC = importlib.util.spec_from_file_location("cloudfile_settings", SCRIPT)
CLOUDFILE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CLOUDFILE)


class CloudFileSettingsTest(unittest.TestCase):
    def test_write_is_idempotent_and_preserves_local_settings(self):
        environment = {
            "CLOUDFILE_EXTENSION_APPS": "project_extension",
            "CLOUDFILE_EXTENSION_URLCONFS_JSON": '{"project":"project_extension.urls"}',
            "CLOUDFILE_CAPABILITIES_JSON": '{"search.fulltext":{"enabled":true,"provider":"meilisearch"}}',
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "seahub_settings.py"
            path.write_text("SITE_NAME = 'Example'\n", encoding="utf-8")

            self.assertTrue(CLOUDFILE.write_settings(path, environment))
            first = path.read_text(encoding="utf-8")
            self.assertFalse(CLOUDFILE.write_settings(path, environment))
            self.assertEqual(path.read_text(encoding="utf-8"), first)
            self.assertIn("SITE_NAME = 'Example'", first)
            self.assertIn("project_extension.urls", first)
            self.assertIn("meilisearch", first)
            self.assertIn("protocol.webdav", first)

    def test_existing_block_is_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "seahub_settings.py"
            path.write_text(
                "before = True\n"
                f"{CLOUDFILE.BEGIN_MARKER}\nold = True\n{CLOUDFILE.END_MARKER}\n"
                "after = True\n",
                encoding="utf-8",
            )

            CLOUDFILE.write_settings(path, {})
            rendered = path.read_text(encoding="utf-8")
            self.assertNotIn("old = True", rendered)
            self.assertIn("before = True", rendered)
            self.assertIn("after = True", rendered)

    def test_invalid_configuration_is_rejected(self):
        with self.assertRaises(ValueError):
            CLOUDFILE.render_settings({"CLOUDFILE_EXTENSION_APPS": "../bad"})
        with self.assertRaises(ValueError):
            CLOUDFILE.render_settings({"CLOUDFILE_EXTENSION_URLCONFS_JSON": "[]"})
        with self.assertRaises(ValueError):
            CLOUDFILE.render_settings({
                "CLOUDFILE_EXTENSION_URLCONFS_JSON": '{"Bad Name":"project.urls"}',
            })
        with self.assertRaises(ValueError):
            CLOUDFILE.render_settings({"CLOUDFILE_CAPABILITIES_JSON": "[]"})
        with self.assertRaises(ValueError):
            CLOUDFILE.render_settings({
                "CLOUDFILE_CAPABILITIES_JSON": '{"auth.oidc":{"enabled":true,"secret":"bad"}}',
            })

    def test_authentik_preset_uses_stable_subject_identity(self):
        rendered = CLOUDFILE.render_settings({
            "CLOUDFILE_AUTHENTIK_ENABLED": "true",
            "CLOUDFILE_AUTHENTIK_URL": "https://auth.example.com/",
            "CLOUDFILE_AUTHENTIK_CLIENT_ID": "cloudfile",
            "CLOUDFILE_AUTHENTIK_CLIENT_SECRET": "secret",
            "SEAFILE_SERVER_PROTOCOL": "https",
            "SEAFILE_SERVER_HOSTNAME": "files.example.com",
        })

        self.assertIn("OAUTH_PROVIDER = 'authentik-oauth'", rendered)
        self.assertIn("'sub': (True, 'uid')", rendered)
        self.assertIn("https://auth.example.com/application/o/userinfo/", rendered)
        self.assertIn("https://files.example.com/oauth/callback/", rendered)
        self.assertIn("'provider': 'authentik'", rendered)

    def test_authentik_requires_https_by_default(self):
        with self.assertRaises(ValueError):
            CLOUDFILE.render_settings({
                "CLOUDFILE_AUTHENTIK_ENABLED": "true",
                "CLOUDFILE_AUTHENTIK_URL": "http://auth.example.com",
                "CLOUDFILE_AUTHENTIK_CLIENT_ID": "cloudfile",
                "CLOUDFILE_AUTHENTIK_CLIENT_SECRET": "secret",
                "SEAFILE_SERVER_HOSTNAME": "files.example.com",
            })


if __name__ == "__main__":
    unittest.main()
