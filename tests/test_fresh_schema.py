"""Startup checks the installed contract and initializes only a fresh volume."""
import ast
import importlib.util
from pathlib import Path
import sys
import tempfile
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

    def test_startup_initializes_fresh_volume_without_legacy_runner(self):
        bootstrap = ast.parse((ROOT/'scripts/scripts_14.0/bootstrap.py').read_text())
        function = next(n for n in bootstrap.body if isinstance(n, ast.FunctionDef) and n.name == 'write_cloudfile_config')
        names = {n.func.id for n in ast.walk(function) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        self.assertFalse(any(name.startswith('apply_') for name in names))
        start = (ROOT/'scripts/scripts_14.0/start.py').read_text()
        self.assertIn('prepare_fresh_schema(shared_seafiledir)', start)
        self.assertIn('initialize_fresh_schema(schema_marker, installdir)', start)
        self.assertIn('verify_development_schema(installdir)', start)
        startup = ast.parse(start)
        hook = next(n for n in ast.walk(startup) if isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Name) and n.func.id == 'write_policy_worker_hooks')
        self.assertTrue(any(k.arg == 'v2' and isinstance(k.value, ast.Constant)
                            and k.value.value is True for k in hook.keywords))
        # Fresh initialization is allowed; legacy migration is not.
        schema = (ROOT/'scripts/scripts_14.0/cloudfile_schema.py').read_text()
        self.assertNotIn('SchemaRunner', schema)
        self.assertNotIn('cloudfile.sql', schema)
        self.assertNotIn('ALTER TABLE', schema.upper())


class FreshInstallTest(unittest.TestCase):
    """The marker authorizes one-time initialization, never an upgrade."""

    class FakeFreshSchema:
        calls = []
        fail = False

        def __init__(self, connection, ddl, *, edit_ddl=None, audit_ddl=None):
            self.ddl, self.edit_ddl, self.audit_ddl = ddl, edit_ddl, audit_ddl
            FreshInstallTest.FakeFreshSchema.calls.append(self)

        def install(self):
            if FreshInstallTest.FakeFreshSchema.fail:
                raise RuntimeError('private-fixture-value')

    def setUp(self):
        FreshInstallTest.FakeFreshSchema.calls = []
        FreshInstallTest.FakeFreshSchema.fail = False

    def _installdir(self, root):
        installdir = Path(root) / 'seafile-server'
        sql = installdir / 'sql' / 'mysql'
        sql.mkdir(parents=True, exist_ok=True)
        (sql / 'cloudfile-v2.sql').write_text('-- reviewed base DDL')
        (sql / 'cloudfile-v2-edit.sql').write_text('-- reviewed optional Guard DDL')
        (sql / 'cloudfile-v2-audit.sql').write_text('-- reviewed operation audit DDL')
        (installdir / 'seahub').mkdir(exist_ok=True)
        return installdir

    def _env(self, checkout='false'):
        return {'SEAFILE_MYSQL_DB_HOST': 'db', 'SEAFILE_MYSQL_DB_PASSWORD': 'fixture',
                'CF_ENABLE_CHECKOUT': checkout}

    def _init(self, root, marker, checkout='false'):
        driver = ModuleType('pymysql')
        connection = Mock()
        driver.connect = Mock(return_value=connection)
        schema = ModuleType('cloudfile_ext.v2.schema')
        schema.FreshSchema = FreshInstallTest.FakeFreshSchema
        v2 = ModuleType('cloudfile_ext.v2')
        v2.schema = schema
        package = ModuleType('cloudfile_ext')
        package.v2 = v2
        modules = {'pymysql': driver, 'cloudfile_ext': package,
                   'cloudfile_ext.v2': v2, 'cloudfile_ext.v2.schema': schema}
        with patch.dict(sys.modules, modules):
            result = SCHEMA.initialize_fresh_schema(marker, self._installdir(root), self._env(checkout))
        return result, connection

    def test_marker_only_for_volume_without_seafile_data(self):
        with tempfile.TemporaryDirectory() as root:
            fresh = Path(root) / 'fresh'
            fresh.mkdir()
            self.assertTrue(SCHEMA.prepare_fresh_schema(fresh).exists())
            existing = Path(root) / 'existing'
            (existing / 'seafile-data').mkdir(parents=True)
            self.assertFalse(SCHEMA.prepare_fresh_schema(existing).exists())

    def test_fresh_volume_installs_reviewed_ddl_once(self):
        with tempfile.TemporaryDirectory() as root:
            shared = Path(root) / 'shared'
            shared.mkdir()
            marker = SCHEMA.prepare_fresh_schema(shared, self._env('false'))
            result, connection = self._init(root, marker, 'false')
        self.assertTrue(result)
        self.assertFalse(marker.exists())
        self.assertEqual(len(FreshInstallTest.FakeFreshSchema.calls), 1)
        self.assertIsNone(FreshInstallTest.FakeFreshSchema.calls[0].edit_ddl)
        self.assertIsNotNone(FreshInstallTest.FakeFreshSchema.calls[0].audit_ddl)
        connection.close.assert_called_once()

    def test_enabled_checkout_plan_installs_the_optional_guard(self):
        with tempfile.TemporaryDirectory() as root:
            shared = Path(root) / 'shared'
            shared.mkdir()
            marker = SCHEMA.prepare_fresh_schema(shared, self._env('true'))
            result, _ = self._init(root, marker, 'true')
        self.assertTrue(result)
        self.assertIsNotNone(FreshInstallTest.FakeFreshSchema.calls[0].edit_ddl)

    def test_failed_install_keeps_marker_and_retry_uses_the_original_plan(self):
        FreshInstallTest.FakeFreshSchema.fail = True
        with tempfile.TemporaryDirectory() as root:
            shared = Path(root) / 'shared'
            shared.mkdir()
            marker = SCHEMA.prepare_fresh_schema(shared, self._env('false'))
            with self.assertRaises(RuntimeError) as error:
                self._init(root, marker, 'false')
            self.assertTrue(marker.exists())
            # A configuration flip during the failed attempt must not add the
            # optional Guard table: retry keeps the recorded plan.
            FreshInstallTest.FakeFreshSchema.fail = False
            result, _ = self._init(root, marker, 'true')
            self.assertTrue(result)
        self.assertIn('inspect', str(error.exception))
        self.assertFalse(marker.exists())
        self.assertIsNone(FreshInstallTest.FakeFreshSchema.calls[-1].edit_ddl)

    def test_marker_copied_from_another_volume_is_refused(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / 'source'
            source.mkdir()
            self.assertTrue(SCHEMA.prepare_fresh_schema(source, self._env('false')).exists())
            existing = Path(root) / 'existing'
            (existing / 'seafile-data').mkdir(parents=True)
            stray = existing / SCHEMA.MARKER_NAME
            stray.write_bytes((source / SCHEMA.MARKER_NAME).read_bytes())
            with self.assertRaises(RuntimeError) as error:
                self._init(root, stray, 'false')
        self.assertIn('volume', str(error.exception))
        self.assertEqual(FreshInstallTest.FakeFreshSchema.calls, [])

    def test_existing_volume_without_marker_never_runs_ddl(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertFalse(SCHEMA.initialize_fresh_schema(Path(root) / SCHEMA.MARKER_NAME, root, {}))
        self.assertEqual(FreshInstallTest.FakeFreshSchema.calls, [])


if __name__ == '__main__': unittest.main()
