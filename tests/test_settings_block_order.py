"""Generated configuration must remain executable across repeated restarts."""
import ast
import os
import tempfile
import unittest
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[1] / 'scripts/scripts_14.0/bootstrap.py'
TREE = ast.parse(SOURCE.read_text())
FUNCTION = next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == '_replace_block')
NAMESPACE = {'exists': os.path.exists}
exec(compile(ast.Module(body=[FUNCTION], type_ignores=[]), str(SOURCE), 'exec'), NAMESPACE)
REPLACE = NAMESPACE['_replace_block']
BEGIN = '# --- CloudFile (generated, do not edit) ---'
END = '# --- end CloudFile ---'


class SettingsBlockOrderTest(unittest.TestCase):
    def test_restart_preserves_dependent_aliases_and_local_overrides(self):
        # DEV kept aliases after generated SSO settings. Appending the block
        # made those aliases raise NameError and prevented Web/worker startup.
        head = "SITE_NAME = 'fixture'\n"
        tail = "CF_DIRECTORY_URL = CF_SERVICE_SSO_DIRECTORY_URL\nCF_SERVICE_SSO_DIRECTORY_URL = 'local-override'\n"
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / 'seahub_settings.py'
            p.write_text(head + BEGIN + "\nCF_SERVICE_SSO_DIRECTORY_URL = 'old'\n" + END + '\n' + tail)
            for value in ['new', 'new', 'updated']:
                REPLACE(p, BEGIN, END, 'CF_SERVICE_SSO_DIRECTORY_URL = %r\n' % value)
                rendered = p.read_text()
                namespace = {}
                exec(compile(rendered, str(p), 'exec'), namespace)
                self.assertEqual(namespace['CF_DIRECTORY_URL'], value)
                self.assertEqual(namespace['CF_SERVICE_SSO_DIRECTORY_URL'], 'local-override')
                self.assertTrue(rendered.startswith(head))
                self.assertTrue(rendered.endswith(tail))

    def test_invalid_markers_never_truncate_operator_settings(self):
        for markers in [BEGIN, END, BEGIN + '\n' + BEGIN + '\n' + END, END + '\n' + BEGIN]:
            with self.subTest(markers=markers), tempfile.TemporaryDirectory() as directory:
                p = Path(directory) / 'seahub_settings.py'
                original = markers + "\nLOCAL_SETTING = 'keep'\n"
                p.write_text(original)
                with self.assertRaises(ValueError):
                    REPLACE(p, BEGIN, END, 'GENERATED = True\n')
                self.assertEqual(p.read_text(), original)

    def test_first_append_stays_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / 'seafile.conf'
            p.write_text('[fileserver]\nport = 8082\n')
            REPLACE(p, BEGIN, END, '[storage]\nname = fs\n')
            rendered = p.read_text()
            REPLACE(p, BEGIN, END, '[storage]\nname = fs\n')
            self.assertEqual(p.read_text(), rendered)


if __name__ == '__main__':
    unittest.main()
