import importlib.util
from pathlib import Path
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

path = Path(__file__).resolve().parents[1] / 'scripts/scripts_14.0/cloudfile-audit-worker.py'
spec = importlib.util.spec_from_file_location('audit_worker', path)
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


class AuditWorkerTests(unittest.TestCase):
    def test_worker_drains_and_closes_host_on_success_and_failure(self):
        for fail in (False, True):
            settings = SimpleNamespace(CLOUDFILE_POLICY_CONFIG={'database': dict(
                host='db', user='user', name='seafile', password='secret')})
            host = SimpleNamespace(deployment=SimpleNamespace(audit_factory=object()))
            hooks = Mock(_host=None)
            hooks.post_worker_init.side_effect = lambda _: setattr(hooks, '_host', host)
            runtime = Mock()
            runtime.__enter__ = Mock(return_value=runtime)
            runtime.__exit__ = Mock(return_value=False)
            if fail:
                runtime.run.side_effect = RuntimeError('sensitive diagnostic')
            background = Mock(return_value=runtime)
            configure_oidc = Mock()
            modules = {}
            for name, attributes in {
                'django': {}, 'django.conf': {'settings': settings},
                'cloudfile_extensions': {},
                'cloudfile_extensions.authorization': {'gunicorn': hooks},
                'cloudfile_extensions.identity': {},
                'cloudfile_extensions.identity.configuration': {'configure_oidc_host': configure_oidc},
                'cloudfile_extensions.events': {},
                'cloudfile_extensions.events.background': {'AuditBackground': background},
                'cloudfile_extensions.events.configuration': {'require_export_configuration': Mock()},
            }.items():
                modules[name] = ModuleType(name)
                modules[name].__dict__.update(attributes)
            with patch.dict('sys.modules', modules), patch.object(worker, 'bootstrap'), \
                    patch.object(worker.signal, 'signal') as signals, patch('sys.stderr') as stderr:
                self.assertEqual(worker.main(['--once']), int(fail))
                hooks.post_worker_init.assert_called_once_with(None)
                configure_oidc.assert_called_once_with(settings)
                hooks.worker_exit.assert_called_once_with(None, None)
                runtime.__exit__.assert_called_once()
                self.assertTrue(runtime.run.call_args.kwargs['once'])
                self.assertEqual(signals.call_count, 4)
                self.assertNotIn('sensitive diagnostic', str(stderr.mock_calls))

    def test_invalid_limits_fail_before_bootstrap(self):
        for arguments in (['--poll-seconds', '0'], ['--poll-seconds', '31'],
                          ['--lease-seconds', '0'], ['--lease-seconds', '301']):
            with patch.object(worker, 'bootstrap') as bootstrap, patch('sys.stderr'):
                self.assertEqual(worker.main(arguments), 1)
                bootstrap.assert_not_called()

    def test_database_is_derived_from_authority_configuration(self):
        database = dict(host='db', user='audit', name='seafile', password='private')
        self.assertEqual(worker.database_environment({'database': database}), dict(
            CLOUDFILE_DB_HOST='db', CLOUDFILE_DB_USER='audit', CLOUDFILE_DB_NAME='seafile',
            CLOUDFILE_DB_PASSWORD='private', CLOUDFILE_DB_PORT='3306'))
        database['port'] = 3307
        self.assertEqual(worker.database_environment({'database': database})['CLOUDFILE_DB_PORT'], '3307')
