#!/usr/bin/env python3
"""Explicit, additive five-to-six-table migration; never called by startup."""
import argparse
import os
from pathlib import Path
import sys


def migrate(schema, *, apply=False):
    from cloudfile_ext.v2.schema import database_lock, SchemaError, PROTECTION_TABLES
    with database_lock(schema.connection, 'schema'):
        with schema.connection.cursor() as cursor:
            present = schema._tables(cursor)
            if present not in (schema.tables, schema.tables - PROTECTION_TABLES):
                raise SchemaError('requires the exact reviewed five- or six-table schema')
            for name in sorted(present):
                schema._verify_one(cursor, name)
            if present == schema.tables:
                return 'already current'
            if not apply:
                return 'ready: would create cf_file_protection only'
            cursor.execute(schema.ddl['cf_file_protection'])
        schema.verify()
        return 'created and verified cf_file_protection'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--installdir', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--writers-stopped', action='store_true',
                        help='operator assertion: all Server/Hub/worker writers are stopped')
    args = parser.parse_args()
    if args.apply and not args.writers_stopped:
        parser.error('--apply requires --writers-stopped')
    sys.path.insert(0, str(args.installdir / 'seahub'))
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts/scripts_cf14.0'))
    from cloudfile_ext.v2.schema import FreshSchema
    from cloudfile_schema import _connect
    connection = None
    try:
        sql = args.installdir / 'sql/mysql'
        connection = _connect(os.environ)
        schema = FreshSchema(connection, (sql / 'cloudfile-v2.sql').read_text(),
            edit_ddl=(sql / 'cloudfile-v2-edit.sql').read_text(),
            audit_ddl=(sql / 'cloudfile-v2-audit.sql').read_text(),
            protection_ddl=(sql / 'cloudfile-v2-protection.sql').read_text())
        print(migrate(schema, apply=args.apply))
    except Exception:
        print('Protection migration failed; inspect schema and keep writers stopped. No rollback or deletion attempted.', file=sys.stderr)
        return 1
    finally:
        if connection is not None:
            connection.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
