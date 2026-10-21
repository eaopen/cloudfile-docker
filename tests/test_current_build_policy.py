"""Current builds have one implementation and no automatic heavy CI."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CurrentBuildPolicy(unittest.TestCase):
    def test_legacy_assembler_and_workflows_are_gone(self):
        # 2026-10-21：旧构建链归档已移出本仓，不在本仓保留任何历史构建脚本。
        # 本仓只保证"旧入口不再存在"，不再断言归档文件仍在本地。
        self.assertFalse((ROOT / 'build/v2/source-set.json').exists())
        self.assertFalse((ROOT / 'tools/prepare-v2-source.py').exists())
        self.assertFalse((ROOT / 'docs/history/storage-build-20261020').exists())
        for name in ('v2-clean.yml', 'v2-dev-bundle.yml'):
            self.assertFalse((ROOT / '.github/workflows' / name).exists())

    def test_full_and_privileged_tests_only_run_on_dispatch(self):
        workflow = (ROOT / '.github/workflows/prod.yml').read_text()
        trigger = workflow.split('permissions:', 1)[0]
        self.assertIn('workflow_dispatch:', trigger)
        self.assertNotIn('  push:', trigger)
        self.assertNotIn('  pull_request:', trigger)
        self.assertIn('--privileged', workflow)
        self.assertIn('CF_TEST_BIND_MOUNTS=1', workflow)
        quick = (ROOT / '.github/workflows/dev.yml').read_text()
        self.assertNotIn('docker run', quick)
        self.assertNotIn('build-in-docker.sh', quick)

    def test_generated_lock_has_no_hand_maintained_source_shas(self):
        ignored = (ROOT / '.gitignore').read_text(errors='replace')
        self.assertIn('build/cloudfile_14.0/release.json', ignored)
        builder = (ROOT / 'build/cloudfile_14.0/cloudfile-build.sh').read_text()
        self.assertIn('build_receipt.py', builder)
        self.assertNotIn('target="origin/${ref}"', builder)
        self.assertNotIn("manifest_get_optional 'server_commit'", builder)
