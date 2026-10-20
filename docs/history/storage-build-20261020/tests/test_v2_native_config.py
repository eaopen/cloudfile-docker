"""Protect native assets at the exact fresh-volume/upgrade boundary."""
import configparser
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock

# Archived with the historical V2 launcher it exercises.
BUILD = Path(__file__).resolve().parents[1] / 'v2'
spec = importlib.util.spec_from_file_location('native_config', BUILD / 'native_config.py')
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)
REPO = '11111111-1111-4111-8111-111111111111'


class NativeConfigTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = configparser.ConfigParser(interpolation=None)

    def layout(self, nested=False):
        base = self.root / 'seafile' if nested else self.root
        (base / 'seafile-data/storage').mkdir(parents=True)
        (base / 'conf').mkdir()
        (base / 'conf/seafile.conf').write_text('[fileserver]\n')
        return base

    def test_fresh_nested_and_flat_layouts(self):
        self.assertEqual(native.volume_layout(self.root), (self.root, False))
        base = self.layout(nested=True)
        self.assertEqual(native.volume_layout(self.root), (base, True))
        self.layout()
        with self.assertRaisesRegex(native.NativeStartupError, 'AMBIGUOUS'):
            native.volume_layout(self.root)

    def test_flat_restart_is_reuse(self):
        self.layout()
        self.assertEqual(native.volume_layout(self.root), (self.root, True))

    def test_missing_mount_or_config_never_bootstraps_empty_data(self):
        (self.root / 'seafile-data').mkdir()
        with self.assertRaisesRegex(native.NativeStartupError, 'NATIVE_STORAGE_MISSING'):
            native.volume_layout(self.root)
        self.assertFalse((self.root / 'conf').exists())

    def test_unrecognized_original_storage_is_not_fresh(self):
        (self.root / 'storage').mkdir()
        with self.assertRaisesRegex(native.NativeStartupError, 'LAYOUT_REQUIRES_REVIEW'):
            native.volume_layout(self.root)

    def test_conflicting_database_env_is_rejected_without_exposing_secret(self):
        (self.root / '.env').write_text('SEAFILE_MYSQL_DB_PASSWORD="source-secret"\n')
        with self.assertRaises(native.NativeStartupError) as caught:
            native.load_native_environment(self.root, {'SEAFILE_MYSQL_DB_PASSWORD': 'candidate-secret'})
        self.assertNotIn('source-secret', str(caught.exception))
        self.assertNotIn('candidate-secret', str(caught.exception))

    def test_flat_database_names_and_percent_password_survive_restart(self):
        self.config.read_dict({'database': {'host': 'original-db', 'user': 'native', 'password': 'a%secret',
                                          'db_name': 'old_files', 'ccnet_db_name': 'old_accounts'}})
        previous = {'DATABASES': {'default': {'NAME': 'old_hub', 'HOST': 'original-db'}}}
        env = {'PUBLIC_URL': 'https://files.example.test'}
        native.native_environment(self.config, previous, env)
        native.verify_database_binding(self.config, env, previous)
        self.assertEqual(env['SEAFILE_MYSQL_DB_SEAFILE_DB_NAME'], 'old_files')
        self.assertEqual(env['SEAFILE_MYSQL_DB_SEAHUB_DB_NAME'], 'old_hub')
        self.assertEqual(self.config.get('database', 'password'), 'a%secret')
        env['DB_HOST'] = 'empty-candidate'
        with self.assertRaisesRegex(native.NativeStartupError, 'BINDING_CHANGED'):
            native.native_environment(self.config, previous, env)

    def test_native_major_upgrade_requires_original_seafile_scripts(self):
        stamp = self.root / 'current_version'
        stamp.write_text('13.0.12\n')
        with self.assertRaisesRegex(native.NativeStartupError, 'NATIVE_UPGRADE_REQUIRED'):
            native.require_native_ce14(self.root)
        self.assertEqual(stamp.read_text(), '13.0.12\n')
        stamp.write_text('14.0.8\n')
        native.require_native_ce14(self.root)

    def test_native_env_password_hash_character_is_preserved(self):
        (self.root / '.env').write_text('SEAFILE_MYSQL_DB_PASSWORD=p#q\n')
        env = {}
        native.load_native_environment(self.root, env)
        self.assertEqual(env['SEAFILE_MYSQL_DB_PASSWORD'], 'p#q')

    def test_native_reader_owns_object_and_path_validation(self):
        api = MagicMock()
        # An empty list is a valid native empty root. None means missing/unreadable.
        api.list_dir_by_path.return_value = []
        native.verify_native_reads([REPO], api)
        api.list_dir_by_path.assert_called_once_with(REPO, '/', 0, 1)
        api.list_dir_by_path.return_value = None
        with self.assertRaisesRegex(native.NativeStartupError, 'NATIVE_REPO_UNREADABLE'):
            native.verify_native_reads([REPO], api)
        api.list_dir_by_path.side_effect = RuntimeError('do not disclose native staff/file details')
        with self.assertRaises(native.NativeStartupError) as caught:
            native.verify_native_reads([REPO], api)
        self.assertNotIn('staff/file', str(caught.exception))

if __name__ == '__main__':
    unittest.main()
