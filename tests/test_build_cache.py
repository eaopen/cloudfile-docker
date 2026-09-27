"""Exercise the real dependency cache shell function without network or Docker."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'build/seafile_14.0/seafile-build.sh'
FUNCTION = SCRIPT.read_text().split('function install_python_dependencies() {', 1)[1].split(
    'function clone_code()', 1)[0]
FUNCTION = 'function install_python_dependencies() {' + FUNCTION


@unittest.skipUnless(subprocess.run(['sed', '--version'], capture_output=True).returncode == 0,
                     'builder cache tests require Linux GNU sed; run in CE14 image')
class BuildDependencyCacheTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / 'sources'
        for name in ('seafevents', 'seafdav', 'seahub'):
            path = self.source / name
            path.mkdir(parents=True)
            (path / 'requirements.txt').write_text('example-package==1\n')
        binary = self.root / 'bin'
        binary.mkdir()
        pip = binary / 'pip3'
        pip.write_text('#!' + sys.executable + '\n' + '''
import json, os, pathlib, sys
with open(os.environ['CF_PIP_CALLS'], 'a') as output:
    output.write(json.dumps(sys.argv[1:]) + '\\n')
if os.environ.get('CF_FAIL_PIP') == 'true':
    raise SystemExit(1)
target = pathlib.Path(sys.argv[sys.argv.index('-t') + 1])
(target / 'example_module.py').write_text('installed fixture dependency')
''')
        pip.chmod(0o755)
        self.calls = self.root / 'calls.jsonl'
        self.environment = {**os.environ, 'PATH': str(binary) + ':' + os.environ['PATH'],
            'CF_PIP_CALLS': str(self.calls), 'CLOUDFILE_BUILD_BASE_ID': 'fixture-base-a'}

    def run_install(self, **changes):
        return subprocess.run(['bash', '-c', 'set -euo pipefail; code_path=$1;\n'
            + FUNCTION + '\ninstall_python_dependencies', 'fixture', str(self.source)],
            env={**self.environment, **changes}, capture_output=True, text=True)

    def count(self):
        return len(self.calls.read_text().splitlines())

    def test_repeat_reuses_install_but_requirements_and_base_changes_invalidate(self):
        self.assertEqual(self.run_install().returncode, 0)
        self.assertEqual(self.run_install().returncode, 0)
        self.assertEqual(self.count(), 1)
        (self.source / 'seahub/requirements.txt').write_text('different-package==2\n')
        self.assertEqual(self.run_install().returncode, 0)
        self.assertEqual(self.count(), 2)
        self.assertEqual(self.run_install(CLOUDFILE_BUILD_BASE_ID='fixture-base-b').returncode, 0)
        self.assertEqual(self.count(), 3)

    def test_failed_refresh_preserves_last_complete_dependencies_and_marker(self):
        self.assertEqual(self.run_install().returncode, 0)
        marker = self.source / 'thirdpartdir/.cloudfile-requirements.sha256'
        previous = marker.read_bytes()
        result = self.run_install(CF_FORCE_THIRDPART_REFRESH='true', CF_FAIL_PIP='true')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(marker.read_bytes(), previous)
        self.assertTrue((marker.parent / 'example_module.py').is_file())
        self.assertEqual(self.run_install().returncode, 0)
        self.assertEqual(self.count(), 2)

    def test_unmarked_partial_dependencies_are_replaced_not_reused(self):
        target = self.source / 'thirdpartdir'
        target.mkdir()
        (target / 'stale_module.py').write_text('partial prior install')
        self.assertEqual(self.run_install().returncode, 0)
        self.assertEqual(self.count(), 1)
        self.assertFalse((target / 'stale_module.py').exists())
        self.assertTrue((target / '.cloudfile-requirements.sha256').is_file())


if __name__ == '__main__':
    unittest.main()
