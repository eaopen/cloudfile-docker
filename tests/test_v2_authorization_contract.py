"""Quick current-V2 documentation guard, no Docker/DB/network/compilation."""
from pathlib import Path
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

if __name__ == '__main__':
    unittest.main()
