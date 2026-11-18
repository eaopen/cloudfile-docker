#!/usr/bin/env python3
"""Offline V2 cutover. Preserve the old registry for inspection and reversibility."""
import argparse
from configparser import ConfigParser
import os
from pathlib import Path
from uuid import UUID

ARCHIVE = 'retired_library_storage_v2'


def canonical(value):
    if str(UUID(value)) != value:
        raise ValueError('noncanonical repository UUID')
    return value


def migrate(db, config, sql_dir, apply):
    from cloudfile_ext.v2.schema import FreshSchema
    from cloudfile_ext.v2.storage_reconcile import valid_key
    schema = FreshSchema(db, (sql_dir / 'cloudfile-v2.sql').read_text(),
                         edit_ddl=(sql_dir / 'cloudfile-v2-edit.sql').read_text(),
                         audit_ddl=(sql_dir / 'cloudfile-v2-audit.sql').read_text(),
                         protection_ddl=(sql_dir / 'cloudfile-v2-protection.sql').read_text())
    managed = bool(config.get('cloudfile_v2','auto_local_root',fallback='').strip())
    with db.cursor() as cur:
        cur.execute('SHOW TABLES')
        tables = {row[0] for row in cur.fetchall()}
        if ARCHIVE in tables and 'cf_library_storage' not in tables:
            schema.verify()
            return 'already migrated'
        if ARCHIVE in tables or 'cf_library_storage' not in tables:
            raise ValueError('unexpected registry state')
        # Verify native routes against every historical key before changing
        # anything. Never synthesize a UUID route for a missing custom key.
        cur.execute('SELECT repo_id,storage_id FROM RepoStorageId')
        routes = dict(cur.fetchall())
        cur.execute('SELECT repo_id,repo_key,state FROM cf_library_storage')
        legacy = {r:(key,state) for r,key,state in cur.fetchall()}
        cur.execute('SELECT repo_id FROM Repo UNION SELECT repo_id FROM RepoTrash '
                    'UNION SELECT repo_id FROM GarbageRepos UNION SELECT repo_id FROM VirtualRepo')
        resources = {row[0] for row in cur.fetchall()}
        cur.execute('SELECT repo_id FROM VirtualRepo')
        virtual = {r[0] for r in cur.fetchall()}
        native = set()
        for rid,(key,state) in legacy.items():
            canonical(rid)
            route = routes.get(rid)
            if state not in ('active','retired') or (
                key != 'native-'+rid and
                (not valid_key(key) or route != 'auto-local:'+key)):
                raise ValueError('unresolved registry entry '+rid)
            if key == 'native-'+rid and rid in routes and route != 'cf-native':
                raise ValueError('native route mismatch '+rid)
        if managed:
            for rid in resources-routes.keys():
                if legacy.get(rid,(None,))[0] != 'native-'+rid and rid not in virtual:
                    raise ValueError('missing proven native binding '+rid)
                native.add(canonical(rid))
        allocated = [v for v in routes.values() if v and v.startswith('auto-local:')]
        if len(allocated)!=len(set(allocated)):
            raise ValueError('duplicate managed route')
        for name in schema.tables:
            if name in tables:
                schema._verify_one(cur,name)
            elif name not in ('cf_repo_feature','cf_file_protection'):
                raise ValueError('missing prerequisite '+name)
        # Never strand protection records or live leases when features default off.
        for table, feature, predicate in (
                ('cf_file_protection', 'protection', '1=1'),
                ('cf_edit_guard', 'checkout', 't.lease_expires_at > UTC_TIMESTAMP(6)')):
            if table not in tables:
                continue
            enabled = (" AND NOT EXISTS (SELECT 1 FROM cf_repo_feature f "
                       "WHERE f.repo_id=t.repo_id AND f.feature=%s)"
                       if 'cf_repo_feature' in tables else '')
            cur.execute('SELECT 1 FROM ' + table + ' t WHERE ' + predicate + enabled + ' LIMIT 1',
                        (feature,) if enabled else ())
            if cur.fetchone():
                raise ValueError('existing protection or active Guard requires explicit safe disposition before migration')
        if not apply:
            return f'ready: {len(legacy)} registry rows, {len(native)} native routes, features default off'
        for name in ('cf_file_protection','cf_repo_feature'):
            if name not in tables:
                cur.execute(schema.ddl[name])
        db.begin()
        try:
            for rid in sorted(native):
                cur.execute("INSERT INTO RepoStorageId(repo_id,storage_id) VALUES (%s,'cf-native')",(rid,))
            db.commit()
        except BaseException:
            db.rollback()
            raise
        cur.execute('RENAME TABLE cf_library_storage TO '+ARCHIVE)
        schema.verify()
        return f'migrated: {len(legacy)} archived rows, {len(native)} native routes, existing feature rows preserved; new features default off'


if __name__ == '__main__':
    import sys
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument('--installdir',type=Path,required=True)
    args.add_argument('--conf',type=Path,required=True)
    args.add_argument('--apply',action='store_true')
    args.add_argument('--writers-stopped',action='store_true')
    opts = args.parse_args()
    if opts.apply and not opts.writers_stopped:
        args.error('offline migration requires stopped writers')
    sys.path.insert(0,str(opts.installdir/'seahub'))
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts/scripts_cf14.0'))
    from cloudfile_schema import _connect
    conf = ConfigParser(interpolation=None)
    with opts.conf.open() as stream:
        conf.read_file(stream)
    connection = _connect(os.environ)
    try:
        print(migrate(connection,conf,opts.installdir/'sql/mysql',opts.apply))
    finally:
        connection.close()
