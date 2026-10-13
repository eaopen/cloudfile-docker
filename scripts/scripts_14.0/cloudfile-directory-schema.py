#!/usr/bin/env python3
"""Explicit release command for the three directory authority tables.

Use the same seafile database as native authority and the policy host. A second
set of CLOUDFILE_DB_* deployment secrets is neither needed nor accepted here.
This command is deliberately not invoked by normal service startup.
"""
import argparse
import json
import os
from pathlib import Path
import runpy
import sys


def database_options(environment, policy=None):
    required = ('SEAFILE_MYSQL_DB_HOST', 'SEAFILE_MYSQL_DB_USER',
                'SEAFILE_MYSQL_DB_PASSWORD', 'SEAFILE_MYSQL_DB_SEAFILE_DB_NAME')
    if any(not environment.get(key) for key in required):
        raise ValueError('explicit native database configuration required')
    result = dict(host=environment[required[0]], user=environment[required[1]],
                  password=environment[required[2]], database=environment[required[3]],
                  port=int(environment.get('SEAFILE_MYSQL_DB_PORT', '3306')),
                  charset='utf8mb4', autocommit=True, connect_timeout=5)
    if not 1 <= result['port'] <= 65535:
        raise ValueError('invalid database port')
    if policy is not None:
        db = policy['database']
        # Credentials may differ by role; authority host and native reads must
        # still point at exactly the same server and database.
        if (db['host'], int(db.get('port', 3306)), db['name']) != (
                result['host'], result['port'], result['database']):
            raise ValueError('policy and native directory databases differ')
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('plan', 'apply', 'check'))
    parser.add_argument('--offline', action='store_true',
                        help='confirm Hub, Server and workers that access directory tables are stopped')
    args = parser.parse_args(argv)
    connection = None
    try:
        entry = runpy.run_path(str(Path(__file__).with_name('cloudfile-jit-worker.py')))
        entry['bootstrap']()
        from django.conf import settings
        import pymysql
        from cloudfile_extensions.schema.directory import DirectorySchemaRunner
        options = database_options(os.environ, getattr(settings, 'CLOUDFILE_POLICY_CONFIG', None))
        connection = pymysql.connect(**options)
        runner = DirectorySchemaRunner(connection)
        result = (runner.apply(offline=args.offline) if args.command == 'apply' else
                  runner.require_current() if args.command == 'check' else runner.inspect())
        print(json.dumps({'database': options['database'], 'result': result}))
        return 0
    except Exception:
        # Driver/settings exceptions can contain passwords. Plans themselves
        # contain only table layouts and migration states, never subject rows.
        print('Directory schema command failed; check plan, offline state and database alignment', file=sys.stderr)
        return 1
    finally:
        if connection is not None:
            connection.close()


if __name__ == '__main__':
    raise SystemExit(main())
