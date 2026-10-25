"""Cheap startup-hook checks; no Docker image, database or network required."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import subprocess
import unittest
from unittest.mock import Mock

FILE = (Path(__file__).resolve().parents[1] / 'scripts' /
        'scripts_cf14.0' / 'cloudfile_admin_startup.py')
spec = importlib.util.spec_from_file_location('admin_sync_startup', FILE)
admin_sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(admin_sync)


class StartupSyncHookTests(unittest.TestCase):
    def test_disabled_never_spawns_an_process(self):
        spawn = Mock(side_effect=AssertionError('disabled'))
        self.assertEqual(admin_sync.run_provider_admin_sync(
            '/seahub.sh', '/seahub/manage.py', enabled=False, runner=spawn),
            'SKIPPED')
        spawn.assert_not_called()

    def test_enabled_spawns_once_with_bounded_timeout(self):
        spawn = Mock(return_value=SimpleNamespace(
            returncode=0, stdout='CF_ADMIN_SYNC APPLIED added=1 removed=0 unchanged=0\n'))
        self.assertEqual(admin_sync.run_provider_admin_sync(
            '/seahub.sh', '/seahub/manage.py', enabled=True, runner=spawn), 'APPLIED')
        args, kw = spawn.call_args
        self.assertEqual(args[0][-2:], ['/seahub/manage.py', 'cf_sync_provider_admins'])
        self.assertEqual(kw['timeout'], 30)
        self.assertFalse(kw['check'])
        self.assertEqual(spawn.call_count, 1)

    def test_failed_provider_never_aborts_container_startup(self):
        self.assertEqual(admin_sync.run_provider_admin_sync(
            '/seahub.sh', '/seahub/manage.py', enabled=True,
            runner=Mock(return_value=SimpleNamespace(returncode=1, stdout=''))),
            'FAILED')
        self.assertEqual(admin_sync.run_provider_admin_sync(
            '/seahub.sh', '/seahub/manage.py', enabled=True,
            runner=Mock(side_effect=subprocess.TimeoutExpired('sync', 30))),
            'FAILED')

    def test_zero_exit_without_applied_receipt_is_failure_not_false_success(self):
        for stdout in ('', 'CF_ADMIN_SYNC SKIPPED (not configured)',
                       'unrelated successful output'):
            with self.subTest(stdout=stdout):
                self.assertEqual(admin_sync.run_provider_admin_sync(
                    '/seahub.sh', '/seahub/manage.py', enabled=True,
                    runner=Mock(return_value=SimpleNamespace(
                        returncode=0, stdout=stdout))), 'FAILED')

    def test_enterprise_default_admin_compatibility_remains_opt_in(self):
        root = Path(__file__).resolve().parents[1]
        env = (root / 'deploy/compose/.env.enterprise-sso.example').read_text()
        self.assertIn('CF_PROVIDER_ADMIN_STARTUP_SYNC_ENABLED=false', env)
        # The example must not hardcode a customer administrator account: the
        # expected-account assertion is an operator opt-in in their own config.
        self.assertIn('CF_PROVIDER_ADMIN_EXPECTED_ACCOUNT=', env)
        self.assertNotIn('CF_PROVIDER_ADMIN_EXPECTED_ACCOUNT=admin', env)
        self.assertIn('CF_DIRECTORY_PROVIDER=external', env)
        self.assertIn('CF_DIRECTORY_AUDIENCE=eap-directory', env)

    def test_nonroot_command_is_one_safely_quoted_shell_command(self):
        spawn = Mock(return_value=SimpleNamespace(returncode=0, stdout='CF_ADMIN_SYNC APPLIED added=1 removed=0 unchanged=0'))
        self.assertEqual(admin_sync.run_provider_admin_sync(
            '/seahub.sh', '/seahub/manage.py', enabled=True,
            non_root=True, runner=spawn), 'APPLIED')
        args = spawn.call_args.args[0]
        self.assertEqual(args[:4], ['su', '-p', 'seafile', '-c'])
        self.assertIn('cf_sync_provider_admins', args[-1])


if __name__ == '__main__':
    unittest.main()
