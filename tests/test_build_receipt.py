"""Remote resolution, fail-closed source locks and test evidence."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'build/cloudfile_14.0'))
import build_receipt as receipt
from source_manifest import load_manifest


class ReceiptTests(unittest.TestCase):
    def resolve(self):
        def remote(argv, **kwargs):
            return 'a' * 40 + '\t' + argv[-1] + '\n'
        with patch.object(receipt.subprocess, 'check_output', side_effect=remote) as call:
            result = receipt.resolve(ROOT / 'release.yaml', '14.0.8-storage-test')
        self.assertEqual(call.call_count, 3)
        self.assertTrue(all(c.args[0][1:3] == ['ls-remote', '--exit-code'] for c in call.call_args_list))
        self.assertEqual(set(result['requested_branches'].values()), {'dev'})
        return result

    def test_resolve_once_and_generate_only_immutable_source_lock(self):
        result = self.resolve()
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'build-receipt.json'
            receipt.atomic_json(target, result)
            loaded = receipt.load_receipt(target)
            self.assertEqual(load_manifest(target), loaded['lock'])
            self.assertEqual(loaded['lock']['docker_commit'], 'a' * 40)
            self.assertEqual(len(loaded['lock']['sources']), 7)
            self.assertEqual(loaded['tests'], {})
            self.assertIsNone(loaded['image'])

    def test_remote_failure_never_returns_cached_sha(self):
        with patch.object(receipt.subprocess, 'check_output',
                          side_effect=subprocess.CalledProcessError(128, 'git')):
            with self.assertRaises(subprocess.CalledProcessError):
                receipt.resolve(ROOT / 'release.yaml', '14.0.8-storage-test')

    def test_ambiguous_missing_or_wrong_ref_is_rejected(self):
        for result in ('', 'a' * 40 + '\trefs/heads/other\n',
                       'a' * 40 + '\trefs/heads/dev\n' + 'b' * 40 + '\trefs/heads/dev\n'):
            with self.subTest(result=result), patch.object(receipt.subprocess, 'check_output', return_value=result):
                with self.assertRaises(ValueError):
                    receipt.resolve(ROOT / 'release.yaml', '14.0.8-storage-test')

    def test_exact_recipe_and_clean_worktree_required(self):
        resolved = self.resolve()
        for replies in (['b' * 40], ['a' * 40, ' M release.yaml\n']):
            with patch.object(receipt.subprocess, 'check_output', side_effect=replies):
                with self.assertRaises(ValueError):
                    receipt.verify_recipe(resolved, ROOT)
        with patch.object(receipt.subprocess, 'check_output', side_effect=['a' * 40, '']):
            receipt.verify_recipe(resolved, ROOT)

    def test_bad_receipt_cannot_masquerade_as_branch_configuration(self):
        result = self.resolve()
        result['lock']['sources']['seahub']['ref'] = 'dev'
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'receipt.json'
            receipt.atomic_json(target, result)
            with self.assertRaisesRegex(ValueError, 'immutable'):
                receipt.load_receipt(target)

    def test_test_status_cli_and_log_digest_survive_reloading(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'receipt.json'
            receipt.atomic_json(target, self.resolve())
            subprocess.run([sys.executable, str(ROOT / 'build/cloudfile_14.0/build_receipt.py'),
                            'test', str(target), 'local_storage', 'failed', '--command',
                            'bash tests/local_storage/run.sh', '--log-sha256', 'b' * 64],
                           check=True, capture_output=True)
            loaded = receipt.load_receipt(target)
            self.assertEqual(loaded['tests']['local_storage']['status'], 'failed')
            self.assertEqual(loaded['tests']['local_storage']['log_sha256'], 'b' * 64)

    def test_ref_inputs_cannot_select_old_sha_as_default_branch(self):
        with self.assertRaises(ValueError):
            receipt.resolve(ROOT / 'release.yaml', '14.0.8-storage-test', {'seafile-server': 'a' * 40})


if __name__ == '__main__':
    unittest.main()
