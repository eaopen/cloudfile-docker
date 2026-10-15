"""Fresh-install DDL must resume failures without upgrading existing volumes."""

import importlib.util
from pathlib import Path
import sys
import tempfile
from types import ModuleType
import unittest
from unittest.mock import Mock, patch


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/scripts_14.0/cloudfile_schema.py'
SPEC = importlib.util.spec_from_file_location('fresh_schema', SCRIPT)
SCHEMA = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SCHEMA)


class FreshSchemaTest(unittest.TestCase):
    def test_existing_volume_does_not_opt_into_ddl(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / 'seafile-data').mkdir()
            marker = SCHEMA.prepare_fresh_schema(directory)
            self.assertFalse(marker.exists())
            self.assertFalse(SCHEMA.initialize_fresh_schema(marker, '/missing', {}))

    def test_failed_first_install_retains_intent_after_ce_initializes(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = SCHEMA.prepare_fresh_schema(directory)
            self.assertTrue(marker.exists())
            (Path(directory) / 'seafile-data').mkdir()
            self.assertEqual(SCHEMA.prepare_fresh_schema(directory), marker)
            self.assertTrue(marker.exists())

    def _run(self, fail=False):
        driver = ModuleType('pymysql')
        driver.connect = Mock()
        runner_module = ModuleType('cloudfile_extensions.schema.runner')
        runner_module.SchemaRunner = Mock()
        if fail:
            runner_module.SchemaRunner.return_value.apply.side_effect = ValueError('private-database-value')
        modules = {'pymysql': driver, 'cloudfile_extensions.schema.runner': runner_module}
        environment = dict(SEAFILE_MYSQL_DB_HOST='db', SEAFILE_MYSQL_DB_USER='native',
                           SEAFILE_MYSQL_DB_PASSWORD='fixture', SEAFILE_MYSQL_DB_SEAFILE_DB_NAME='native_db')
        with tempfile.TemporaryDirectory() as directory, patch.dict(sys.modules, modules):
            marker = SCHEMA.prepare_fresh_schema(directory)
            previous_path = list(sys.path)
            if fail:
                with self.assertRaisesRegex(RuntimeError, '^Fresh CloudFile schema initialization failed;') as error:
                    SCHEMA.initialize_fresh_schema(marker, '/installed', environment)
                self.assertNotIn('private-database-value', str(error.exception))
                self.assertTrue(marker.exists())
            else:
                self.assertTrue(SCHEMA.initialize_fresh_schema(marker, '/installed', environment))
                self.assertFalse(marker.exists())
                # A completed installation must not issue DDL again on restart.
                self.assertFalse(SCHEMA.initialize_fresh_schema(marker, '/installed', environment))
            self.assertEqual(sys.path, previous_path)
            runner_module.SchemaRunner.return_value.apply.assert_called_once_with()
            driver.connect.return_value.close.assert_called_once_with()
            self.assertEqual(driver.connect.call_args.kwargs['database'], 'native_db')
            self.assertTrue(driver.connect.call_args.kwargs['autocommit'])

    def test_success_verifies_and_clears_intent(self):
        self._run()

    def test_failure_stops_startup_and_allows_retry(self):
        self._run(fail=True)


if __name__ == '__main__':
    unittest.main()
