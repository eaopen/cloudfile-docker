"""Development startup checks contracts and never executes an upgrade."""
import ast
import importlib.util
from pathlib import Path
import sys
from types import ModuleType
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('development_schema', ROOT / 'scripts/scripts_14.0/cloudfile_schema.py')
SCHEMA = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SCHEMA)


class ReadOnlyCursor:
    def __init__(self, defect=None): self.defect, self.rows, self.calls = defect, (), []
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def execute(self, sql, args=()):
        if not sql.startswith('SELECT '): raise AssertionError('Startup attempted a database write')
        self.calls.append(sql)
        if not args:
            self.rows = tuple((name,) for name in SCHEMA.COLUMNS)
            if self.defect == 'legacy_table': self.rows += (('cf_resource',),)
            return
        table = args[0]
        if 'information_schema.TABLES' in sql:
            self.rows = (('InnoDB', 'utf8mb4_bin'),)
        elif 'information_schema.COLUMNS' in sql:
            self.rows = tuple((name, 'binary' if name == 'path_hash' else 'bigint' if name == 'group_id' else 'varchar',
                               32 if name == 'path_hash' else 255) for name in SCHEMA.COLUMNS[table].split())
            if self.defect == 'old_guard' and table == 'cf_edit_guard': self.rows += (('resource_uid', 'char', 36),)
            if self.defect == 'text_hash' and table == 'cf_dir_acl':
                self.rows = tuple((name, 'char', 64) if name == 'path_hash' else (name, kind, length) for name, kind, length in self.rows)
        else:
            self.rows = tuple((name, unique, i+1, column, None)
                for name, (unique, columns) in SCHEMA.INDEXES[table].items() for i, column in enumerate(columns))
            if self.defect == 'missing_index' and table == 'cf_edit_guard':
                self.rows = tuple(row for row in self.rows if row[0] != 'cf_edit_guard_active')
    def fetchall(self): return self.rows


class DevelopmentSchemaTest(unittest.TestCase):
    def test_correct_contract_issues_only_selects(self):
        cursor = ReadOnlyCursor()
        connection = Mock(); connection.cursor.return_value = cursor
        SCHEMA.verify_v2_schema(connection)
        self.assertEqual(len(cursor.calls), 10)
        connection.commit.assert_not_called()
        connection.rollback.assert_not_called()

    def test_old_layout_hash_and_missing_index_fail_without_repair(self):
        for defect in ('old_guard', 'text_hash', 'missing_index', 'legacy_table'):
            connection = Mock(); connection.cursor.return_value = ReadOnlyCursor(defect)
            with self.assertRaises(ValueError): SCHEMA.verify_v2_schema(connection, checkout_enabled=True)
            connection.commit.assert_not_called()

    def test_disabled_checkout_ignores_guard_layout_and_index(self):
        for defect in ('old_guard', 'missing_index'):
            cursor = ReadOnlyCursor(defect)
            connection = Mock(); connection.cursor.return_value = cursor
            SCHEMA.verify_v2_schema(connection)
            self.assertEqual(len(cursor.calls), 10)

    def test_connection_failure_is_sanitized_and_requires_sql(self):
        driver = ModuleType('pymysql'); driver.connect = Mock(side_effect=RuntimeError('private-fixture-value'))
        env = dict(SEAFILE_MYSQL_DB_HOST='db', SEAFILE_MYSQL_DB_PASSWORD='fixture')
        with patch.dict(sys.modules, {'pymysql': driver}):
            with self.assertRaises(RuntimeError) as error: SCHEMA.verify_development_schema(environment=env)
        self.assertIn('SQL', str(error.exception)); self.assertNotIn('private-fixture-value', str(error.exception))

    def test_startup_and_config_do_not_call_ddl_helpers(self):
        bootstrap = ast.parse((ROOT/'scripts/scripts_14.0/bootstrap.py').read_text())
        function = next(n for n in bootstrap.body if isinstance(n, ast.FunctionDef) and n.name == 'write_cloudfile_config')
        names = {n.func.id for n in ast.walk(function) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        self.assertFalse(any(name.startswith('apply_') for name in names))
        start = (ROOT/'scripts/scripts_14.0/start.py').read_text()
        self.assertIn('verify_development_schema(installdir)', start)
        startup = ast.parse(start)
        hook = next(n for n in ast.walk(startup) if isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Name) and n.func.id == 'write_policy_worker_hooks')
        self.assertTrue(any(k.arg == 'v2' and isinstance(k.value, ast.Constant)
                            and k.value.value is True for k in hook.keywords))
        self.assertNotIn('initialize_fresh_schema', start)
        self.assertNotIn('prepare_fresh_schema', start)
        self.assertNotIn('SchemaRunner', (ROOT/'scripts/scripts_14.0/cloudfile_schema.py').read_text())


if __name__ == '__main__': unittest.main()
