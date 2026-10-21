"""Startup schema gate plus one-time initialization for a new volume."""
import json
import os
import sys
from pathlib import Path

# Keep these names aligned with database/v2/20261021-four-table-baseline/00-create.sql.
# Table existence alone previously enabled an incompatible Guard on every upload.
COLUMNS = {
    'cf_library_storage': 'repo_key repo_id state',
    'cf_sso_group_map': 'provider subject_type namespace external_id group_id',
    'cf_dir_acl': 'repo_id path_hash path subject_type provider namespace external_id permission inherit share_mode revision',
    'cf_edit_guard': 'repo_id path_hash path guard_id generation owner_uid owner_native_user terminal_type terminal_name checkout_ip proof_digest base_file_id lease_expires_at created_at updated_at',
    'cf_audit_event': 'id repo_id object_type object_id operation operator source before after source_path target_path path_hash commit_id result failure_reason occurred_at',
}
INDEXES = {
    'cf_library_storage': {'PRIMARY': (0, ('repo_key',)), 'library_storage_repo': (0, ('repo_id',))},
    'cf_sso_group_map': {'PRIMARY': (0, ('provider','subject_type','namespace','external_id')), 'sso_native_group': (0, ('group_id',))},
    'cf_dir_acl': {'PRIMARY': (0, ('repo_id','path_hash','subject_type','provider','namespace','external_id')),
                   'acl_shared_subject': (1, ('provider','subject_type','namespace','external_id','share_mode','repo_id'))},
    'cf_edit_guard': {'PRIMARY': (0, ('repo_id','path_hash')), 'cf_edit_guard_id': (0, ('guard_id',)),
                      'cf_edit_guard_active': (1, ('repo_id','guard_id')), 'cf_edit_guard_owner': (1, ('owner_uid','guard_id'))},
    'cf_audit_event': {'PRIMARY': (0, ('id',)),
        'cf_audit_repo_time': (1, ('repo_id','occurred_at','id')),
        'cf_audit_path_time': (1, ('repo_id','path_hash','occurred_at','id'))},
}


def verify_v2_schema(connection, checkout_enabled=False):
    """Check the installed core contract without CREATE, ALTER, DML or repair.

    This is a startup gate, not a replacement for release SQL/data validation.
    The four-table baseline includes the optional edit table, but disabled
    Checkout does not qualify or require that table for ordinary file transfers.
    """
    with connection.cursor() as cursor:
        # Legacy tables are migration inputs/archives, never runtime fallbacks.
        # Reject mixed databases even when the four new tables themselves match.
        cursor.execute("SELECT TABLE_NAME FROM information_schema.TABLES "
                       "WHERE TABLE_SCHEMA=DATABASE() AND LOWER(LEFT(TABLE_NAME,2))='cf'")
        installed = {row[0] for row in cursor.fetchall()}
        required = set(COLUMNS) if checkout_enabled else set(COLUMNS) - {'cf_edit_guard'}
        if not required <= installed or installed - set(COLUMNS):
            raise ValueError('runtime database contains missing core or unapproved CloudFile tables')
        for table, names in COLUMNS.items():
            # An unfinished, disabled Checkout must never prevent file service
            # startup because its Guard is missing or has an incompatible shape.
            if table == 'cf_edit_guard' and not checkout_enabled:
                continue
            cursor.execute('SELECT ENGINE,TABLE_COLLATION FROM information_schema.TABLES '
                           'WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s', (table,))
            if cursor.fetchall() != (('InnoDB', 'utf8mb4_bin'),):
                raise ValueError('core table engine/collation mismatch')
            cursor.execute('SELECT COLUMN_NAME,DATA_TYPE,CHARACTER_MAXIMUM_LENGTH '
                           'FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s', (table,))
            columns = {name: (kind, length) for name, kind, length in cursor.fetchall()}
            if set(columns) != set(names.split()):
                raise ValueError('core column layout mismatch')
            if table in ('cf_dir_acl', 'cf_edit_guard') and columns['path_hash'] != ('binary', 32):
                raise ValueError('core path hash must be BINARY(32)')
            if table == 'cf_audit_event' and columns['path_hash'] != ('binary', 32):
                raise ValueError('audit path hash must be BINARY(32)')
            if table == 'cf_sso_group_map' and columns['group_id'][0] != 'bigint':
                raise ValueError('native group identity must be BIGINT')
            cursor.execute('SELECT INDEX_NAME,NON_UNIQUE,SEQ_IN_INDEX,COLUMN_NAME,SUB_PART '
                           'FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s '
                           'ORDER BY INDEX_NAME,SEQ_IN_INDEX', (table,))
            indexes = {}
            for name, non_unique, sequence, column, prefix in cursor.fetchall():
                unique, parts = indexes.setdefault(name, (non_unique, []))
                if prefix is not None or unique != non_unique or sequence != len(parts) + 1:
                    raise ValueError('core index contract mismatch')
                parts.append(column)
            actual = {name: (unique, tuple(parts)) for name, (unique, parts) in indexes.items()}
            if any(actual.get(name) != value for name, value in INDEXES[table].items()):
                raise ValueError('required core index missing or changed')


