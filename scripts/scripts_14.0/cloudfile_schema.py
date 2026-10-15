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
        from cloudfile_extensions.schema.runner import SchemaRunner
        connection = pymysql.connect(
            host=environment['SEAFILE_MYSQL_DB_HOST'],
            port=int(environment.get('SEAFILE_MYSQL_DB_PORT', '3306')),
            user=environment.get('SEAFILE_MYSQL_DB_USER', 'seafile'),
            password=environment['SEAFILE_MYSQL_DB_PASSWORD'],
            database=environment.get('SEAFILE_MYSQL_DB_SEAFILE_DB_NAME', 'seafile_db'),
            charset='utf8mb4', autocommit=True, connect_timeout=5,
        )
        # apply() verifies DDL and checksums under the runner's database lock.
        # Keep the marker on failure so partial MySQL DDL can resume safely.
        SchemaRunner(connection).apply()
        marker.unlink()
        return True
    except Exception:
        # Driver errors can contain credentials; expose only an actionable cause.
        raise RuntimeError('Fresh CloudFile schema initialization failed; inspect the schema ledger before retry') from None
    finally:
        if connection is not None:
            connection.close()
        sys.path.pop(0)
