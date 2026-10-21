"""Run SQL contract regressions on copies of the real reviewed DDL inputs."""
import argparse
import importlib.util
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('sql_contracts', ROOT / 'tools/check-sql-contracts.py')
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)
SERVER = ROOT.parent / 'cloudfile-server'
HUB = ROOT.parent / 'cloudfile-hub'


class SqlContractTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.server = Path(self.temporary.name) / 'server'
        self.hub = Path(self.temporary.name) / 'hub'
        sql = self.server / 'scripts/sql/mysql'
        sql.mkdir(parents=True)
        for name in ('cloudfile.sql', 'cloudfile-v2.sql', 'cloudfile-v2-edit.sql'):
            shutil.copyfile(SERVER / 'scripts/sql/mysql' / name, sql / name)
        shutil.copytree(HUB / 'cloudfile_extensions/schema/migrations', self.hub / 'cloudfile_extensions/schema/migrations')
        helper = self.hub / 'cloudfile_ext/v2'
        helper.mkdir(parents=True)
        shutil.copyfile(HUB / 'cloudfile_ext/v2/checkout_schema.py', helper / 'checkout_schema.py')

    def test_actual_reviewed_contracts_agree_and_report_layout_boundaries(self):
        result = CHECK.audit(self.server, self.hub)
        self.assertEqual(result['checkout_reader_contracts'], 'matched')
        self.assertEqual(result['isolated_layout_collisions'], ['cf_dir_acl', 'cf_edit_guard', 'cf_sso_group_map'])

    def test_new_missing_index_or_changed_column_is_rejected(self):
        path = self.server / 'scripts/sql/mysql/cloudfile-v2-edit.sql'
        original = path.read_text()
        for changed in (original.replace('cf_edit_guard_active', 'wrong_index'),
                        original.replace('lease_expires_at', 'lease_expiry')):
            path.write_text(changed)
            with self.assertRaisesRegex(ValueError, 'reader and CREATE DDL'):
                CHECK.audit(self.server, self.hub)

    def test_new_unreviewed_same_name_layout_is_rejected(self):
        core = self.server / 'scripts/sql/mysql/cloudfile-v2.sql'
        core.write_text(core.read_text() + '\nCREATE TABLE cf_probe(alpha INT) ENGINE=InnoDB;')
        migration = self.hub / 'cloudfile_extensions/schema/migrations/999_probe.json'
        migration.write_text('{"steps":[{"sql":"CREATE TABLE cf_probe(beta INT) ENGINE=InnoDB"}]}')
        with self.assertRaisesRegex(ValueError, 'new incompatible table-name collision'):
            CHECK.audit(self.server, self.hub)

    def test_type_default_and_migration_changes_require_review(self):
        path = self.server / 'scripts/sql/mysql/cloudfile-v2-edit.sql'
        original = path.read_text()
        # Same columns/indexes still cannot hide changed types or SQL semantics.
        path.write_text(original.replace('CHAR(36)', 'CHAR(35)'))
        self.assertNotEqual(path.read_text(), original)
        with self.assertRaisesRegex(ValueError, 'SQL review baseline changed'):
            CHECK.audit(self.server, self.hub)
        path.write_text(original)
        migration = self.hub / 'cloudfile_extensions/schema/migrations/999_drift.json'
        migration.write_text('{"steps":[{"sql":"ALTER TABLE cf_edit_guard ADD unsafe INT DEFAULT 1"}]}')
        with self.assertRaisesRegex(ValueError, 'SQL review baseline changed'):
            CHECK.audit(self.server, self.hub)

    def test_nested_constraints_do_not_become_fake_columns(self):
        result = list(CHECK.creates("CREATE TABLE cf_test(path VARCHAR(99), guard_id CHAR(36), CONSTRAINT c CHECK (path IN ('a,b','c')), KEY lookup(path,guard_id)) ENGINE=InnoDB"))
        self.assertEqual(result[0][1], {'path', 'guard_id'})
        self.assertEqual(result[0][2]['lookup'], (1, ('path', 'guard_id')))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--server', type=Path, default=SERVER)
    parser.add_argument('--hub', type=Path, default=HUB)
    options, remaining = parser.parse_known_args()
    SERVER, HUB = options.server, options.hub
    unittest.main(argv=[sys.argv[0], *remaining])
