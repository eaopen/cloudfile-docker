"""Deployment DB selection must not split directory facts across databases."""
import importlib.util
from pathlib import Path
import unittest

path = Path(__file__).resolve().parents[1] / 'scripts/scripts_14.0/cloudfile-directory-schema.py'
spec = importlib.util.spec_from_file_location('directory_schema_command', path)
command = importlib.util.module_from_spec(spec)
spec.loader.exec_module(command)


class DirectorySchemaCommandTest(unittest.TestCase):
    def setUp(self):
        self.environment = dict(SEAFILE_MYSQL_DB_HOST='db', SEAFILE_MYSQL_DB_USER='owner',
            SEAFILE_MYSQL_DB_PASSWORD='test-only', SEAFILE_MYSQL_DB_SEAFILE_DB_NAME='seafile_db')

    def test_native_configuration_is_the_default(self):
        self.assertEqual(command.database_options(self.environment)['database'], 'seafile_db')

    def test_policy_host_must_use_the_same_database(self):
        policy = {'database': dict(host='db', port=3306, name='seafile_db')}
        command.database_options(self.environment, policy)
        for key, value in [('host', 'other'), ('port', 3307), ('name', 'seahub_db')]:
            with self.subTest(key=key):
                changed = {'database': dict(policy['database'], **{key: value})}
                with self.assertRaises(ValueError):
                    command.database_options(self.environment, changed)

    def test_missing_native_settings_do_not_fall_back_to_another_database(self):
        with self.assertRaises(ValueError):
            command.database_options({'CLOUDFILE_DB_NAME': 'other'})
