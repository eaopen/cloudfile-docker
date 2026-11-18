"""Focused tests for the narrowly authorized schema completion and migration."""
import importlib.util
import sys
import tempfile
import unittest
from configparser import ConfigParser
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

schema = load('upgrade_schema', ROOT / 'scripts/scripts_cf14.0/cloudfile_schema.py')
migration = load('repo_migration', ROOT / 'tools/migrate/repo-features.py')

class UpgradeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        sql = self.root / 'sql/mysql'
        sql.mkdir(parents=True)
        for name in ('cloudfile-v2.sql', 'cloudfile-v2-edit.sql', 'cloudfile-v2-audit.sql', 'cloudfile-v2-protection.sql'):
            (sql / name).write_text(name)
        self.cursor = Mock()
        self.cursor.__enter__ = Mock(return_value=self.cursor)
        self.cursor.__exit__ = Mock(return_value=False)
        self.cursor.fetchone.return_value = None
        self.db = Mock(); self.db.cursor.return_value = self.cursor
        self.fresh = Mock()
        self.fresh.tables = set(schema.COLUMNS)
        self.fresh.ddl = {'cf_repo_feature': 'CREATE reviewed feature table'}
        self.fresh._tables.return_value = self.fresh.tables - {'cf_repo_feature'}
        module = ModuleType('cloudfile_ext.v2.schema')
        module.FreshSchema = Mock(return_value=self.fresh)
        @contextmanager
        def lock(db, key):
            self.assertEqual(key, 'schema')
            yield
        module.database_lock = lock
        self.modules = patch.dict(sys.modules, {'cloudfile_ext.v2.schema': module})
        self.modules.start(); self.addCleanup(self.modules.stop)
        self.report = {'status': 'mixed', 'extra_tables': [], 'tables': {
            n: 'missing' if n == 'cf_repo_feature' else 'current' for n in schema.COLUMNS}}

    def run_upgrade(self, reports):
        with patch.object(schema, 'inspect_v2_schema', side_effect=reports), patch.object(schema, 'verify_v2_schema'):
            schema._complete_repo_feature_schema(self.db, self.root)

    def test_create_and_exact_verify(self):
        self.run_upgrade([self.report, self.report])
        self.assertEqual(self.fresh._verify_one.call_count, 5)
        self.assertEqual(self.cursor.execute.call_args_list[-1].args[0], 'CREATE reviewed feature table')
        self.fresh.verify.assert_called_once()

    def test_other_missing_legacy_and_drift_rejected(self):
        for change in ('missing', 'legacy', 'drift'):
            report = {'status': 'mixed', 'extra_tables': [], 'tables': dict(self.report['tables'])}
            if change == 'missing': report['tables']['cf_dir_acl'] = 'missing'
            if change == 'legacy': report['extra_tables'] = ['cf_library_storage']
            if change == 'drift': report['tables']['cf_dir_acl'] = 'incompatible'
            with self.subTest(change=change), self.assertRaises(ValueError): self.run_upgrade([report])
        self.cursor.execute.assert_not_called()

    def test_exact_ddl_drift_rejected_before_create(self):
        self.fresh._verify_one.side_effect = ValueError('drift')
        with self.assertRaises(ValueError): self.run_upgrade([self.report, self.report])
        self.cursor.execute.assert_not_called()

    def test_existing_safeguard_blocks_creation(self):
        for results in ([(1,)], [None, (1,)]):
            with self.subTest(results=results):
                self.cursor.reset_mock()
                self.cursor.fetchone.side_effect = results
                with self.assertRaises(ValueError): self.run_upgrade([self.report, self.report])
                self.assertFalse(any(call.args[0].startswith('CREATE ') for call in self.cursor.execute.call_args_list))

    def test_race_completed_before_helper_is_idempotent(self):
        current = {'status': 'current', 'extra_tables': [],
                   'tables': {n: 'current' for n in schema.COLUMNS}}
        self.run_upgrade([current])
        self.cursor.execute.assert_not_called()

    def test_race_completed_by_other_starter_is_idempotent(self):
        current = {'status': 'current', 'extra_tables': [], 'tables': {n: 'current' for n in schema.COLUMNS}}
        self.run_upgrade([self.report, current])
        self.cursor.execute.assert_not_called()
        self.fresh.verify.assert_called_once()

    def test_race_to_invalid_layout_rejected(self):
        changed = dict(self.report, extra_tables=['cf_library_storage'])
        with self.assertRaises(ValueError): self.run_upgrade([self.report, changed])
        self.cursor.execute.assert_not_called()

    def test_current_startup_is_read_only(self):
        with patch.object(schema, '_connect', return_value=self.db), patch.object(schema, 'inspect_v2_schema', return_value={'status': 'current'}), patch.object(schema, 'verify_v2_schema') as verify, patch.object(schema, '_complete_repo_feature_schema') as complete:
            schema.verify_development_schema(self.root, {})
        verify.assert_called_once(); complete.assert_not_called()

class MigrationTest(unittest.TestCase):
    def run_case(self, blocked=None):
        class Cursor:
            def __init__(self): self.sql = []; self.rows = []
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def execute(self, sql, args=()):
                self.sql.append((sql, args)); self.rows = []
                if sql == 'SHOW TABLES': self.rows = [(x,) for x in ('cf_library_storage', 'cf_dir_acl', 'cf_sso_group_map', 'cf_edit_guard', 'cf_audit_event', 'cf_file_protection')]
                elif sql.startswith('SELECT 1 FROM ') and blocked and blocked in sql: self.rows = [(1,)]
            def fetchall(self): return self.rows
            def fetchone(self): return self.rows[0] if self.rows else None
        cursor = Cursor(); db = Mock(); db.cursor.return_value = cursor
        fake = Mock(); fake.tables = set(schema.COLUMNS); fake.ddl = {'cf_repo_feature': 'CREATE feature'}
        mod = ModuleType('cloudfile_ext.v2.schema'); mod.FreshSchema = Mock(return_value=fake)
        storage = ModuleType('cloudfile_ext.v2.storage_reconcile'); storage.valid_key = lambda x: True
        config = ConfigParser(); config.read_dict({'cloudfile': {'checkout_repo_ids': 'not-a-uuid', 'protection_repo_ids': 'anything'}})
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            for name in ('cloudfile-v2.sql', 'cloudfile-v2-edit.sql', 'cloudfile-v2-audit.sql', 'cloudfile-v2-protection.sql'): (path/name).write_text('ddl')
            with patch.dict(sys.modules, {'cloudfile_ext.v2.schema': mod, 'cloudfile_ext.v2.storage_reconcile': storage}):
                if blocked:
                    with self.assertRaisesRegex(ValueError, 'explicit safe disposition'): migration.migrate(db, config, path, True)
                else: migration.migrate(db, config, path, True)
        return cursor.sql

    def test_legacy_lists_do_not_create_feature_rows(self):
        calls = self.run_case()
        self.assertFalse(any('INSERT INTO cf_repo_feature' in sql for sql, _ in calls))
        self.assertTrue(any(sql == 'CREATE feature' for sql, _ in calls))

    def test_protection_and_active_guard_block_before_writes(self):
        for table in ('cf_file_protection', 'cf_edit_guard'):
            with self.subTest(table=table):
                calls = self.run_case(table)
                self.assertFalse(any(sql.startswith(('CREATE ', 'INSERT ', 'RENAME ')) for sql, _ in calls))

if __name__ == '__main__': unittest.main()
