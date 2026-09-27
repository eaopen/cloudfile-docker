"""Application assembly must reuse native bytes and preserve other entrypoints."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest

BUILD = Path(__file__).resolve().parents[1] / 'build/seafile_14.0'
sys.path.insert(0, str(BUILD))
from assemble_application import assemble
from package_provenance import preserved_digest, verify_package
import test_package_provenance as fixtures


class ApplicationAssemblyTests(unittest.TestCase):
    def setUp(self):
        fixtures.PackageProvenanceTests.setUp(self)
        cache = self.package / 'seafile/lib/python3/__pycache__/native.pyc'
        cache.parent.mkdir(parents=True)
        cache.write_bytes(b'captured native dependency cache')
        self.hub = self.root / 'hub'
        self.hub.mkdir()
        def git(*args):
            return subprocess.check_output(['git', '-C', str(self.hub), *args], text=True).strip()
        git('init', '-q')
        git('config', 'user.name', 'Fixture')
        git('config', 'user.email', 'fixture@example.invalid')
        for name in ('seahub/settings.py', 'cloudfile_extensions/apps.py', 'frontend/source.js'):
            path = self.hub / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('old source\n')
        git('add', '.')
        git('commit', '-qm', 'base')
        old = git('rev-parse', 'HEAD')
        self.captured['manifest']['sources']['seahub']['ref'] = old
        self.captured['source_commits']['seahub'] = old
        (self.hub / 'cloudfile_extensions/apps.py').write_text('new source\n')
        git('add', '.')
        git('commit', '-qm', 'current')
        current = git('rev-parse', 'HEAD')
        assets = self.package / 'seahub/media/assets/frontend/static/js'
        assets.mkdir(parents=True)
        for name in ('old.js', 'admin.js'):
            (assets / name).write_bytes(name.encode())
        stats = self.package / 'seahub/frontend/webpack-stats.pro.json'
        stats.parent.mkdir(parents=True)
        stats.write_text(json.dumps(dict(status='done', assets={}, chunks={
            'app': ['static/js/old.js'], 'admin': ['static/js/admin.js']})))
        (self.package / 'seahub/media/assets/staticfiles.json').write_text(json.dumps(dict(paths={}, hash='', version='1.1')))
        # Stamp the base against its own older manifest.
        self.manifest_path.write_text(json.dumps(self.captured['manifest']))
        fixtures.PackageProvenanceTests.stamp(self)
        self.manifest = json.loads(self.manifest_path.read_text())
        self.manifest['sources']['seahub']['ref'] = current
        self.manifest_path.write_text(json.dumps(self.manifest))
        compiled = self.root / 'app.js'
        compiled.write_bytes(b'compiled new app')
        self.stats = self.root / 'stats.json'
        self.stats.write_text(json.dumps(dict(status='done', chunks={'app': ['static/js/app.hash.js']},
            assets={'static/js/app.hash.js': dict(name='static/js/app.hash.js', path=str(compiled))})))
        self.evidence = self.root / 'evidence.json'
        self.evidence.write_text(json.dumps(dict(source_commits={'cloudfile-hub': current},
            frontend_compile=dict(passed=True, entry='app', assets_sha256={
                'static/js/app.hash.js': hashlib.sha256(compiled.read_bytes()).hexdigest()}))))
        self.output = self.root / 'assembled'

    def run_assembly(self):
        return assemble(self.package, self.hub, self.output, self.manifest_path, self.stats, self.evidence)

    def test_new_hub_preserves_native_bytes_admin_bundle_and_base(self):
        before = preserved_digest(self.package)
        record = self.run_assembly()
        self.assertEqual(preserved_digest(self.output), before)
        self.assertEqual(verify_package(self.output, self.manifest_path), record)
        self.assertEqual((self.output / 'seahub/cloudfile_extensions/apps.py').read_text(), 'new source\n')
        stats = json.loads((self.output / 'seahub/frontend/webpack-stats.pro.json').read_text())
        self.assertEqual(stats['chunks']['admin'], ['static/js/admin.js'])
        self.assertEqual(stats['chunks']['app'], ['static/js/app.hash.js'])
        self.assertTrue((self.package / 'seahub/media/assets/frontend/static/js/old.js').exists())

    def test_changed_native_pin_refuses_reuse_without_creating_output(self):
        self.manifest['sources']['seafile-server']['ref'] = 'a' * 40
        self.manifest_path.write_text(json.dumps(self.manifest))
        with self.assertRaisesRegex(ValueError, 'non-Hub'):
            self.run_assembly()
        self.assertFalse(self.output.exists())

    def test_unverified_frontend_bytes_refuse_publication(self):
        (self.root / 'app.js').write_bytes(b'unverified')
        with self.assertRaisesRegex(ValueError, 'compiled asset'):
            self.run_assembly()
        self.assertFalse(self.output.exists())

