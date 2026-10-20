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

    def _run(self, fail=False, editing=False):
        driver = ModuleType('pymysql')
        driver.connect = Mock()
        v2 = ModuleType('cloudfile_ext.v2.schema')
        v2.FreshSchema = Mock()
        if fail:
            v2.FreshSchema.return_value.install.side_effect = ValueError('private-database-value')
        modules = {'pymysql': driver,
                   'cloudfile_ext': ModuleType('cloudfile_ext'),
                   'cloudfile_ext.v2': ModuleType('cloudfile_ext.v2'),
                   'cloudfile_ext.v2.schema': v2}
        environment = dict(SEAFILE_MYSQL_DB_HOST='db', SEAFILE_MYSQL_DB_USER='native',
                           SEAFILE_MYSQL_DB_PASSWORD='fixture', SEAFILE_MYSQL_DB_SEAFILE_DB_NAME='native_db')
        if editing:
            environment['CF_ENABLE_CHECKOUT'] = 'true'
        with tempfile.TemporaryDirectory() as directory, patch.dict(sys.modules, modules):
            root = Path(directory) / 'installed'
            schema_dir = root / 'sql/mysql'
            schema_dir.mkdir(parents=True)
            (schema_dir / 'cloudfile-v2.sql').write_text('current V2 three-table DDL')
            (schema_dir / 'cloudfile-v2-edit.sql').write_text('current V2 optional Guard DDL')
            marker = SCHEMA.prepare_fresh_schema(directory)
            previous_path = list(sys.path)
            if fail:
                with self.assertRaisesRegex(RuntimeError, '^CloudFile V2 fresh schema initialization failed;') as error:
                    SCHEMA.initialize_fresh_schema(marker, root, environment)
                self.assertNotIn('private-database-value', str(error.exception))
                self.assertTrue(marker.exists())
            else:
                self.assertTrue(SCHEMA.initialize_fresh_schema(marker, root, environment))
                self.assertFalse(marker.exists())
                # A completed installation must not issue DDL again on restart.
                self.assertFalse(SCHEMA.initialize_fresh_schema(marker, root, environment))
            self.assertEqual(sys.path, previous_path)
            v2.FreshSchema.assert_called_once_with(driver.connect.return_value,
                'current V2 three-table DDL',
                edit_ddl='current V2 optional Guard DDL' if editing else None)
            v2.FreshSchema.return_value.install.assert_called_once_with()
            driver.connect.return_value.close.assert_called_once_with()
            self.assertEqual(driver.connect.call_args.kwargs['database'], 'native_db')
            self.assertTrue(driver.connect.call_args.kwargs['autocommit'])

    def test_success_verifies_and_clears_intent(self):
        self._run()

    def test_failure_stops_startup_and_allows_retry(self):
        self._run(fail=True)

    def test_explicit_checkout_adds_only_current_guard(self):
        self._run(editing=True)

    def test_bootstrap_does_not_create_legacy_extension_tables(self):
        # V2 bootstrap retains CE metadata/tag compatibility, not the retired
        # 001..042/029 Guard or cloudfile.sql integration table creators.
        code = (Path(__file__).resolve().parents[1] /
                'scripts/scripts_14.0/bootstrap.py').read_text()
        body = code.split('def write_cloudfile_config():', 1)[1].split(
            '\\ndef apply_sso_hierarchy_schema_compatibility', 1)[0]
        for call in ('apply_cloudfile_schema()', 'apply_sso_hierarchy_schema_compatibility()',
                     'apply_audit_schema()'):
            self.assertNotIn('    '+call, body)


if __name__ == '__main__':
    unittest.main()
