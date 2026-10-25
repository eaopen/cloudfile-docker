"""Isolated validation of the OFF / OPTIONAL repository configuration.

No Docker, database, or CloudFile runtime is needed.
"""
import ast
import uuid
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / 'scripts/scripts_cf14.0/cloudfile_bootstrap.py'
TREE = ast.parse(SOURCE.read_text())
METHODS = {'_checkout_repo_ids', '_seafile_conf_cloudfile_lines'}
FUNCTIONS = [node for node in TREE.body if isinstance(node, ast.FunctionDef) and node.name in METHODS]


class CheckoutRepoConfigTest(unittest.TestCase):
    def setUp(self):
        self.env = {}
        self.namespace = {
            'uuid': uuid,
            'get_conf': lambda name, default='': self.env.get(name, default),
            'cf_enabled': lambda name: self.env.get(name, 'false') == 'true',
            'CF_FEATURE_SWITCHES': ('CF_ENABLE_CHECKOUT',),
        }
        exec(compile(ast.Module(body=FUNCTIONS, type_ignores=[]), str(SOURCE), 'exec'),
             self.namespace)

    def test_no_selection_means_all_off(self):
        self.assertEqual(self.namespace['_checkout_repo_ids'](), ())
        rendered = ''.join(self.namespace['_seafile_conf_cloudfile_lines']())
        self.assertIn('checkout_enabled = false\n', rendered)
        self.assertIn('checkout_repo_ids = \n', rendered)

    def test_global_switch_alone_does_not_enable_any_repo(self):
        self.env['CF_ENABLE_CHECKOUT'] = 'true'
        self.assertEqual(self.namespace['_checkout_repo_ids'](), ())
        self.assertIn('checkout_repo_ids = \n',
                      ''.join(self.namespace['_seafile_conf_cloudfile_lines']()))

    def test_selected_repo_is_rendered_once(self):
        repo = '11111111-1111-4111-8111-111111111111'
        self.env.update(CF_ENABLE_CHECKOUT='true', CF_CHECKOUT_REPOS=repo)
        self.assertEqual(self.namespace['_checkout_repo_ids'](), (repo,))
        self.assertIn('checkout_repo_ids = ' + repo + '\n',
                      ''.join(self.namespace['_seafile_conf_cloudfile_lines']()))

    def test_invalid_lists_rejected_before_config_write(self):
        good = '11111111-1111-4111-8111-111111111111'
        for value in ['not-a-uuid', good + ',', good + ',' + good,
                      'AAAAAAAA-AAAA-4AAA-AAAA-AAAAAAAAAAAA', 'x' * 8193]:
            self.env['CF_CHECKOUT_REPOS'] = value
            with self.subTest(value=value[:40]), self.assertRaises(ValueError):
                self.namespace['_checkout_repo_ids']()


if __name__ == '__main__':
    unittest.main()
