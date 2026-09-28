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
    def test_backchannel_flag_requires_enabled_oidc_and_defaults_off(self):
        namespace = {}
        exec(CLOUDFILE.render_settings({}), namespace)
        self.assertIs(namespace['CLOUDFILE_OIDC_BACKCHANNEL_ENABLED'], False)
        with self.assertRaisesRegex(ValueError, 'backchannel'):
            CLOUDFILE.render_settings({'CLOUDFILE_OIDC_BACKCHANNEL_ENABLED': 'true'})

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

    def test_transfer_routes_require_explicit_deployment_flag(self):
        policy = '{"database":{},"redis":{}}'
        for value, expected in ((None, False), ("true", True), ("false", False)):
            environment = {} if value is None else {
                "CLOUDFILE_TRANSFER_ENABLED": value,
                "ENABLE_GO_FILESERVER": "true",
                "CLOUDFILE_POLICY_CONFIG_JSON": policy,
                "CLOUDFILE_POLICY_WORKER_HOOKS": "true",
            }
            namespace = {}
            exec(CLOUDFILE.render_settings(environment), namespace)
            self.assertEqual(namespace["CLOUDFILE_TRANSFER_ENABLED"], expected)

    def test_enabled_transfer_rejects_missing_policy_worker(self):
        with self.assertRaisesRegex(ValueError, "authorization or transfer"):
            CLOUDFILE.render_settings({"CLOUDFILE_TRANSFER_ENABLED": "true"})

    def test_enabled_transfer_rejects_native_c_fileserver(self):
        environment = {
            "CLOUDFILE_TRANSFER_ENABLED": "true",
            "CLOUDFILE_POLICY_CONFIG_JSON": '{"database":{},"redis":{}}',
            "CLOUDFILE_POLICY_WORKER_HOOKS": "true",
        }
        for value in (None, "false"):
            with self.subTest(value=value):
                if value is not None:
                    environment["ENABLE_GO_FILESERVER"] = value
                with self.assertRaisesRegex(ValueError, "ENABLE_GO_FILESERVER=true"):
                    CLOUDFILE.render_settings(environment)

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


