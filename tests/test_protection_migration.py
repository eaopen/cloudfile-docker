"""Migration refuses partial/drifted schemas and never changes existing data."""
import contextlib
import importlib.util
from pathlib import Path
import sys
from types import ModuleType
import unittest
from unittest.mock import MagicMock, patch

SPEC = importlib.util.spec_from_file_location('migration', Path(__file__).resolve().parents[1] / 'tools/migrate/file-protection-v1.py')
MIGRATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MIGRATION)


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.module = ModuleType('cloudfile_ext.v2.schema')
        self.module.database_lock = lambda *args: contextlib.nullcontext()
        self.module.SchemaError = ValueError
        self.module.PROTECTION_TABLES = frozenset({'cf_file_protection'})
        self.schema = MagicMock()
        self.schema.tables = frozenset({'cf_library_storage', 'cf_sso_group_map', 'cf_dir_acl', 'cf_edit_guard', 'cf_audit_event', 'cf_file_protection'})
        self.schema._tables.return_value = self.schema.tables - self.module.PROTECTION_TABLES
        self.schema.ddl = {'cf_file_protection': 'CREATE TABLE cf_file_protection reviewed'}
        self.cursor = self.schema.connection.cursor.return_value.__enter__.return_value

    def run_migration(self, apply=False):
        with patch.dict(sys.modules, {'cloudfile_ext.v2.schema': self.module}):
            return MIGRATION.migrate(self.schema, apply=apply)

    def test_plan_does_not_create_table(self):
        self.assertIn('would create', self.run_migration())
        self.cursor.execute.assert_not_called()
        self.assertEqual(self.schema._verify_one.call_count, 5)

    def test_apply_creates_only_protection_and_verifies(self):
        self.run_migration(True)
        self.cursor.execute.assert_called_once_with(self.schema.ddl['cf_file_protection'])
        self.schema.verify.assert_called_once()

    def test_repeat_is_noop(self):
        self.schema._tables.return_value = self.schema.tables
        self.assertEqual(self.run_migration(True), 'already current')
        self.cursor.execute.assert_not_called()

    def test_partial_extra_or_drifted_schema_cannot_create(self):
        for present in (set(), self.schema.tables - {'cf_edit_guard'}, self.schema.tables | {'cf_resource'}):
            self.schema._tables.return_value = present
            with self.assertRaises(ValueError):
                self.run_migration(True)
        self.schema._tables.return_value = self.schema.tables - self.module.PROTECTION_TABLES
        self.schema._verify_one.side_effect = ValueError('drift')
        with self.assertRaises(ValueError):
            self.run_migration(True)
        self.cursor.execute.assert_not_called()