# Historical column names that identify an archived 029/042 layout rather than
# a random drift. Used only for classification; never for migration decisions.
LEGACY_MARKERS = {
    'cf_edit_guard': {'resource_uid', 'lifecycle_ref', 'lease_until'},
    'cf_dir_acl': {'lifecycle_ref'},
}

# Written only for a volume without seafile-data; it authorizes one-time
# initialization and is removed after a verified install.
MARKER_NAME = '.cloudfile-schema-init-pending'


def _checkout_enabled(environment):
    """Parse the explicit Checkout switch; an invalid value must not guess."""
    requested = str(environment.get('CF_ENABLE_CHECKOUT', 'false')).lower()
    if requested not in ('true', 'false'):
        raise ValueError('invalid Checkout setting')
    return requested == 'true'


def _connect(environment):
    import pymysql
    return pymysql.connect(
        host=environment['SEAFILE_MYSQL_DB_HOST'],
        port=int(environment.get('SEAFILE_MYSQL_DB_PORT', '3306')),
        user=environment.get('SEAFILE_MYSQL_DB_USER', 'seafile'),
        password=environment['SEAFILE_MYSQL_DB_PASSWORD'],
        database=environment.get('SEAFILE_MYSQL_DB_SEAFILE_DB_NAME', 'seafile_db'),
        charset='utf8mb4', autocommit=True, connect_timeout=5, read_timeout=10,
    )


def inspect_v2_schema(connection, checkout_enabled=False):
    """Classify an installed database without writes, migrations or failures.

    The startup gate answers "may this instance serve traffic?"; this inventory
    answers "what is actually installed?" so an operator can run the reviewed
    SQL package with the right plan. It issues information_schema SELECTs only
    and returns a JSON-serialisable report instead of raising on drift.
    """
    report = {
        'status': 'current',
        'checkout_enabled': bool(checkout_enabled),
        'tables': {},
        'extra_tables': [],
    }
    with connection.cursor() as cursor:
        cursor.execute("SELECT TABLE_NAME FROM information_schema.TABLES "
                       "WHERE TABLE_SCHEMA=DATABASE() AND LOWER(LEFT(TABLE_NAME,2))='cf'")
        installed = {row[0] for row in cursor.fetchall()}
        report['extra_tables'] = sorted(installed - set(COLUMNS))
        required = set(COLUMNS) if checkout_enabled else set(COLUMNS) - {'cf_edit_guard'}
        for table, names in COLUMNS.items():
            if table not in required:
                # Disabled Checkout is not a defect: the optional table is
                # reported without being qualified, matching the startup gate.
                report['tables'][table] = 'optional-disabled'
                continue
            if table not in installed:
                report['tables'][table] = 'missing'
                continue
            cursor.execute('SELECT COLUMN_NAME,DATA_TYPE,CHARACTER_MAXIMUM_LENGTH '
                           'FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s', (table,))
            columns = {name: (kind, length) for name, kind, length in cursor.fetchall()}
            report['tables'][table] = _classify_table(cursor, table, columns, names)
    report['status'] = _overall_status(report, required)
    return report


def _classify_table(cursor, table, columns, expected_names):
    """Return current, legacy or incompatible for one installed table."""
    # Same contract checks as the startup gate, but drift is reported instead
    # of raised so a diagnostic run never looks like a failed deployment.
    defects = []
    if set(columns) != set(expected_names.split()):
        defects.append('columns')
    if table in ('cf_dir_acl', 'cf_edit_guard') and columns.get('path_hash') != ('binary', 32):
        defects.append('path_hash')
    if table == 'cf_audit_event' and columns.get('path_hash') != ('binary', 32):
        defects.append('path_hash')
    if table == 'cf_sso_group_map' and columns.get('group_id', ('',))[0] != 'bigint':
        defects.append('group_id')
    cursor.execute('SELECT ENGINE,TABLE_COLLATION FROM information_schema.TABLES '
                   'WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s', (table,))
    if cursor.fetchall() != (('InnoDB', 'utf8mb4_bin'),):
        defects.append('engine')
    cursor.execute('SELECT INDEX_NAME,NON_UNIQUE,SEQ_IN_INDEX,COLUMN_NAME,SUB_PART '
                   'FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s '
                   'ORDER BY INDEX_NAME,SEQ_IN_INDEX', (table,))
    indexes = {}
    for name, non_unique, sequence, column, prefix in cursor.fetchall():
        unique, parts = indexes.setdefault(name, (non_unique, []))
        if prefix is not None or unique != non_unique or sequence != len(parts) + 1:
            defects.append('index_shape')
            continue
        parts.append(column)
    actual = {name: (unique, tuple(parts)) for name, (unique, parts) in indexes.items()}
    if any(actual.get(name) != value for name, value in INDEXES[table].items()):
        defects.append('index')
    if not defects:
        return 'current'
    # Historical names prove the table is an archived layout, not arbitrary drift.
    if LEGACY_MARKERS.get(table, set()) & set(columns):
        return 'legacy'
    return 'incompatible'


