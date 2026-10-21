"""Minimal native volume/database wiring; Seafile owns upgrades and objects.

Do not bootstrap a fresh database when an existing native volume is present.
Native RPC validates reads; native upgrade scripts and FSCK own data upgrades.
"""
from pathlib import Path


class NativeStartupError(RuntimeError):
    pass


def volume_layout(shared):
    """Recognize both CE's nested layout and an existing flat V2 deployment."""
    shared = Path(shared)
    nested = shared / 'seafile'
    legacy = (nested / 'seafile-data').exists() or (nested / 'conf').exists()
    flat = (shared / 'seafile-data').exists() or (shared / 'conf/seafile.conf').exists()
    if (shared / 'storage').exists() or (nested.is_dir() and not legacy and next(nested.iterdir(), None) is not None):
        raise NativeStartupError('NATIVE_LAYOUT_REQUIRES_REVIEW: unrecognized existing storage')
    # Two plausible roots are not permission to choose one and hide the other.
    if legacy and flat:
        raise NativeStartupError('AMBIGUOUS_NATIVE_STORAGE: multiple existing data roots')
    root = nested if legacy else shared
    data, conf = root / 'seafile-data', root / 'conf'
    reused = legacy or flat
    if reused and (not data.is_dir() or not (conf / 'seafile.conf').is_file()):
        raise NativeStartupError('NATIVE_STORAGE_MISSING: existing data/config must be mounted together')
    return root, reused


def require_native_ce14(data):
    """Honor Seafile's existing version stamp instead of inventing migrations."""
    stamp = Path(data) / 'current_version'
    if stamp.is_file() and stamp.read_text().strip().split('.')[:2] != ['14', '0']:
        raise NativeStartupError('NATIVE_UPGRADE_REQUIRED: use Seafile official upgrade scripts first')


def load_native_environment(original, environment):
    """A persisted database binding must not silently lose to a new env file."""
    import shlex
    filename = Path(original) / '.env'
    if not filename.is_file():
        return
    for line in filename.read_text().splitlines():
        key, separator, value = line.partition('=')
        key = key.strip()
        if not separator or not key or key.startswith('#'):
            continue
        values = shlex.split(value)
        if len(values) > 1:
            raise NativeStartupError('INVALID_NATIVE_ENVIRONMENT')
        value = values[0] if values else ''
        if key.startswith('SEAFILE_MYSQL_DB_') and key in environment and environment[key] != value:
            # Include the setting name only; never print credentials or values.
            raise NativeStartupError('NATIVE_DATABASE_BINDING_CHANGED: ' + key)
        environment.setdefault(key, value)


def native_environment(config, previous, environment):
    """Flat V2 restarts reuse persisted names instead of becoming fresh installs."""
    fields = {'host': 'HOST', 'port': 'PORT', 'user': 'USER', 'password': 'PASSWORD'}
    hub = previous.get('DATABASES', {}).get('default', {})
    for native, django in fields.items():
        value = config.get('database', native, fallback=None) or hub.get(django)
        if value not in (None, ''):
            environment.setdefault('SEAFILE_MYSQL_DB_' + native.upper(), str(value))
    for option, suffix in [('db_name', 'SEAFILE_DB_NAME'), ('ccnet_db_name', 'CCNET_DB_NAME')]:
        value = config.get('database', option, fallback=None)
        if value:
            environment.setdefault('SEAFILE_MYSQL_DB_' + suffix, value)
    if hub.get('NAME'):
        environment.setdefault('SEAFILE_MYSQL_DB_SEAHUB_DB_NAME', hub['NAME'])
    for alias, native in [('DB_HOST', 'HOST'), ('DB_PASSWORD', 'PASSWORD')]:
        target = 'SEAFILE_MYSQL_DB_' + native
        if alias in environment and environment.get(target) != environment[alias]:
            raise NativeStartupError('NATIVE_DATABASE_BINDING_CHANGED: ' + alias)


def verify_database_binding(config, environment, previous):
    """Check persisted C/Hub database settings against the selected connection."""
    selected = {'host': environment['SEAFILE_MYSQL_DB_HOST'],
                'port': environment.get('SEAFILE_MYSQL_DB_PORT', '3306'),
                'user': environment['SEAFILE_MYSQL_DB_USER'],
                'password': environment['SEAFILE_MYSQL_DB_PASSWORD'],
                'db_name': environment['SEAFILE_MYSQL_DB_SEAFILE_DB_NAME'],
                'ccnet_db_name': environment['SEAFILE_MYSQL_DB_CCNET_DB_NAME']}
    if config.has_section('database'):
        for key, value in selected.items():
            if config.has_option('database', key) and config.get('database', key) != value:
                raise NativeStartupError('NATIVE_DATABASE_BINDING_CHANGED: native ' + key)
    hub = previous.get('DATABASES', {}).get('default', {})
    for key, value in {'HOST': selected['host'], 'PORT': selected['port'],
                       'USER': selected['user'], 'PASSWORD': selected['password'],
                       'NAME': environment['SEAFILE_MYSQL_DB_SEAHUB_DB_NAME']}.items():
        if hub.get(key) not in (None, '') and str(hub[key]) != value:
            raise NativeStartupError('NATIVE_DATABASE_BINDING_CHANGED: hub ' + key)
    # CE can use env-only database settings. Make the same validated binding
    # explicit in the ephemeral C configuration; leave original files intact.
    if not config.has_section('database'):
        config.add_section('database')
    config.set('database', 'type', 'mysql')
    for key, value in selected.items():
        config.set('database', key, value)


def verify_native_reads(repo_ids, native_api):
    """Delegate commits, virtual origins and storage paths to native Seafile.

    A bounded root listing proves the native reader can open each old library;
    never implement a second object decoder or return users/file names in logs.
    Full historical object/block integrity remains native seaf-fsck's job.
    """
    for repo in repo_ids:
        try:
            if native_api.get_repo(repo) is None or native_api.list_dir_by_path(repo, '/', 0, 1) is None:
                raise ValueError('Native repository not readable')
        except Exception:
            raise NativeStartupError('NATIVE_REPO_UNREADABLE: ' + repo) from None

