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
    def test_retired_policy_configuration_is_rejected_without_echoing_values(self):
        for key in CLOUDFILE.RETIRED_POLICY_SETTINGS:
            with self.subTest(key=key):
                with self.assertRaises(ValueError) as error:
                    CLOUDFILE.render_settings({key: 'secret-example'})
                self.assertIn(key, str(error.exception))
                self.assertNotIn('secret-example', str(error.exception))
        rendered = CLOUDFILE.render_settings({})
        self.assertNotIn('cloudfile_extensions.authorization.gunicorn', rendered)
        self.assertNotIn('CLOUDFILE_POLICY_CONFIG =', rendered)



    def test_v2_removes_only_legacy_worker_hooks_without_starting_policy_host(self):
        # A stale policy config/hook must not load a historical SchemaRunner.
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "gunicorn.conf.py"
            original = "def post_worker_init(worker):\n    worker.append('native')\n"
            path.write_text(original + "# BEGIN CLOUDFILE POLICY WORKER HOOKS\nraise AssertionError('retired')\n# END CLOUDFILE POLICY WORKER HOOKS\n")
            env = {"CLOUDFILE_POLICY_WORKER_HOOKS": "true"}
            CLOUDFILE.write_policy_worker_hooks(path, env, v2=True)
            self.assertEqual(path.read_text(), original)
            namespace = {}; exec(path.read_text(), namespace)
            events = []; namespace['post_worker_init'](events)
            self.assertEqual(events, ['native'])
            self.assertEqual(env, {"CLOUDFILE_POLICY_WORKER_HOOKS": "true"})



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


    def test_native_block_follows_legacy_defaults_and_preserves_both_apps(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "seahub_settings.py"
            path.write_text(CLOUDFILE.render_settings({}) +
                            "EXTRA_INSTALLED_APPS = ['cloudfile_ext']\n")
            CLOUDFILE.write_settings(path, {})
            namespace = {}
            exec(path.read_text(), namespace)
            self.assertEqual(namespace['EXTRA_INSTALLED_APPS'],
                             ['cloudfile_ext', 'cloudfile_extensions'])
            self.assertFalse(CLOUDFILE.write_settings(path, {}))

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

    def test_permission_runtime_middleware_is_installed(self):
        # P0-5: a permission-runtime failure must surface as 503, so the
        # response-shaping middleware has to be part of the generated settings.
        # EXTRA_MIDDLEWARE is appended to MIDDLEWARE by load_local_settings, so
        # it must be a list, not a bare string.
        rendered = CLOUDFILE.render_settings({})
        self.assertIn("EXTRA_MIDDLEWARE = ['cloudfile_extensions.permission_middleware."
            "CloudFilePermissionMiddleware']", rendered)

    def test_authentik_redirect_defaults_to_the_deployment_protocol(self):
        # Same default as bootstrap.get_proto(): an unset SEAFILE_SERVER_PROTOCOL
        # means HTTP. Generating an HTTPS redirect for an HTTP entry is what made
        # the Hub mark sessionid/csrftoken Secure on Etech's HTTP deployment.
        # The public entry's scheme is declared by the deployment, so an HTTP
        # redirect does not additionally require CLOUDFILE_AUTHENTIK_ALLOW_INSECURE
        # (that flag stays on the IdP-facing URLs).
        environment = {
            "CLOUDFILE_AUTHENTIK_ENABLED": "true",
            "CLOUDFILE_AUTHENTIK_URL": "https://auth.example.com",
            "CLOUDFILE_AUTHENTIK_CLIENT_ID": "cloudfile",
            "CLOUDFILE_AUTHENTIK_CLIENT_SECRET": "secret",
            "SEAFILE_SERVER_HOSTNAME": "files.example.com",
        }
        self.assertIn("OAUTH_REDIRECT_URL = 'http://files.example.com/oauth/callback/'",
            CLOUDFILE.render_settings(environment))
        with_letsencrypt = dict(environment, SEAFILE_SERVER_LETSENCRYPT="true")
        self.assertIn("OAUTH_REDIRECT_URL = 'https://files.example.com/oauth/callback/'",
            CLOUDFILE.render_settings(with_letsencrypt))
        explicit = dict(environment, SEAFILE_SERVER_PROTOCOL="https")
        self.assertIn("OAUTH_REDIRECT_URL = 'https://files.example.com/oauth/callback/'",
            CLOUDFILE.render_settings(explicit))

    def test_http_redirect_is_rejected_on_an_https_deployment(self):
        environment = {
            "CLOUDFILE_AUTHENTIK_ENABLED": "true",
            "CLOUDFILE_AUTHENTIK_URL": "https://auth.example.com",
            "CLOUDFILE_AUTHENTIK_CLIENT_ID": "cloudfile",
            "CLOUDFILE_AUTHENTIK_CLIENT_SECRET": "secret",
            "SEAFILE_SERVER_PROTOCOL": "https",
            "CLOUDFILE_AUTHENTIK_REDIRECT_URL": "http://files.example.com/oauth/callback/",
        }
        with self.assertRaises(ValueError):
            CLOUDFILE.render_settings(environment)

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
            # The generated redirect now follows the deployment protocol like
            # bootstrap.get_proto() does, so an HTTPS entry must say so.
            "SEAFILE_SERVER_PROTOCOL": "https",
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









    def test_deployment_cannot_claim_reserved_domain(self):
        for domain in CLOUDFILE.RESERVED_DOMAINS:
            with self.assertRaises(ValueError):
                CLOUDFILE.render_settings({"CLOUDFILE_EXTENSION_URLCONFS_JSON": '{"' + domain + '":"adapter.urls"}'})


class OIDCSettingsTest(unittest.TestCase):



    def test_managed_group_settings_follow_runtime_environment(self):
        namespace = {}
        exec(CLOUDFILE.render_settings({
            "CF_SSO_GROUP_OWNER": "owner@example.com",
            "CF_SSO_MAX_REMOVAL_RATIO": "0.25",
        }), namespace)
        self.assertEqual(namespace["CF_SSO_GROUP_OWNER"], "owner@example.com")
        self.assertEqual(namespace["CF_SSO_MAX_REMOVAL_RATIO"], "0.25")







    def test_identity_domain_cannot_be_replaced_by_project_urlconf(self):
        with self.assertRaises(ValueError):
            CLOUDFILE.render_settings({"CLOUDFILE_EXTENSION_URLCONFS_JSON":
                                      '{"identity":"project.urls"}'})


if __name__ == "__main__":
    unittest.main()
