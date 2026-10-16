"""Initialize the shipped schema only for a new, persistent installation."""

import os
from pathlib import Path
import sys
import tempfile


def installation_profile(shared_dir):
    shared_dir = Path(shared_dir)
    values = []
    for name in ('.cloudfile-schema-profile', '.cloudfile-schema-init-pending'):
        path = shared_dir / name
        if path.exists():
            value = path.read_text().strip() or 'legacy'
            if value not in ('legacy', 'm1'):
                raise RuntimeError('Invalid CloudFile schema profile marker')
            values.append(value)
    if len(set(values)) > 1:
        raise RuntimeError('Conflicting CloudFile schema profile markers')
    return values[0] if values else 'legacy'


def _write_profile(path, profile):
    descriptor, temporary = tempfile.mkstemp(prefix='.cf-schema-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w') as stream:
            stream.write(profile + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def prepare_fresh_schema(shared_dir, environment=None):
    shared_dir = Path(shared_dir)
    environment = os.environ if environment is None else environment
    marker = shared_dir / '.cloudfile-schema-init-pending'
    requested = environment.get('CLOUDFILE_FRESH_SCHEMA_PROFILE', 'legacy')
    initialize = environment.get('CLOUDFILE_INITIALIZE_M1_SCHEMA', 'false').strip().lower()
    if initialize not in ('true', 'false'):
        raise RuntimeError('CLOUDFILE_INITIALIZE_M1_SCHEMA must be true or false')
    if initialize == 'true' and (requested != 'm1' or
            (shared_dir / '.cloudfile-schema-profile').exists() and installation_profile(shared_dir) != 'm1'):
        raise RuntimeError('M1 initialization requires a clean M1 configuration')
    # Persist intent before CE creates seafile-data: a failed DDL attempt must
    # retry after restart, while existing installations never opt into upgrades.
    fresh = not (shared_dir / 'seafile-data').exists()
    if (fresh or initialize == 'true') and not marker.exists():
        profile = requested
        if profile not in ('legacy', 'm1'):
            raise RuntimeError('Invalid fresh CloudFile schema profile')
        _write_profile(marker, profile)
    # The persistent installation marker wins on restart; changing an env var
    # must never turn an existing database into a destructive schema upgrade.
    environment['CLOUDFILE_SCHEMA_PROFILE'] = installation_profile(shared_dir)
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
        profile = installation_profile(marker.parent)
        if profile == 'm1':
            SchemaRunner(connection, profile='m1').apply()
        else:
            SchemaRunner(connection).apply()
        _write_profile(marker.parent / '.cloudfile-schema-profile', profile)
        marker.unlink()
        return True
    except Exception:
        # Driver errors can contain credentials; expose only an actionable cause.
        raise RuntimeError('Fresh CloudFile schema initialization failed; inspect the schema ledger before retry') from None
    finally:
        if connection is not None:
            connection.close()
        sys.path.pop(0)
