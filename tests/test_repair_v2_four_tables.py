"""Lossless DEV projections must reject data the four-table contract cannot hold."""
import hashlib
import importlib.util
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location('four_table_repair', Path(__file__).resolve().parents[1] / 'tools/repair-v2-four-tables.py')
REPAIR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REPAIR)


class FourTableRepairTest(unittest.TestCase):
    def acl(self):
        return dict(repo_id='01234567-89ab-cdef-0123-456789abcdef', path='/目录/a',
                    path_hash=hashlib.sha256('/目录/a'.encode()).hexdigest(),
                    subject_type='user', provider='fixture', namespace='user',
                    external_id='1', permission='rw', inherit=1, share_mode=0,
                    revision='01234567-89ab-cdef-0123-456789abcdef', kind='dir',
                    lifecycle_ref='retained-in-private-backup')

    def test_acl_preserves_rules_and_converts_hash_to_binary(self):
        source = self.acl()
        target = REPAIR.project('cf_dir_acl', [source])[0]
        self.assertEqual(len(target['path_hash']), 32)
        self.assertEqual(target['path_hash'].hex(), source['path_hash'])
        self.assertEqual(set(target), set(REPAIR.TARGET_COLUMNS['cf_dir_acl']))
        for column in target:
            if column != 'path_hash': self.assertEqual(target[column], source[column])

    def test_hash_corruption_and_file_scope_have_no_silent_conversion(self):
        for changed in (dict(path_hash='00'*32), dict(kind='file')):
            source = self.acl(); source.update(changed)
            with self.assertRaises(RuntimeError): REPAIR.project('cf_dir_acl', [source])

    def test_group_mapping_keeps_native_group_identity(self):
        source = dict(provider='fixture', subject_type='org', namespace='directory',
                      external_id='12', group_id=34, name='native-display-name', id=56)
        result = REPAIR.project('cf_sso_group_map', [source])[0]
        self.assertEqual(result, {key:source[key] for key in REPAIR.TARGET_COLUMNS['cf_sso_group_map']})

    def test_any_old_guard_row_requires_a_separate_conversion(self):
        self.assertEqual(REPAIR.project('cf_edit_guard', []), [])
        with self.assertRaises(RuntimeError): REPAIR.project('cf_edit_guard', [dict(resource_uid='guard')])

    def test_storage_states_and_keys_remain_unchanged(self):
        source = dict(repo_key='native/key', repo_id='repo', state='retired')
        self.assertEqual(REPAIR.project('cf_library_storage', [source]), [source])

    def test_digest_is_order_independent_and_binary_safe(self):
        rows = [dict(value=b'\x00\xff'), dict(value='text')]
        self.assertEqual(REPAIR.digest(rows), REPAIR.digest(rows[::-1]))
        self.assertNotEqual(REPAIR.digest(rows), REPAIR.digest(rows[:1]))
        self.assertEqual(set(REPAIR.definitions()), set(REPAIR.TABLES))


if __name__ == '__main__':
    unittest.main()
