"""Initialize the shipped schema only for a new, persistent installation."""

import os
from pathlib import Path
import sys


def prepare_fresh_schema(shared_dir):
    shared_dir = Path(shared_dir)
    marker = shared_dir / '.cloudfile-schema-init-pending'
    # Persist intent before CE creates seafile-data: a failed DDL attempt must
    # retry after restart, while existing installations never opt into upgrades.
    if not (shared_dir / 'seafile-data').exists():
        marker.touch(mode=0o600, exist_ok=True)
    return marker


def initialize_fresh_schema(marker, installdir, environment=None):
    marker = Path(marker)
    if not marker.exists():
        return False
    environment = os.environ if environment is None else environment
    # Import the canonical runner without django.setup(): schema must exist
    # before enabled applications or native write barriers can access it.
    sys.path.insert(0, str(Path(installdir) / 'seahub'))
    connection = None
    try:
        import pymysql
        from cloudfile_ext.v2.schema import FreshSchema
        schema_dir = Path(installdir) / 'sql' / 'mysql'
        # One current V2 DDL owner; never replay the old 001..042 migration
        # catalog into a fresh database (it creates an incompatible Guard,
        # directory ACL and group mapping structure).
        ddl = (schema_dir / 'cloudfile-v2.sql').read_text()
        checkout = str(environment.get('CF_ENABLE_CHECKOUT', 'false')).lower() in ('true', '1')
        file_lock = str(environment.get('CF_ENABLE_FILE_LOCK', 'false')).lower() in ('true', '1')
        edit_ddl = ((schema_dir / 'cloudfile-v2-edit.sql').read_text()
                    if checkout or file_lock else None)
        connection = pymysql.connect(
            host=environment['SEAFILE_MYSQL_DB_HOST'],
            port=int(environment.get('SEAFILE_MYSQL_DB_PORT', '3306')),
            user=environment.get('SEAFILE_MYSQL_DB_USER', 'seafile'),
            password=environment['SEAFILE_MYSQL_DB_PASSWORD'],
            database=environment.get('SEAFILE_MYSQL_DB_SEAFILE_DB_NAME', 'seafile_db'),
            charset='utf8mb4', autocommit=True, connect_timeout=5,
        )
        # Install only three reviewed V2 tables (plus the explicitly enabled
        # optional one-table CF-EDIT). verify() rejects legacy/mixed layouts;
        # never auto-convert old identity, ACL or active Checkout data.
        # Keep the marker on failure; the operator must inspect and reconcile
        # any incompatible existing structure instead of replaying old DDL.
        FreshSchema(connection, ddl, edit_ddl=edit_ddl).install()
        marker.unlink()
        return True
    except Exception:
        # Driver errors can contain credentials; expose only an actionable cause.
        raise RuntimeError('CloudFile V2 fresh schema initialization failed; inspect existing cf_* tables before retry') from None
    finally:
        if connection is not None:
            connection.close()
        sys.path.pop(0)