class OIDCSettingsTest(unittest.TestCase):
    @staticmethod
    def environment():
        import json
        return {"CLOUDFILE_OIDC_ENABLED": "true", "CLOUDFILE_POLICY_WORKER_HOOKS": "true",
            "CLOUDFILE_POLICY_CONFIG_JSON": '{"provider":"fixture"}',
            "CLOUDFILE_OIDC_CONFIG_JSON": json.dumps(dict(
                issuer="https://idp.example/application/o/cloudfile/", client_id="cloudfile",
                client_secret="fixture-client-secret",
                redirect_uri="https://files.example/api/v2.1/cloudfile/extensions/identity/v1/callback/",
                authorization_url="https://idp.example/authorize/", token_url="https://idp.example/token/",
                userinfo_url="https://idp.example/userinfo/", jwks_url="https://idp.example/jwks/"))}

    def test_audit_query_requires_explicit_prerequisites_and_fixed_secret(self):
        environment = self.environment()
        environment.update(CLOUDFILE_AUTHORIZATION_ENABLED="true",
            CLOUDFILE_AUDIT_QUERY_ENABLED="true",
            CLOUDFILE_AUDIT_CURSOR_SECRET="fixed-audit-secret-" + "x" * 32)
        namespace = {}
        exec(CLOUDFILE.render_settings(environment), namespace)
        self.assertTrue(namespace["CLOUDFILE_AUDIT_QUERY_ENABLED"])
        self.assertEqual(namespace["CLOUDFILE_AUDIT_CURSOR_SECRET"],
                         environment["CLOUDFILE_AUDIT_CURSOR_SECRET"].encode("utf-8"))
        for key in ("CLOUDFILE_AUTHORIZATION_ENABLED", "CLOUDFILE_AUDIT_CURSOR_SECRET"):
            invalid = dict(environment)
            del invalid[key]
            with self.subTest(key=key), self.assertRaises(ValueError):
                CLOUDFILE.render_settings(invalid)
        invalid = dict(environment, CLOUDFILE_AUDIT_CURSOR_SECRET="short")
        with self.assertRaises(ValueError):
            CLOUDFILE.render_settings(invalid)

    def test_managed_group_settings_follow_runtime_environment(self):
        namespace = {}
        exec(CLOUDFILE.render_settings({
            "CF_SSO_GROUP_OWNER": "owner@example.com",
            "CF_SSO_MAX_REMOVAL_RATIO": "0.25",
        }), namespace)
        self.assertEqual(namespace["CF_SSO_GROUP_OWNER"], "owner@example.com")
        self.assertEqual(namespace["CF_SSO_MAX_REMOVAL_RATIO"], "0.25")

    def test_explicit_oidc_renders_primitives_without_claiming_capability(self):
        namespace = {}
        exec(CLOUDFILE.render_settings(self.environment()), namespace)
        self.assertTrue(namespace["CLOUDFILE_OIDC_ENABLED"])
        self.assertFalse(namespace["CLOUDFILE_OIDC_JIT_ENABLED"])
        self.assertEqual(namespace["CLOUDFILE_OIDC_CONFIG"]["client_id"], "cloudfile")
        self.assertFalse(namespace["CLOUDFILE_CAPABILITIES"]["auth.oidc"]["enabled"])
        self.assertNotIn("ENABLE_OAUTH", namespace)
        self.assertFalse(namespace["CLOUDFILE_LOCAL_EDIT_ENABLED"])

    def test_missing_runtime_or_worker_hooks_rejected(self):
        for key in ("CLOUDFILE_POLICY_CONFIG_JSON", "CLOUDFILE_OIDC_CONFIG_JSON",
                    "CLOUDFILE_POLICY_WORKER_HOOKS"):
            environment = self.environment()
            del environment[key]
            with self.subTest(key=key), self.assertRaises(ValueError):
                CLOUDFILE.render_settings(environment)

    def test_legacy_oauth_and_jit_without_host_are_rejected(self):
        environment = self.environment()
        environment.update(CLOUDFILE_AUTHENTIK_ENABLED="true",
            CLOUDFILE_AUTHENTIK_URL="https://idp.example",
            CLOUDFILE_AUTHENTIK_CLIENT_ID="fixture", CLOUDFILE_AUTHENTIK_CLIENT_SECRET="fixture",
            CLOUDFILE_AUTHENTIK_REDIRECT_URL="https://files.example/oauth/callback/")
        with self.assertRaises(ValueError):
            CLOUDFILE.render_settings(environment)
        with self.assertRaises(ValueError):
            CLOUDFILE.render_settings({"CLOUDFILE_OIDC_JIT_ENABLED": "true"})

    def test_oidc_json_and_endpoint_errors_are_redacted(self):
        import json
        for raw in ('{"client_secret":"fixture-client-secret","client_secret":"duplicate"}',
                    '{"secret":NaN}', '[]'):
            environment = self.environment()
            environment["CLOUDFILE_OIDC_CONFIG_JSON"] = raw
            with self.subTest(raw=raw), self.assertRaises(ValueError) as error:
                CLOUDFILE.render_settings(environment)
            self.assertNotIn("fixture-client-secret", str(error.exception))
        for uri in ("http://idp.example", "https://user:fixture-client-secret@idp.example",
                    "https://idp.example/#fragment", "https://idp.example:invalid", "https://idp.example/\n"):
            environment = self.environment()
            value = json.loads(environment["CLOUDFILE_OIDC_CONFIG_JSON"])
            value["issuer"] = uri
            environment["CLOUDFILE_OIDC_CONFIG_JSON"] = json.dumps(value)
            with self.subTest(uri=uri), self.assertRaises(ValueError) as error:
                CLOUDFILE.render_settings(environment)
            self.assertNotIn("fixture-client-secret", str(error.exception))

    def test_identity_domain_cannot_be_replaced_by_project_urlconf(self):
        with self.assertRaises(ValueError):
            CLOUDFILE.render_settings({"CLOUDFILE_EXTENSION_URLCONFS_JSON":
                                      '{"identity":"project.urls"}'})


if __name__ == "__main__":
    unittest.main()