def _overall_status(report, required):
    """Collapse per-table states into one operator-facing status."""
    states = [report['tables'][table] for table in sorted(required)]
    if all(state == 'current' for state in states) and not report['extra_tables']:
        return 'current'
    if all(state == 'missing' for state in states):
        return 'missing'
    if 'legacy' in states:
        return 'legacy'
    if 'incompatible' in states:
        return 'incompatible'
    return 'mixed'


def prepare_fresh_schema(shared_dir, environment=None):
    """Persist fresh-volume intent before CE creates its data directory.

    Only a volume without seafile-data gets the marker, and an existing marker
    is never rewritten: a retry must keep the original table plan so a changed
    Checkout setting cannot add a table behind the operator's back. The marker
    records the file identity of this volume, so a copied or restored marker
    from another deployment is rejected instead of being replayed.
    """
    shared_dir = Path(shared_dir)
    marker = shared_dir / MARKER_NAME
    if marker.exists():
        return marker
    if (shared_dir / 'seafile-data').exists():
        return marker
    try:
        checkout = _checkout_enabled(os.environ if environment is None else environment)
    except ValueError:
        # Invalid configuration fails the later startup gate; do not bake a
        # guessed table plan into a volume that may then be reused.
        return marker
    plan = {'version': 1, 'checkout': checkout}
    marker.write_text(json.dumps(plan), encoding='utf-8')
    stat = marker.stat()
    plan.update({'dev': stat.st_dev, 'ino': stat.st_ino})
    marker.write_text(json.dumps(plan), encoding='utf-8')
    marker.chmod(0o600)
    return marker


def _fresh_plan(marker):
    """Read and validate the recorded initialization plan.

    A missing identity, wrong version or foreign inode means the marker is not
    proof of a fresh volume; initialization must stop instead of guessing.
    """
    try:
        plan = json.loads(Path(marker).read_text(encoding='utf-8'))
        stat = Path(marker).stat()
    except Exception:
        raise RuntimeError('CloudFile V2 initialization marker is unreadable; inspect cf_* tables before retry') from None
    if (not isinstance(plan, dict) or plan.get('version') != 1
            or not isinstance(plan.get('checkout'), bool)
            or (plan.get('dev'), plan.get('ino')) != (stat.st_dev, stat.st_ino)):
        raise RuntimeError('CloudFile V2 initialization marker is stale or belongs to another volume; '
                           'inspect cf_* tables and remove the marker only after review')
    return plan


def initialize_fresh_schema(marker, installdir, environment=None):
    """Create the reviewed V2 tables once for a new volume.

    Development-period *upgrades* stay manual, but a fresh volume still needs
    its tables before the first request. The DDL is the reviewed CREATE set
    shipped with the server image; FreshSchema refuses legacy or mixed layouts
    instead of converting them. The table plan comes from the marker, never
    from the current environment, so a retry after a configuration change
    cannot add the optional Guard table. The marker is removed only after a
    verified install, so a failed attempt is retried on the next start.
    """
    marker = Path(marker)
    if not marker.exists():
        return False
    plan = _fresh_plan(marker)
    connection = None
    try:
        sql_dir = Path(installdir) / 'sql' / 'mysql'
        ddl = (sql_dir / 'cloudfile-v2.sql').read_text()
        audit_ddl = (sql_dir / 'cloudfile-v2-audit.sql').read_text()
        edit_ddl = ((sql_dir / 'cloudfile-v2-edit.sql').read_text()
                    if plan['checkout'] else None)
        sys.path.insert(0, str(Path(installdir) / 'seahub'))
        try:
            from cloudfile_ext.v2.schema import FreshSchema
        finally:
            sys.path.pop(0)
        connection = _connect(environment or os.environ)
        FreshSchema(connection, ddl, edit_ddl=edit_ddl, audit_ddl=audit_ddl).install()
        marker.unlink()
        return True
    except Exception:
        # Driver/schema errors may embed credentials or row values.
        raise RuntimeError('CloudFile V2 fresh schema initialization failed; '
                           'inspect existing cf_* tables before retry') from None
    finally:
        if connection is not None:
            connection.close()


def verify_development_schema(installdir=None, environment=None):
    """Fail startup with an operator action, never migrate a development DB."""
    environment = os.environ if environment is None else environment
    connection = None
    try:
        connection = _connect(environment)
        verify_v2_schema(connection, checkout_enabled=_checkout_enabled(environment))
    except Exception:
        # Driver details may contain credentials. Never invoke a legacy runner
        # or restore old fields when this fails: use the fixed release SQL pack.
        raise RuntimeError('CloudFile development schema check failed; stop writers and apply the reviewed database/v2 SQL package before starting services') from None
    finally:
        if connection is not None:
            connection.close()
