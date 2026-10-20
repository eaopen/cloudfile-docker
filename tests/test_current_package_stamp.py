"""Receipt source checks do not consult stale local dev branches."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('stamp', ROOT / 'build/cloudfile_14.0/stamp-current-package.py')
STAMP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STAMP)


class CurrentPackageSourceTest(unittest.TestCase):
    def test_duplicate_missing_source_records_are_rejected(self):
        commit = 'a' * 40
        base = '\n'.join(['product: 14.0.8-storage-test', 'cloudfile-docker: ' + commit,
            *[name + ': ' + commit for name in STAMP.SOURCE_NAMES]]) + '\n'
        with tempfile.TemporaryDirectory() as directory:
            info = Path(directory) / 'cloudfile-build-info.txt'
            info.write_text(base)
            self.assertEqual(STAMP.build_sources(directory, '14.0.8-storage-test')['seahub'], commit)
            for invalid in (base + 'seahub: ' + commit + '\n', base.replace('seahub: ' + commit + '\n', '')):
                info.write_text(invalid)
                with self.assertRaises(ValueError):
                    STAMP.build_sources(directory, '14.0.8-storage-test')

    def test_moving_local_refs_are_never_used_to_stamp(self):
        source = (ROOT / 'build/cloudfile_14.0/stamp-current-package.py').read_text()
        self.assertNotIn('rev-parse', source)
        self.assertNotIn('current_manifest', source)
        self.assertIn('load_receipt', source)
