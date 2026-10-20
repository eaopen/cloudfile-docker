"""Existing CloudFile databases are inventoried, never auto-upgraded."""
import runpy
import tempfile
from pathlib import Path
from types import ModuleType
from unittest import TestCase
from unittest.mock import Mock, patch
import sys

ROOT = Path(__file__).resolve().parents[1]
COMMAND = ROOT / 'scripts/scripts_14.0/cloudfile-v2-schema.py'
SCHEMA = runpy.run_path(str(COMMAND))


class SchemaInventoryCommandTests(TestCase):
    def test_explicit_native_database_credentials_are_required(self):
        with self.assertRaises(ValueError):
            SCHEMA['database_options']({'SEAFILE_MYSQL_DB_HOST': 'db'})
        options = SCHEMA['database_options']({
            'SEAFILE_MYSQL_DB_HOST': 'db', 'SEAFILE_MYSQL_DB_USER': 'seafile',
            'SEAFILE_MYSQL_DB_PASSWORD': 'secret',
            'SEAFILE_MYSQL_DB_SEAFILE_DB_NAME': 'seafile_db'})
        self.assertEqual(options['database'], 'seafile_db')
        self.assertTrue(options['autocommit'])

    def test_existing_schema_diagnosis_issues_no_mutations(self):
        driver = Mock()
        expected = dict(status='migration_review_required',
                        tables={'cf_edit_guard': 'legacy'},
                        unexpected_cf_tables=['cf_resource'])
        v2 = ModuleType('cloudfile_ext.v2.schema')
        v2.FreshSchema = Mock()
        v2.FreshSchema.return_value.inspect.return_value = expected
        imported = {'cloudfile_ext': ModuleType('cloudfile_ext'),
                    'cloudfile_ext.v2': ModuleType('cloudfile_ext.v2'),
                    'cloudfile_ext.v2.schema': v2}
        helper = ModuleType('cloudfile_schema')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sql = root / 'sql' / 'mysql'
            sql.mkdir(parents=True)
            (sql / 'cloudfile-v2.sql').write_text('reviewed V2 DDL')
            helper._v2_schema_dir = lambda _: sql
            imported['cloudfile_schema'] = helper
            with patch.dict(sys.modules, imported):
                before = list(sys.path)
                result = SCHEMA['inspect'](root, {
                    'SEAFILE_MYSQL_DB_HOST': 'db', 'SEAFILE_MYSQL_DB_USER': 'seafile',
                    'SEAFILE_MYSQL_DB_PASSWORD': 'secret',
                    'SEAFILE_MYSQL_DB_SEAFILE_DB_NAME': 'seafile_db'}, connect=driver)
                self.assertEqual(before, sys.path)
            self.assertEqual(result, expected)
        v2.FreshSchema.return_value.inspect.assert_called_once()
        v2.FreshSchema.return_value.install.assert_not_called()
        driver.return_value.close.assert_called_once_with()


if __name__ == '__main__':
    import unittest
    unittest.main()
