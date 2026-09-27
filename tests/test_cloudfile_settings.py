import importlib.util
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock, patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "scripts_14.0" / "cloudfile.py"
SPEC = importlib.util.spec_from_file_location("cloudfile_settings", SCRIPT)
CLOUDFILE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CLOUDFILE)


class CloudFileSettingsTest(unittest.TestCase):
    def test_policy_worker_hooks_preserve_compose_and_remove_only_owned_block(self):
        environment = {"CLOUDFILE_POLICY_WORKER_HOOKS": "true"}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "gunicorn.conf.py"
            original = "bind = '127.0.0.1:8000'\ndef post_worker_init(worker):\n    worker.append('original-init')\ndef worker_exit(server, worker):\n    worker.append('original-exit')\n"
            path.write_text(original, encoding="utf-8")
            self.assertTrue(CLOUDFILE.write_policy_worker_hooks(path, environment))
            rendered = path.read_text(encoding="utf-8")
            self.assertFalse(CLOUDFILE.write_policy_worker_hooks(path, environment))
            self.assertEqual(path.read_text(encoding="utf-8"), rendered)
            fixture = ModuleType("cloudfile_extensions.authorization.gunicorn")
            fixture.post_worker_init = lambda worker: worker.append("cf-init")
            fixture.worker_exit = lambda server, worker: worker.append("cf-exit")
            with patch.dict("sys.modules", {fixture.__name__: fixture}):
                namespace = {}
                exec(compile(rendered, str(path), "exec"), namespace)
                events = []
                namespace["post_worker_init"](events)
                namespace["worker_exit"](None, events)
                self.assertEqual(events, ["original-init", "cf-init", "original-exit", "cf-exit"])
            self.assertTrue(CLOUDFILE.write_policy_worker_hooks(path, {}))
            self.assertEqual(path.read_text(encoding="utf-8"), original)
            self.assertFalse(CLOUDFILE.write_policy_worker_hooks(path, {}))

    def test_policy_exit_cleanup_runs_after_existing_hook_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "gunicorn.conf.py"
            path.write_text("def worker_exit(server, worker):\n    raise RuntimeError('fixture')\n", encoding="utf-8")
            CLOUDFILE.write_policy_worker_hooks(path, {"CLOUDFILE_POLICY_WORKER_HOOKS": "true"})
            fixture = ModuleType("cloudfile_extensions.authorization.gunicorn")
            fixture.worker_exit = Mock()
            with patch.dict("sys.modules", {fixture.__name__: fixture}):
                namespace = {}
                exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), namespace)
                with self.assertRaises(RuntimeError):
                    namespace["worker_exit"]("server", "worker")
                fixture.worker_exit.assert_called_once_with("server", "worker")

    def test_policy_hook_malformed_markers_preserve_original_file(self):
        for original in ("# BEGIN CLOUDFILE POLICY WORKER HOOKS\n",
                         "# END CLOUDFILE POLICY WORKER HOOKS\n",
                         "# BEGIN CLOUDFILE POLICY WORKER HOOKS\n# BEGIN CLOUDFILE POLICY WORKER HOOKS\n# END CLOUDFILE POLICY WORKER HOOKS\n"):
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "gunicorn.conf.py"
                path.write_text(original, encoding="utf-8")
                with self.assertRaises(ValueError):
                    CLOUDFILE.write_policy_worker_hooks(path, {"CLOUDFILE_POLICY_WORKER_HOOKS": "true"})
                self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_write_is_idempotent_and_preserves_local_settings(self):
        environment = {
            "CLOUDFILE_EXTENSION_APPS": "project_extension",
            "CLOUDFILE_EXTENSION_URLCONFS_JSON": '{"project":"project_extension.urls"}',
            "CLOUDFILE_CAPABILITIES_JSON": '{"search.resources":{"enabled":true,"provider":"meilisearch"}}',
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

    def test_preset_does_not_claim_completed_oidc(self):
        namespace = {}
        exec(CLOUDFILE.render_settings({
            "CLOUDFILE_AUTHENTIK_ENABLED": "true",
            "CLOUDFILE_AUTHENTIK_URL": "https://auth.example.com",
            "CLOUDFILE_AUTHENTIK_CLIENT_ID": "cloudfile",
            "CLOUDFILE_AUTHENTIK_CLIENT_SECRET": "example-only",
            "SEAFILE_SERVER_HOSTNAME": "files.example.com",
        }), namespace)
        self.assertTrue(namespace["ENABLE_OAUTH"])
        self.assertFalse(namespace["OAUTH_CREATE_UNKNOWN_USER"])
        self.assertFalse(namespace["OAUTH_ACTIVATE_USER_AFTER_CREATION"])
        self.assertFalse(namespace["CLOUDFILE_CAPABILITIES"]["auth.oidc"]["enabled"])

    def test_webdav_requires_explicit_deployment_flag(self):
        for value, expected in ((None, False), ("true", True), ("false", False)):
            environment = {} if value is None else {"CLOUDFILE_WEBDAV_ENABLED": value}
            namespace = {}
            exec(CLOUDFILE.render_settings(environment), namespace)
            self.assertEqual(namespace["CLOUDFILE_WEBDAV_SERVICE_ENABLED"], expected)
            self.assertEqual(namespace["CLOUDFILE_CAPABILITIES"]["protocol.webdav"]["enabled"], expected)

    def test_local_edit_routes_require_explicit_deployment_flag(self):
        for value, expected in ((None, False), ("true", True), ("false", False)):
            environment = {} if value is None else {"CLOUDFILE_LOCAL_EDIT_ENABLED": value}
            namespace = {}
            exec(CLOUDFILE.render_settings(environment), namespace)
            self.assertEqual(namespace["CLOUDFILE_LOCAL_EDIT_ENABLED"], expected)

    def test_authorization_routes_require_explicit_deployment_flag(self):
        policy = '{"database":{},"redis":{}}'
        for value, expected in ((None, False), ("true", True), ("false", False)):
            environment = {} if value is None else {
                "CLOUDFILE_AUTHORIZATION_ENABLED": value,
                "CLOUDFILE_POLICY_CONFIG_JSON": policy,
                "CLOUDFILE_POLICY_WORKER_HOOKS": "true",
            }
            namespace = {}
            exec(CLOUDFILE.render_settings(environment), namespace)
            self.assertEqual(namespace["CLOUDFILE_AUTHORIZATION_ENABLED"], expected)

    def test_enabled_authorization_rejects_incomplete_or_ambiguous_policy_config(self):
        with self.assertRaisesRegex(ValueError, "policy config and worker hooks"):
            CLOUDFILE.render_settings({"CLOUDFILE_AUTHORIZATION_ENABLED": "true"})
        with self.assertRaisesRegex(ValueError, "policy config and worker hooks"):
            CLOUDFILE.render_settings({
                "CLOUDFILE_AUTHORIZATION_ENABLED": "true",
                "CLOUDFILE_POLICY_CONFIG_JSON": "{}",
            })
        with self.assertRaisesRegex(ValueError, "duplicate"):
            CLOUDFILE.render_settings({
                "CLOUDFILE_POLICY_CONFIG_JSON": '{"database":{},"database":{}}',
            })
        with self.assertRaisesRegex(ValueError, "strict JSON"):
            CLOUDFILE.render_settings({"CLOUDFILE_POLICY_CONFIG_JSON": '{"port":NaN}'})

    def test_deployment_cannot_claim_reserved_domain(self):
        for domain in CLOUDFILE.RESERVED_DOMAINS:
            with self.assertRaises(ValueError):
                CLOUDFILE.render_settings({"CLOUDFILE_EXTENSION_URLCONFS_JSON": '{"' + domain + '":"adapter.urls"}'})


if __name__ == "__main__":
    unittest.main()
