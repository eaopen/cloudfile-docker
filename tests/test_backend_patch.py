"""Refuse native/frontend drift before backend-only application reuse."""
import sys
from pathlib import Path
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'build/seafile_14.0'))
from assemble_backend_patch import changed_paths


class BackendPatchTests(unittest.TestCase):
    def test_only_extensions_changes_are_admitted(self):
        with patch('assemble_backend_patch._git', return_value='cloudfile_extensions/jobs/worker.py'):
            self.assertEqual(changed_paths('/hub', 'old', 'new'), ['cloudfile_extensions/jobs/worker.py'])

    def test_empty_frontend_native_and_escape_changes_require_other_recipe(self):
        for paths in ('', 'frontend/package.json', 'seahub/settings.py',
                      'cloudfile_extensions/../seahub/settings.py',
                      'cloudfile_extensions/jobs/worker.py\nfrontend/src/app.js'):
            with self.subTest(paths=paths), patch('assemble_backend_patch._git', return_value=paths):
                with self.assertRaises(ValueError):
                    changed_paths('/hub', 'old', 'new')
