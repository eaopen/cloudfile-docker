#!/usr/bin/env python3
"""Fast, read-only V2 4+1 table dependency gate.

No historical migrations, no schema checksum ledger, no Docker/DB access.
Check only code that actually ships in current V2 runtime; inert historical
source is never an excuse to recreate a legacy table.
"""
import argparse
from pathlib import Path
import re

TABLES = frozenset({
    'cf_library_storage', 'cf_sso_group_map', 'cf_dir_acl',
    'cf_edit_guard', 'cf_audit_event',
})
DDL = ('cloudfile-v2.sql', 'cloudfile-v2-edit.sql', 'cloudfile-v2-audit.sql')
SQL_TABLE = re.compile(
    r'\b(?:FROM|JOIN|INTO|UPDATE|TABLE|REFERENCES)\s+[`"]?(cf_[a-z0-9_]+)',
)


def validate(server, hub, docker, agent=None):
    sql_dir = server / 'scripts/sql/mysql'
    observed = set()
    for name in DDL:
        text = (sql_dir / name).read_text()
        matches = re.findall(r'\bCREATE TABLE (cf_[a-z0-9_]+)\s*\(', text)
        if not matches or len(matches) != len(set(matches)):
            raise ValueError('missing or duplicate DDL: ' + name)
        observed.update(matches)
    if observed != TABLES:
        raise ValueError('V2 DDL differs from 4+1: ' + str(sorted(observed ^ TABLES)))
    if (sql_dir / 'cloudfile.sql').exists():
        raise ValueError('retired CloudFile schema re-entered Server installation')
    if (hub / 'cloudfile_extensions/schema').exists():
        raise ValueError('retired 001-042 schema runner re-entered Hub runtime')

    checks = [
        (server, ['common', 'server', 'fileserver'], ('.c', '.go')),
        (hub, ['cloudfile_ext/v2', 'cloudfile_ext/audit',
               'cloudfile_ext/file_actions'], ('.py',)),
        (docker, ['scripts/scripts_14.0', 'scripts/scripts_cf14.0'], ('.py',)),
    ]
    for root, dirs, suffixes in checks:
        for directory in dirs:
            for path in sorted((root / directory).rglob('*')):
                if not path.is_file() or path.suffix not in suffixes:
                    continue
                if path.name.endswith('_test.go') or path.name.startswith('test_'):
                    continue
                src = path.read_text()
                for match in SQL_TABLE.finditer(src):
                    if match.group(1).lower() not in TABLES:
                        raise ValueError('retired table SQL in ' +
                                         str(path.relative_to(root)) + ': ' + match.group(1))
    if agent is not None:
        core = agent / 'crates/cloudfile-core/src'
        for path in sorted(core.glob('*.rs')):
            source = path.read_text()
            if '/api/v2.1/cloudfile/agent-sessions/claim/' in source:
                raise ValueError('Agent2 legacy SQL Session HTTP client: ' + path.name)
    print('PASS current V2 4+1 DDL and active SQL dependencies')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--server', type=Path, required=True)
    ap.add_argument('--hub', type=Path, required=True)
    ap.add_argument('--docker', type=Path, default=Path(__file__).resolve().parents[2])
    ap.add_argument('--agent', type=Path)
    args = ap.parse_args()
    validate(args.server, args.hub, args.docker, args.agent)


if __name__ == '__main__':
    main()
