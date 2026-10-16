import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest


spec = importlib.util.spec_from_file_location('v2_sources', Path(__file__).resolve().parents[1] / 'tools/prepare-v2-source.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class SourceAssemblyTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.config = {'format': 1, 'ce_version': '14.0.8', 'components': {}}
        self.refs = {}
        for name, target, overlay in (('cloudfile-server', 'seafile-server', 'scripts/sql/mysql/cloudfile-v2.sql'),
                                       ('cloudfile-hub', 'seahub', 'cloudfile_ext/v2')):
            repo = self.root / name
            repo.mkdir()
            self.git(repo, 'init', '-q')
            self.git(repo, 'config', 'user.name', 'V2 Source Test')
            self.git(repo, 'config', 'user.email', 'test@example.invalid')
            (repo / 'native.txt').write_text('fixed upstream file')
            self.git(repo, 'add', '.')
            self.git(repo, 'commit', '-qm', 'native fixture')
            base = self.git(repo, 'rev-parse', 'HEAD').strip()
            # Pollute the fork HEAD and prove the assembled source excludes it.
            (repo / 'native.txt').write_text('unreviewed fork modification')
            (repo / 'cloudfile_extensions').mkdir()
            (repo / 'cloudfile_extensions/legacy.py').write_text('old_framework = True')
            extension = repo / (overlay if overlay.endswith('.sql') else overlay + '/__init__.py')
            extension.parent.mkdir(parents=True, exist_ok=True)
            extension.write_text('-- reviewed DDL' if extension.suffix == '.sql' else '"""Isolated V2 adapter."""\n')
            self.git(repo, 'add', '.')
            self.git(repo, 'commit', '-qm', 'fork fixture with unrelated legacy code')
            self.config['components'][name] = {'directory': target, 'native_commit': base, 'overlay': [overlay]}
            self.refs[name] = 'HEAD'

    def tearDown(self):
        self.directory.cleanup()

    @staticmethod
    def git(repo, *args):
        return subprocess.check_output(['git', '-C', str(repo), *args], text=True)

    def test_head_history_and_legacy_files_cannot_enter_prepared_source(self):
        output = self.root / 'prepared'
        receipt = module.assemble(self.root, output, self.config, self.refs)
        for name, config in self.config['components'].items():
            target = output / config['directory']
            self.assertEqual((target / 'native.txt').read_text(), 'fixed upstream file')
            self.assertFalse((target / 'cloudfile_extensions').exists())
            self.assertEqual(receipt['components'][name]['native_commit'], config['native_commit'])
            self.assertTrue(receipt['components'][name]['overlay_sha256'])
        with self.assertRaises(ValueError):
            module.assemble(self.root, output, self.config, self.refs)

    def test_overlay_cannot_replace_a_native_file(self):
        self.config['components']['cloudfile-hub']['overlay'] = ['native.txt']
        output = self.root / 'failed'
        with self.assertRaises(ValueError):
            module.assemble(self.root, output, self.config, self.refs)
        self.assertFalse(output.exists())

    def test_absolute_legacy_import_is_rejected(self):
        self._bad_import('from cloudfile_extensions.jobs.store import JobStore\n')

    def test_relative_import_cannot_escape_isolated_package(self):
        self._bad_import('from .. import registry\n')

    def _bad_import(self, source):
        repo = self.root / 'cloudfile-hub'
        (repo / 'cloudfile_ext/v2/__init__.py').write_text(source)
        self.git(repo, 'add', '.')
        self.git(repo, 'commit', '-qm', 'bad dependency fixture')
        with self.assertRaises(ValueError):
            module.assemble(self.root, self.root / 'failed', self.config, self.refs)
        self.assertFalse((self.root / 'failed').exists())
