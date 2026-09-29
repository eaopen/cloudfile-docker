import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / 'build/cloudfile_14.0/stamp-current-package.py'
SPEC = importlib.util.spec_from_file_location('stamp_current_package', SCRIPT)
STAMP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STAMP)


class CurrentPackageSourceTest(unittest.TestCase):
    def test_build_record_rejects_duplicate_missing_and_foreign_recipe(self):
        commit = 'a' * 40
        entries = [f'{name}: {commit}' for name in STAMP.SOURCE_NAMES]
        base = '\n'.join(['product: 14.0.8-cf.0-test',
            'cloudfile-docker: ' + commit, *entries]) + '\n'
        with tempfile.TemporaryDirectory() as temporary:
            info = Path(temporary) / 'cloudfile-build-info.txt'
            with patch.object(STAMP.subprocess, 'check_output', return_value=commit + '\n'):
                info.write_text(base)
                self.assertEqual(STAMP.build_sources(temporary, '14.0.8-cf.0-test'),
                    dict.fromkeys(STAMP.SOURCE_NAMES, commit))
                for invalid in (base + entries[0] + '\n',
                                base.replace(entries[0] + '\n', ''),
                                base.replace('cloudfile-docker: ' + commit,
                                             'cloudfile-docker: ' + 'b' * 40)):
                    info.write_text(invalid)
                    with self.assertRaises(ValueError):
                        STAMP.build_sources(temporary, '14.0.8-cf.0-test')
