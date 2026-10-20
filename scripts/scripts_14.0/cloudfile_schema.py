"""Read-only startup gate; development DDL is applied with reviewed SQL files."""
import os

# Keep these names aligned with database/v2/20261021-four-table-baseline/00-create.sql.
# Table existence alone previously enabled an incompatible Guard on every upload.
COLUMNS = {
    'cf_library_storage': 'repo_key repo_id state',
    'cf_sso_group_map': 'provider subject_type namespace external_id group_id',
    'cf_dir_acl': 'repo_id path_hash path subject_type provider namespace external_id permission inherit share_mode revision',
    'cf_edit_guard': 'repo_id path_hash path guard_id generation owner_uid owner_native_user terminal_type terminal_name checkout_ip proof_digest base_file_id lease_expires_at created_at updated_at',
}
INDEXES = {
    'cf_library_storage': {'PRIMARY': (0, ('repo_key',)), 'library_storage_repo': (0, ('repo_id',))},
    'cf_sso_group_map': {'PRIMARY': (0, ('provider','subject_type','namespace','external_id')), 'sso_native_group': (0, ('group_id',))},
    'cf_dir_acl': {'PRIMARY': (0, ('repo_id','path_hash','subject_type','provider','namespace','external_id')),
                   'acl_shared_subject': (1, ('provider','subject_type','namespace','external_id','share_mode','repo_id'))},
    'cf_edit_guard': {'PRIMARY': (0, ('repo_id','path_hash')), 'cf_edit_guard_id': (0, ('guard_id',)),
                      'cf_edit_guard_active': (1, ('repo_id','guard_id')), 'cf_edit_guard_owner': (1, ('owner_uid','guard_id'))},
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


def verify_development_schema(installdir=None, environment=None):
    """Fail startup with an operator action, never migrate a development DB."""
    environment = os.environ if environment is None else environment
    connection = None
    try:
        import pymysql
        connection = pymysql.connect(
            host=environment['SEAFILE_MYSQL_DB_HOST'],
            port=int(environment.get('SEAFILE_MYSQL_DB_PORT', '3306')),
            user=environment.get('SEAFILE_MYSQL_DB_USER', 'seafile'),
            password=environment['SEAFILE_MYSQL_DB_PASSWORD'],
            database=environment.get('SEAFILE_MYSQL_DB_SEAFILE_DB_NAME', 'seafile_db'),
            charset='utf8mb4', autocommit=True, connect_timeout=5,
        )
        requested = str(environment.get('CF_ENABLE_CHECKOUT', 'false')).lower()
        if requested not in ('true', 'false'):
            raise ValueError('invalid Checkout setting')
        verify_v2_schema(connection, checkout_enabled=requested == 'true')
    except Exception:
        # Driver details may contain credentials. Never invoke a legacy runner
        # or restore old fields when this fails: use the fixed release SQL pack.
        raise RuntimeError('CloudFile development schema check failed; stop writers and apply the reviewed database/v2 SQL package before starting services') from None
    finally:
        if connection is not None:
            connection.close()
