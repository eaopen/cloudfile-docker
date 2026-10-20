#!/usr/bin/env python3
"""Read-only inventory of CloudFile V2 schema compatibility on an existing DB.

plan  — report missing, legacy, incompatible and extra cf_* tables using only
        information_schema SELECT queries.
check — same read-only probe, non-zero exit if the core V2 contract or installed
        optional Guard is not current. Never runs CREATE/ALTER/DROP or ledger
        updates; schema/data migration requires an offline reviewed procedure.
"""
import argparse
import json
import os
from pathlib import Path
import sys


def database_options(env):
    required = ('SEAFILE_MYSQL_DB_HOST', 'SEAFILE_MYSQL_DB_USER',
                'SEAFILE_MYSQL_DB_PASSWORD', 'SEAFILE_MYSQL_DB_SEAFILE_DB_NAME')
    if any(not env.get(name) for name in required):
        raise ValueError('explicit Seafile native database configuration required')
    return dict(host=env[required[0]], user=env[required[1]],
                password=env[required[2]], database=env[required[3]],
                port=int(env.get('SEAFILE_MYSQL_DB_PORT', '3306')),
                charset='utf8mb4', autocommit=True, connect_timeout=5,
                read_timeout=10)


def inspect(installdir, env, connect=None):
    from cloudfile_schema import _v2_schema_dir
    directory = _v2_schema_dir(installdir)
    sys.path.insert(0, str(Path(installdir) / 'seahub'))
    db = None
    try:
        from cloudfile_ext.v2.schema import FreshSchema
        if connect is None:
            import pymysql
            connect = pymysql.connect
        db = connect(**database_options(env))
        # The optional table is inventoried even when Checkout is disabled.
        # Read-only plan is metadata-only and never creates a table.
        ddl = (directory / 'cloudfile-v2.sql').read_text()
        return FreshSchema(db, ddl).inspect()
    finally:
        if db is not None:
            db.close()
        sys.path.pop(0)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('plan', 'check'))
    args = parser.parse_args(argv)
    try:
        from utils import get_install_dir
        report = inspect(get_install_dir(), os.environ)
        print(json.dumps(report, sort_keys=True))
        return 0 if args.command == 'plan' or report['status'] == 'current' else 2
    except Exception:
        # Never print connection/driver exceptions, which could expose secrets.
        print('CloudFile V2 schema inventory unavailable; check database and installed DDL',
              file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
