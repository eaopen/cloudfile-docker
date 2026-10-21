"""Release SQL and read-only startup must not drift into different contracts."""
import hashlib
import importlib.util
import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value
SQL=module('sql_contracts',ROOT/'tools/check-sql-contracts.py')
GATE=module('readonly_schema',ROOT/'scripts/scripts_14.0/cloudfile_schema.py')
FOLDER=ROOT/'database/v2/20261021-four-table-baseline'


class ManualSQLPackageTest(unittest.TestCase):
    def test_fixed_release_checksums_cover_every_sql_input(self):
        expected=json.loads((FOLDER/'checksums.json').read_text())
        actual={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in FOLDER.glob('*.sql')}
        self.assertEqual(actual,expected)

    def test_no_fifth_business_table_is_delivered(self):
        names={name for path in FOLDER.glob('*.sql') for name,_,_ in SQL.creates(path.read_text())}
        self.assertEqual(names,{'cf_library_storage','cf_dir_acl','cf_sso_group_map','cf_edit_guard'})

    def test_startup_contract_matches_delivered_create_sql(self):
        tables={name:(columns,indexes) for name,columns,indexes in SQL.creates((FOLDER/'00-create.sql').read_text())}
        self.assertEqual(set(tables),set(GATE.COLUMNS))
        for name,(columns,indexes) in tables.items():
            self.assertEqual(columns,set(GATE.COLUMNS[name].split()))
            self.assertEqual(indexes,GATE.INDEXES[name])

    def test_upgrade_requires_offline_and_refuses_guard_or_partial_state(self):
        upgrade=(FOLDER/'10-upgrade-029-042.sql').read_text()
        self.assertIn('@cf_upgrade_writers_stopped',upgrade)
        self.assertIn('@cf_upgrade_accept_path_acl',upgrade)
        self.assertIn('IF EXISTS(SELECT 1 FROM cf_edit_guard)',upgrade)
        self.assertIn('UNHEX(path_hash)',upgrade)
        self.assertEqual(upgrade.count('RENAME TABLE '),1)
        self.assertIn('@cf_upgrade_archive_database',upgrade)
        self.assertNotIn('DROP TABLE ',upgrade)
        self.assertIn('Candidate data mismatch',upgrade)
        self.assertNotIn('cf_schema_migration SET',upgrade)


if __name__=='__main__': unittest.main()
