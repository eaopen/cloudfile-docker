"""Quick current-V2 documentation guard, no Docker/DB/network/compilation."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]

class CurrentAuthorizationSpec(unittest.TestCase):
    def test_no_library_classification_in_active_contracts(self):
        adjudication = (ROOT / 'docs/permission-adjudication-contract.md').read_text()
        schema = (ROOT / 'docs/permission-tables.md').read_text()
        policy = (ROOT / 'docs/acl-semantics.md').read_text()
        agents = (ROOT / 'AGENTS.md').read_text()
        self.assertIn('不存在托管库', adjudication)
        self.assertIn('不能使整个库进入另一权限模式', adjudication)
        self.assertIn('cf_dir_acl', schema)
        self.assertIn('cf_edit_guard', schema)
        self.assertIn('cf_audit_event', schema)
        self.assertIn('share_mode=true', policy)
        self.assertIn('目录 ACL', policy)
        self.assertIn('禁止“托管库”复活', agents)

    def test_outdated_enrollment_is_forbidden_as_documented_behavior(self):
        current = (ROOT / 'docs/permission-adjudication-contract.md').read_text()
        for old in ('managed_library_guard', 'allow_legacy_managed_reads',
                    'cf_managed_library', 'checkLegacyLibrary'):
            self.assertIn(old, current)
        self.assertIn('禁止重建', current)
        self.assertIn('不能据此拒绝已充分授权的普通目录访问', current)

    def test_retired_sql_runtime_fixtures_cannot_return(self):
        # These pre-V2 suites required cf_managed_library, Resource and
        # Session tables; restoring them would accidentally restore the old
        # implementation rather than validate the current five-table runtime.
        retired = (
            'tests/delegated_transfer_runtime.py',
            'tests/search_runtime.py',
            'tests/e2e/native_editing_e2e.py',
            'tests/e2e/native_optimistic_agent_e2e.py',
            'tests/e2e/native_directory_e2e.py',
            'tests/e2e/native_directory.sh',
        )
        for name in retired:
            self.assertFalse((ROOT / name).exists(), name)
        forbidden = re.compile(
            r'\b(?:INSERT\s+INTO|SELECT\s+[^\n]*?\s+FROM|UPDATE|DELETE\s+FROM)\s+cf_(?:managed_library|managed_library_share|library_share_revision)\b',
            re.I,
        )
        for sql in ('INSERT INTO cf_managed_library VALUES (1)',
                    'SELECT * FROM cf_managed_library_share',
                    'DELETE FROM cf_library_share_revision',
                    'UPDATE cf_managed_library SET x=1'):
            self.assertIsNotNone(forbidden.search(sql), sql)
        for file in (ROOT / 'tests').rglob('*.py'):
            if file == Path(__file__):
                continue
            with self.subTest(path=str(file.relative_to(ROOT))):
                self.assertIsNone(forbidden.search(file.read_text(encoding='utf-8')))

    def test_obsolete_runtime_is_never_reported_as_v2(self):
        smoke = (ROOT / 'tests/smoke_ce14_runtime.py').read_text()
        self.assertNotIn('cloudfile_extensions', smoke)
        self.assertIn('Retired identity-runtime fixture is not a V2 acceptance test', smoke)
        self.assertIn('Retired CloudFile extension regression cannot run on V2', smoke)

    def test_retired_policy_artifacts_are_not_packaged_or_tested(self):
        provenance = (ROOT / 'build/seafile_14.0/package_provenance.py').read_text()
        self.assertNotIn('libcloudfile_acl', provenance)
        for name in ('tests/probe_identity_runtime.py', 'tests/test_jit_worker.py',
                     'tests/test_audit_worker.py', 'tests/e2e/native_device_editing_e2e.py',
                     'tests/e2e/native_cdc_editing_e2e.py', 'tests/e2e/native_optimistic_cdc_e2e.py',
                     'tests/e2e/native_local_edit_baseline_e2e.py'):
            self.assertFalse((ROOT / name).exists(), name)

if __name__ == '__main__':
    unittest.main()
