"""V2 startup configuration; real rendering with an explicit Hub CLI double."""
import ast
import contextlib
import os
import sys
from configparser import ConfigParser
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

SOURCE = Path(__file__).resolve().parents[1] / 'scripts/scripts_14.0/library_storage.py'
SPEC = importlib.util.spec_from_file_location('library_storage_config_test', SOURCE)
storage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(storage)


class LibraryStorageConfigTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir='/private/tmp' if Path('/private/tmp').exists() else None)
        self.addCleanup(self.directory.cleanup)
        self.top = Path(self.directory.name)
        (self.top / 'conf').mkdir()
        (self.top / 'seafile-data').mkdir()
        self.conf = self.top / 'conf/seafile.conf'
        self.root = self.top / 'libraries'
        self.root.mkdir()
        self.installdir = self.top / 'server'
        (self.installdir / 'seahub').mkdir(parents=True)
        self.conf.write_text('[database]\nhost = persisted-db\n')
        self.original = self.conf.read_text()
        self.calls = []
        self.env = dict(CF_LIBRARY_STORAGE='auto', SEAFILE_MYSQL_DB_HOST='existing-db',
                        SEAFILE_MYSQL_DB_PASSWORD='secret', SEAFILE_MYSQL_DB_SEAFILE_DB_NAME='original_db',
                        CF_STORAGE_CLASSES_JSON='new-env-must-not-override-persisted',
                        SEAFILE_DATA_DIR='/stale-data', SEAFILE_CENTRAL_CONF_DIR='/stale-conf')
        self.root_patch = patch.object(storage, 'LIBRARY_ROOT', str(self.root))
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)

    def cli(self, command, **kwargs):
        candidate = Path(command[command.index('--seafile-conf') + 1])
        config = ConfigParser(interpolation=None)
        config.read(candidate)
        self.assertEqual(str(self.root), config['cloudfile_v2']['auto_local_root'])
        self.assertEqual('persisted-db', config['database']['host'])
        self.assertEqual('existing-db', kwargs['env']['CF_V2_DB_HOST'])
        self.assertEqual('original_db', kwargs['env']['CF_V2_DB_NAME'])
        self.assertNotIn('secret', command)
        self.assertNotIn('CF_STORAGE_CLASSES_JSON', kwargs['env'])
        self.assertEqual(str((self.top / 'seafile-data').resolve()), kwargs['env']['SEAFILE_DATA_DIR'])
        self.assertEqual(str(self.conf.parent.resolve()), kwargs['env']['SEAFILE_CENTRAL_CONF_DIR'])
        self.assertEqual(str((self.top / 'seafile-data').resolve()), command[command.index('--seafile-data') + 1])
        self.calls.append((command, config))
        return self.report(command)

    def report(self, command, *, blocked=0, pinned=0, code=0):
        return subprocess.CompletedProcess(command, code, json.dumps(dict(
            mode='apply' if command[-1] == '--apply' else 'dry-run',
            summary={'BLOCKED': blocked, 'NATIVE_CLASS_PINNED': pinned}, items=[], orphan_directories=[])) + '\n', '')

    def configure(self, cli=None):
        with patch.object(storage.subprocess, 'run', side_effect=cli or self.cli), contextlib.redirect_stdout(io.StringIO()) as output:
            storage.configure_auto_storage(self.conf, '[cloudfile]\nexample = true\n', self.installdir, self.env)
        return output.getvalue()

    def bootstrap_writer(self, environment, lines=('[cloudfile]\nexample = true\n',)):
        source = SOURCE.with_name('bootstrap.py')
        names = {'write_cloudfile_seafile_conf', '_replace_block'}
        nodes = [node for node in ast.parse(source.read_text()).body
                 if isinstance(node, ast.FunctionDef) and node.name in names]
        namespace = dict(os=os, json=json, join=os.path.join, exists=os.path.exists,
                         topdir=str(self.top), installdir=str(self.installdir),
                         CF_BEGIN=storage.BEGIN, CF_END=storage.END,
                         get_conf=lambda key, default='': environment.get(key, default),
                         cf_enabled=lambda key: environment.get(key, 'false') == 'true',
                         logwarning=lambda message: None,
                         _seafile_conf_cloudfile_lines=lambda: list(lines))
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), 'exec'), namespace)
        return namespace['write_cloudfile_seafile_conf']

    def test_interrupted_fresh_initialization_retains_auto_intent(self):
        source = SOURCE.with_name('bootstrap.py')
        node = next(node for node in ast.parse(source.read_text()).body
                    if isinstance(node, ast.FunctionDef) and node.name == 'init_seafile_server')
        marker = self.top / '.cloudfile-schema-init-pending'
        marker.touch()
        namespace = dict(exists=os.path.exists, join=os.path.join, shared_seafiledir=str(self.top),
                         get_version_stamp_file=Mock(side_effect=StopIteration))
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), 'exec'), namespace)
        with self.assertRaises(StopIteration):
            namespace['init_seafile_server']()
        self.assertTrue(namespace['_cloudfile_fresh_install'])
        marker.unlink()
        with self.assertRaises(StopIteration):
            namespace['init_seafile_server']()
        self.assertFalse(namespace['_cloudfile_fresh_install'])

    def test_bootstrap_legacy_multi_survives_environment_overlay_removal(self):
        self.conf.write_text(self.original + storage.BEGIN + '\n[cloudfile]\nexample = true\n' +
                             '[storage]\nenable_storage_classes = true\nstorage_classes_file = existing.json\n' +
                             '[block_backend]\nname = multiple\n' + storage.END + '\n')
        with patch.dict(sys.modules, {'library_storage': storage}), patch.dict(os.environ, {}, clear=True):
            self.bootstrap_writer({})()
        config = ConfigParser(interpolation=None)
        config.read(self.conf)
        self.assertEqual('existing.json', config['storage']['storage_classes_file'])
        self.assertEqual('multiple', config['block_backend']['name'])
        self.assertFalse(config.has_section('cloudfile_v2'))

    def test_bootstrap_legacy_multi_keeps_automatic_allocator_switch(self):
        self.conf.write_text(self.original + storage.BEGIN + '\n[cloudfile]\ns3_storage_enabled = true\n' +
                             '[storage]\nenable_storage_classes = true\nstorage_classes_file = existing.json\n' +
                             '[block_backend]\nname = multiple\n' + storage.END + '\n')
        generated = ('[cloudfile]\n', 's3_storage_enabled = false\n')
        with patch.dict(sys.modules, {'library_storage': storage}), patch.dict(os.environ, {}, clear=True):
            self.bootstrap_writer({'CF_ENABLE_S3_STORAGE': 'false'}, generated)()
        config = ConfigParser(interpolation=None)
        config.read(self.conf)
        self.assertEqual('true', config['cloudfile']['s3_storage_enabled'])
        self.assertEqual('multiple', config['block_backend']['name'])

    def test_bootstrap_without_retained_multi_keeps_switch_disabled(self):
        self.conf.write_text(self.original + storage.BEGIN + '\n[cloudfile]\ns3_storage_enabled = true\n' +
                             storage.END + '\n')
        generated = ('[cloudfile]\n', 's3_storage_enabled = false\n')
        with patch.dict(sys.modules, {'library_storage': storage}), patch.dict(os.environ, {}, clear=True):
            self.bootstrap_writer({'CF_ENABLE_S3_STORAGE': 'false'}, generated)()
        config = ConfigParser(interpolation=None)
        config.read(self.conf)
        self.assertEqual('false', config['cloudfile']['s3_storage_enabled'])
        self.assertFalse(config.has_section('storage'))

    def test_bootstrap_s3_switch_without_removed_overlay_type_keeps_multi(self):
        original = self.original + storage.BEGIN + '\n[cloudfile]\nexample = true\n' + (
            '[storage]\nenable_storage_classes = true\nstorage_classes_file = existing.json\n' +
            ''.join('[%s]\nname = multiple\n' % section for section in
                    ('commit_object_backend', 'fs_object_backend', 'block_backend'))) + storage.END + '\n'
        self.conf.write_text(original)
        environment = {'CF_ENABLE_S3_STORAGE': 'true', 'SEAF_SERVER_STORAGE_TYPE': ''}
        with patch.dict(sys.modules, {'library_storage': storage}), patch.dict(os.environ, environment, clear=True):
            self.bootstrap_writer(environment)()
        config = ConfigParser(interpolation=None)
        config.read(self.conf)
        self.assertEqual('existing.json', config['storage']['storage_classes_file'])
        self.assertEqual('true', config['storage']['enable_storage_classes'])
        for section in ('commit_object_backend', 'fs_object_backend', 'block_backend'):
            self.assertEqual('multiple', config[section]['name'])
        self.assertFalse(config.has_section('cloudfile_v2'))
        self.assertNotIn('auto_local_root', self.conf.read_text())

    def test_bootstrap_explicit_auto_ignores_legacy_s3_variable(self):
        environment = dict(self.env, CF_ENABLE_S3_STORAGE='true', SEAF_SERVER_STORAGE_TYPE='multiple')
        with patch.dict(sys.modules, {'library_storage': storage}), patch.dict(os.environ, environment, clear=True), \
                patch.object(storage.subprocess, 'run', side_effect=self.cli), contextlib.redirect_stdout(io.StringIO()):
            self.bootstrap_writer(environment)()
        self.assertIn('enable_storage_classes = false', self.conf.read_text())
        self.assertNotIn('name = multiple', self.conf.read_text())

    def test_new_install_defaults_auto_but_existing_unset_is_legacy(self):
        self.assertTrue(storage.auto_storage_enabled(self.conf, {}, fresh=True))
        self.assertFalse(storage.auto_storage_enabled(self.conf, {}))
        self.assertFalse(storage.auto_storage_enabled(self.conf, {'CF_ENABLE_S3_STORAGE': 'true', 'SEAF_SERVER_STORAGE_TYPE': 'multiple'}, fresh=True))
        self.assertTrue(storage.auto_storage_enabled(self.conf, self.env))
        with self.assertRaises(ValueError):
            storage.auto_storage_enabled(self.conf, {'CF_LIBRARY_STORAGE': 'legacy'})

    def test_new_auto_uses_filesystem_and_reconciles_before_write(self):
        output = self.configure()
        config = ConfigParser(interpolation=None)
        config.read(self.conf)
        self.assertEqual(['--dry-run', '--apply'], [call[0][-1] for call in self.calls])
        self.assertEqual('false', config['storage']['enable_storage_classes'])
        self.assertEqual(str(self.root), config['cloudfile_v2']['auto_local_root'])
        for section in ('commit_object_backend', 'fs_object_backend', 'block_backend'):
            self.assertEqual('filesystem', config[section]['name'])
        self.assertEqual('persisted-db', config['database']['host'])
        self.assertEqual(2, len(output.splitlines()))
        self.assertTrue(storage.auto_storage_enabled(self.conf, {}))
        self.assertEqual([], list(self.conf.parent.glob('.storage-*')))

    def test_native_layout_symlinks_are_resolved_but_managed_root_is_not(self):
        shared = self.top / 'shared-seafile'
        shared.mkdir()
        (shared / 'seafile-data').mkdir()
        (self.top / 'seafile-data').rmdir()
        (self.top / 'seafile-data').symlink_to(shared / 'seafile-data', target_is_directory=True)
        (self.top / 'conf').rename(shared / 'conf')
        (self.top / 'conf').symlink_to(shared / 'conf', target_is_directory=True)
        self.configure()
        for command, _ in self.calls:
            self.assertEqual(str(shared / 'seafile-data'), command[command.index('--seafile-data') + 1])
        config = ConfigParser(interpolation=None)
        config.read(self.conf)
        self.assertEqual(str(self.root), config['cloudfile_v2']['auto_local_root'])

    def test_explicit_transition_inventories_original_classes(self):
        self.conf.write_text(self.original + '[storage]\nenable_storage_classes = true\nstorage_classes_file = existing.json\n[block_backend]\nname = multiple\n')
        self.configure()
        for command, config in self.calls:
            self.assertEqual('existing.json', config['storage']['storage_classes_file'])
            self.assertEqual('multiple', config['block_backend']['name'])
        self.assertNotIn('existing.json', self.conf.read_text())

    def test_schema_missing_and_state_drift_allow_explicit_apply(self):
        for status in ('SCHEMA_MISSING', 'STATE_DRIFT'):
            with self.subTest(status=status):
                modes = []
                def cli(command, **kwargs):
                    modes.append(command[-1])
                    report = json.loads(self.cli(command, **kwargs).stdout)
                    report['summary'][status] = 1
                    report['schema'] = {'status': status if status == 'SCHEMA_MISSING' else 'READY'}
                    return subprocess.CompletedProcess(command, 0, json.dumps(report), '')
                self.configure(cli)
                self.assertEqual(['--dry-run', '--apply'], modes)
                self.assertIn('name = filesystem', self.conf.read_text())

    def test_preflight_blocked_or_pinned_does_not_write_or_apply(self):
        for blocked, pinned in ((1, 0), (0, 1)):
            with self.subTest(blocked=blocked, pinned=pinned):
                calls = []
                def cli(command, **kwargs):
                    calls.append(command)
                    return self.report(command, blocked=blocked, pinned=pinned)
                with self.assertRaises(RuntimeError):
                    self.configure(cli)
                self.assertEqual(self.original, self.conf.read_text())
                self.assertEqual(1, len(calls))

    def test_apply_failure_leaves_original_configuration(self):
        def cli(command, **kwargs):
            return self.report(command, blocked=int(command[-1] == '--apply'), code=2 if command[-1] == '--apply' else 0)
        with self.assertRaises(RuntimeError):
            self.configure(cli)
        self.assertEqual(self.original, self.conf.read_text())
        self.assertEqual([], list(self.conf.parent.glob('.storage-*')))

    def test_cli_exit_failure_invalid_json_or_missing_summary_refuses(self):
        for output, code in (('not JSON', 0), ('{}', 0), ('{"summary": {"BLOCKED": "0"}}', 0), ('{"summary": {}}', 1)):
            with self.subTest(output=output), self.assertRaises(RuntimeError):
                self.configure(lambda command, **kwargs: subprocess.CompletedProcess(command, code, output, 'private driver error'))
            self.assertEqual(self.original, self.conf.read_text())

    def test_root_missing_file_symlink_or_symlink_ancestor_refuses(self):
        self.root.rmdir()
        for kind in ('missing', 'file', 'symlink', 'ancestor'):
            with self.subTest(kind=kind):
                if kind == 'file':
                    self.root.write_text('not directory')
                elif kind == 'symlink':
                    self.root.unlink()
                    self.root.symlink_to(self.top, target_is_directory=True)
                elif kind == 'ancestor':
                    self.root.unlink()
                    link = self.top / 'linked'
                    link.symlink_to(self.top, target_is_directory=True)
                    storage.LIBRARY_ROOT = str(link / 'conf')
                with patch.object(storage.subprocess, 'run') as run, self.assertRaises(ValueError):
                    storage.configure_auto_storage(self.conf, '', self.installdir, self.env)
                run.assert_not_called()
                self.assertEqual(self.original, self.conf.read_text())
        self.assertFalse(self.root.exists())

    def test_restart_is_idempotent_without_changing_other_configuration(self):
        self.configure()
        rendered = self.conf.read_text()
        self.configure()
        self.assertEqual(rendered, self.conf.read_text())

    def test_malformed_markers_refuse_before_inventory_and_write(self):
        self.conf.write_text(self.original + storage.BEGIN + '\n')
        with patch.object(storage.subprocess, 'run') as run, self.assertRaises(ValueError):
            storage.configure_auto_storage(self.conf, '', self.installdir, self.env)
        run.assert_not_called()
        self.assertEqual(self.original + storage.BEGIN + '\n', self.conf.read_text())


if __name__ == '__main__':
    unittest.main()
