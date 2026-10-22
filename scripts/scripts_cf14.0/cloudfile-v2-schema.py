#!/usr/bin/env python3
"""Read-only CloudFile V2 schema inventory for operators.

plan  - print the classified contract (current/missing/legacy/incompatible/mixed)
        plus any extra cf_* tables; never changes the database.
check - same read-only probe, non-zero exit when the instance is not current.

Both commands issue information_schema SELECTs only. Applying DDL stays a
manual, reviewed step with database/v2/20261021-four-table-baseline/*.sql.
"""
import argparse
import json
import os
from pathlib import Path
import sys

# The image flattens scripts_14.0 and scripts_cf14.0 into /scripts; keep the
# sibling import local.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from cloudfile_schema import inspect_v2_schema  # noqa: E402


def _connect(env):
    import pymysql
    return pymysql.connect(
        host=env['SEAFILE_MYSQL_DB_HOST'],
        port=int(env.get('SEAFILE_MYSQL_DB_PORT', '3306')),
        user=env.get('SEAFILE_MYSQL_DB_USER', 'seafile'),
        password=env['SEAFILE_MYSQL_DB_PASSWORD'],
        database=env.get('SEAFILE_MYSQL_DB_SEAFILE_DB_NAME', 'seafile_db'),
        charset='utf8mb4', autocommit=True, connect_timeout=5, read_timeout=10,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('plan', 'check'))
    args = parser.parse_args(argv)
    connection = None
    try:
        requested = str(os.environ.get('CF_ENABLE_CHECKOUT', 'false')).lower()
        if requested not in ('true', 'false'):
            raise ValueError('invalid Checkout setting')
        connection = _connect(os.environ)
        report = inspect_v2_schema(connection, checkout_enabled=requested == 'true')
        print(json.dumps(report, sort_keys=True))
        # plan is diagnostic and always succeeds when the probe worked; check
        # is the gate a deployment script can rely on.
        return 0 if args.command == 'plan' or report['status'] == 'current' else 2
    except Exception:
        # Driver messages may embed connection details; never echo them.
        print('CloudFile V2 schema inventory unavailable; check database configuration '
              'and the reviewed database/v2 SQL package', file=sys.stderr)
        return 1
    finally:
        if connection is not None:
            connection.close()


if __name__ == '__main__':
    raise SystemExit(main())
