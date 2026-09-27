import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

path = Path(__file__).resolve().parents[1] / 'scripts/scripts_14.0/cloudfile-jit-worker.py'
spec = importlib.util.spec_from_file_location('jit_worker', path)
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


class JITWorkerConfigurationTests(unittest.TestCase):
    def test_disabled_and_string_flags_do_not_start_provisioning(self):
        for oidc, jit in [(False, True), (True, False), ('true', True), (True, 'true')]:
            with self.subTest(oidc=oidc, jit=jit), self.assertRaises(ValueError):
                worker.require_enabled(SimpleNamespace(CLOUDFILE_OIDC_ENABLED=oidc, CLOUDFILE_OIDC_JIT_ENABLED=jit))

    def test_invalid_poll_and_lease_limits_fail_before_loading_runtime(self):
        for arguments in [['--poll-seconds', '0'], ['--poll-seconds', '31'],
                          ['--lease-seconds', '0'], ['--lease-seconds', '301']]:
            with patch.object(worker, 'bootstrap') as bootstrap, patch('sys.stderr'):
                self.assertEqual(worker.main(arguments), 1)
                bootstrap.assert_not_called()

    def test_logout_worker_uses_its_own_flag_without_requiring_jit(self):
        settings = SimpleNamespace(CLOUDFILE_OIDC_ENABLED=True, CLOUDFILE_OIDC_BACKCHANNEL_ENABLED=True,
            CLOUDFILE_OIDC_JIT_ENABLED=False)
        worker.require_enabled(settings, logout=True)
        for value in (False, 'true'):
            settings.CLOUDFILE_OIDC_BACKCHANNEL_ENABLED = value
            with self.assertRaises(ValueError):
                worker.require_enabled(settings, logout=True)


if __name__ == '__main__':
    unittest.main()
