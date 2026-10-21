"""Read-only V2 schema inventory: classification, exit codes and secret safety.

The inventory is the operator-facing counterpart of the startup gate: it must
name what is installed (current/missing/incompatible/mixed) without writing or
echoing connection details.
"""
import importlib.util
import io
import os
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock, patch
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'scripts/scripts_cf14.0'
SPEC = importlib.util.spec_from_file_location('schema_inventory', SCRIPTS / 'cloudfile_schema.py')
SCHEMA = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SCHEMA)
CLI_SPEC = importlib.util.spec_from_file_location('schema_inventory_cli', SCRIPTS / 'cloudfile-v2-schema.py')
CLI = importlib.util.module_from_spec(CLI_SPEC)
CLI_SPEC.loader.exec_module(CLI)

LEGACY_GUARD = {'resource_uid', 'lifecycle_ref', 'lease_until', 'guard_id', 'repo_id'}


class Cursor:
    """Deterministic information_schema double; rejects every non-SELECT."""

    def __init__(self, installed, guard_columns=None):
        self.installed = tuple(installed)
        self.guard_columns = guard_columns
        self.rows = ()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, args=()):
        if not sql.lstrip().startswith('SELECT '):
            raise AssertionError('inventory attempted a database write')
        if not args:
            self.rows = tuple((name,) for name in self.installed)
            return
        table = args[0]
        if 'information_schema.COLUMNS' in sql:
            if table == 'cf_edit_guard' and self.guard_columns is not None:
                self.rows = tuple((name, 'char', 36) for name in self.guard_columns)
                return
            self.rows = tuple(
                (name, 'binary' if name == 'path_hash' else 'bigint' if name == 'group_id' else 'varchar',
                 32 if name == 'path_hash' else 255)
                for name in SCHEMA.COLUMNS[table].split())
        elif 'information_schema.TABLES' in sql:
            self.rows = (('InnoDB', 'utf8mb4_bin'),)
        else:
            self.rows = tuple(
                (name, unique, index + 1, column, None)
                for name, (unique, columns) in SCHEMA.INDEXES[table].items()
                for index, column in enumerate(columns))
        return

    def fetchall(self):
        return self.rows


def probe(defect=None, checkout=False):
    installed = list(SCHEMA.COLUMNS)
    guard_columns = None
    if defect == 'missing_table':
        installed.remove('cf_dir_acl')
    elif defect == 'extra_table':
        installed.append('cf_resource')
    elif defect == 'legacy_guard':
        guard_columns = LEGACY_GUARD
    connection = Mock()
    connection.cursor.return_value = Cursor(installed, guard_columns)
    return SCHEMA.inspect_v2_schema(connection, checkout_enabled=checkout)


class InventoryTest(unittest.TestCase):
    def test_current_instance_reports_current(self):
        report = probe(checkout=True)
        self.assertEqual(report['status'], 'current')
        self.assertEqual(report['tables']['cf_edit_guard'], 'current')
        self.assertEqual(report['extra_tables'], [])

    def test_checkout_toggle_does_not_hide_guard_defects(self):
        report = probe(defect='legacy_guard', checkout=False)
        self.assertEqual(report['status'], 'incompatible')
        self.assertEqual(report['tables']['cf_edit_guard'], 'incompatible')

    def test_missing_core_table_and_extra_table_are_mixed(self):
        self.assertEqual(probe(defect='missing_table')['status'], 'mixed')
        extra = probe(defect='extra_table')
        self.assertEqual(extra['status'], 'mixed')
        self.assertEqual(extra['extra_tables'], ['cf_resource'])


class InventoryCliTest(unittest.TestCase):
    def run_cli(self, command, report, connect_error=None):
        driver = ModuleType('pymysql')
        driver.connect = Mock(side_effect=connect_error) if connect_error else Mock()
        connection = Mock()
        connection.cursor.return_value = Cursor(list(SCHEMA.COLUMNS))
        driver.connect.return_value = connection
        env = {'SEAFILE_MYSQL_DB_HOST': 'db', 'SEAFILE_MYSQL_DB_PASSWORD': 'fixture'}
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.dict(sys.modules, {'pymysql': driver}), patch.dict(os.environ, env, clear=False):
            with patch.object(CLI, 'inspect_v2_schema', return_value=report):
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = CLI.main([command])
        return code, stdout.getvalue(), stderr.getvalue()

    def test_plan_always_succeeds_and_check_fails_on_drift(self):
        drift = {'status': 'incompatible', 'checkout_enabled': True, 'tables': {}, 'extra_tables': []}
        self.assertEqual(self.run_cli('plan', drift)[0], 0)
        self.assertEqual(self.run_cli('check', drift)[0], 2)
        self.assertEqual(self.run_cli('check', {'status': 'current', 'tables': {}, 'extra_tables': []})[0], 0)

    def test_connection_failure_is_sanitized(self):
        code, _, stderr = self.run_cli('check', {}, connect_error=RuntimeError('private-fixture-value'))
        self.assertEqual(code, 1)
        self.assertNotIn('private-fixture-value', stderr)


if __name__ == '__main__':
    unittest.main()
