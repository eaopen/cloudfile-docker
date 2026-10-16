"""M1 startup selects an explicit fresh profile and never recreates legacy tables."""
import ast
import importlib.util
from pathlib import Path
import sys
import tempfile
from types import ModuleType
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts/scripts_14.0' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SCHEMA = load('cloudfile_schema')
SETTINGS = load('cloudfile')


class M1BootstrapTest(unittest.TestCase):
    def test_profile_persists_through_failed_init_restart_and_success(self):
        driver = ModuleType('pymysql')
        driver.connect = Mock()
        runner = ModuleType('cloudfile_extensions.schema.runner')
        runner.SchemaRunner = Mock()
        environment = dict(CLOUDFILE_FRESH_SCHEMA_PROFILE='m1', SEAFILE_MYSQL_DB_HOST='db', SEAFILE_MYSQL_DB_PASSWORD='fixture')
        with tempfile.TemporaryDirectory() as directory, patch.dict(sys.modules, {'pymysql': driver, 'cloudfile_extensions.schema.runner': runner}):
            marker = SCHEMA.prepare_fresh_schema(directory, environment)
            self.assertEqual(environment['CLOUDFILE_SCHEMA_PROFILE'], 'm1')
            (Path(directory) / 'seafile-data').mkdir()
            runner.SchemaRunner.return_value.apply.side_effect = ValueError('private value')
            with self.assertRaises(RuntimeError):
                SCHEMA.initialize_fresh_schema(marker, '/installed', environment)
            self.assertTrue(marker.exists())
            # Changing the requested fresh profile cannot convert this retry.
            environment['CLOUDFILE_FRESH_SCHEMA_PROFILE'] = 'legacy'
            SCHEMA.prepare_fresh_schema(directory, environment)
            self.assertEqual(environment['CLOUDFILE_SCHEMA_PROFILE'], 'm1')
            runner.SchemaRunner.return_value.apply.side_effect = None
            SCHEMA.initialize_fresh_schema(marker, '/installed', environment)
            self.assertEqual(SCHEMA.installation_profile(directory), 'm1')
            self.assertFalse(marker.exists())
            self.assertFalse(SCHEMA.initialize_fresh_schema(marker, '/installed', environment))
            self.assertEqual(runner.SchemaRunner.call_args.kwargs, dict(profile='m1'))
            self.assertEqual((Path(directory) / '.cloudfile-schema-profile').stat().st_mode & 0o777, 0o600)

    def test_existing_volume_does_not_convert_from_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / 'seafile-data').mkdir()
            environment = {'CLOUDFILE_FRESH_SCHEMA_PROFILE': 'm1'}
            marker = SCHEMA.prepare_fresh_schema(directory, environment)
            self.assertFalse(marker.exists())
            self.assertEqual(environment['CLOUDFILE_SCHEMA_PROFILE'], 'legacy')

    def test_conflicting_profile_markers_stop_startup(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / '.cloudfile-schema-profile').write_text('m1')
            (Path(directory) / '.cloudfile-schema-init-pending').write_text('legacy')
            with self.assertRaises(RuntimeError):
                SCHEMA.installation_profile(directory)

    def test_explicit_clean_configuration_init_preserves_existing_native_data(self):
        with tempfile.TemporaryDirectory() as directory:
            native = Path(directory) / 'seafile-data'
            native.mkdir()
            (native / 'fixture-block').write_bytes(b'unchanged-native-content')
            environment = {'CLOUDFILE_FRESH_SCHEMA_PROFILE': 'm1', 'CLOUDFILE_INITIALIZE_M1_SCHEMA': 'true'}
            marker = SCHEMA.prepare_fresh_schema(directory, environment)
            self.assertTrue(marker.exists())
            self.assertEqual(environment['CLOUDFILE_SCHEMA_PROFILE'], 'm1')
            self.assertEqual((native / 'fixture-block').read_bytes(), b'unchanged-native-content')
            marker.unlink()
            (Path(directory) / '.cloudfile-schema-profile').write_text('m1')
            self.assertTrue(SCHEMA.prepare_fresh_schema(directory, environment).exists())

    def test_m1_config_writer_skips_all_legacy_extension_ddl(self):
        tree = ast.parse((ROOT / 'scripts/scripts_14.0/bootstrap.py').read_text())
        node = next(item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == 'write_cloudfile_config')
        calls = []
        environment = {'shared_seafiledir': '/fixture'}
        names = ['loginfo', 'write_seafile_env', 'write_cloudfile_settings', 'write_cloudfile_seafile_conf',
                 'write_seafevents_search_config', 'write_seafevents_audit_config', 'apply_cloudfile_schema',
                 'apply_sso_hierarchy_schema_compatibility', 'apply_metadata_schema_compatibility',
                 'apply_tag_schema_compatibility', 'apply_starred_obj_id_schema_compatibility', 'apply_audit_schema']
        for name in names:
            environment[name] = lambda *args, name=name: calls.append(name)
        module = ModuleType('cloudfile_schema')
        module.installation_profile = lambda path: 'm1'
        with patch.dict(sys.modules, {'cloudfile_schema': module}):
            exec(compile(ast.Module(body=[node], type_ignores=[]), '<bootstrap>', 'exec'), environment)
            environment['write_cloudfile_config']()
        self.assertNotIn('apply_cloudfile_schema', calls)
        self.assertNotIn('apply_sso_hierarchy_schema_compatibility', calls)
        self.assertNotIn('apply_audit_schema', calls)
        self.assertIn('apply_metadata_schema_compatibility', calls)

    def test_m1_settings_do_not_enable_runtimes_with_absent_tables(self):
        namespace = {}
        exec(SETTINGS.render_settings({'CLOUDFILE_SCHEMA_PROFILE': 'm1'}), namespace)
        self.assertIs(namespace['CF_ENABLE_FILEOPS'], False)
        self.assertIs(namespace['CF_ENABLE_EXTERNAL_SOURCES'], False)
        self.assertIs(namespace['CF_ENABLE_SEARCH'], False)
        for flag in ('CF_ENABLE_FILEOPS', 'CF_ENABLE_EXTERNAL_SOURCES', 'CF_ENABLE_FILE_LOCK'):
            with self.subTest(flag=flag), self.assertRaises(ValueError):
                SETTINGS.render_settings({'CLOUDFILE_SCHEMA_PROFILE': 'm1', flag: 'true'})
        with self.assertRaises(ValueError):
            SETTINGS.render_settings({'CLOUDFILE_SCHEMA_PROFILE': 'm1', 'CF_ENABLE_SSO': 'true'})
