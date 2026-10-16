import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('subject_settings', Path(__file__).resolve().parents[1] / 'build/v2/subject_settings.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def credentials():
    return dict(CF_DIRECTORY_URL='https://directory.test', CF_DIRECTORY_SECRET='s' * 32,
                CF_DIRECTORY_KEY_ID='test', CF_DIRECTORY_ISSUER='eap',
                CF_DIRECTORY_AUDIENCE='directory', CF_DIRECTORY_SERVICE_ID='cloudfile')


class SubjectSettingsTest(unittest.TestCase):
    def test_disabled_native_default_and_restart_preserves_credentials(self):
        self.assertFalse(m.subject_settings({}, {})['CF_V2_ACL_ENABLED'])
        first = m.subject_settings({}, dict(credentials(), CF_V2_ACL_ENABLED='true', CF_SUBJECT_TTL='60', CF_DIRECTORY_TIMEOUT='5'))
        self.assertEqual(m.subject_settings(first, {}), first)
        self.assertEqual(first['CF_SUBJECT_TTL'], 60)
        self.assertEqual(first['CF_ACL_PROVIDER'], 'etech')
        self.assertEqual(first['CF_ACL_SUBJECT_ENSURE'], 'cloudfile_ext.v2.runtime.ensure_acl_subject')

    def test_partial_static_mismatched_and_bad_numbers_fail_closed(self):
        for values in [dict(CF_V2_ACL_ENABLED='true'), dict(CF_DIRECTORY_TOKEN='old'),
                       dict(credentials(), CF_ACL_PROVIDER='other'), dict(credentials(), CF_ACL_SUBJECT_ENSURE='wrong'),
                       dict(CF_SUBJECT_TTL=True), dict(CF_SUBJECT_TTL='1801'),
                       dict(CF_DIRECTORY_TIMEOUT='0'), dict(CF_ACL_CACHE_TTL='301'), dict(CF_V2_ACL_ENABLED='yes')]:
            with self.subTest(keys=list(values)), self.assertRaises(ValueError):
                m.subject_settings({}, values)

    def test_native_config_preserves_other_sections_and_explicitly_controls_acl(self):
        content = '[database]\npassword=a%secret\n[cloudfile]\nother=keep\n'
        result = m.native_acl_config(content, True)
        self.assertIn('password = a%secret', result)
        self.assertIn('other = keep', result)
        self.assertIn('v2_acl_enabled = true', result)
        self.assertIn('v2_acl_enabled = false', m.native_acl_config(result, False))
