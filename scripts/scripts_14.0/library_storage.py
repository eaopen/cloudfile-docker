"""Explicit V2 local-storage transition, using the Hub's native inventory CLI."""
from configparser import ConfigParser
from io import StringIO
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile

LIBRARY_ROOT = '/shared/seafile/library-storage'
BEGIN = '# --- CloudFile (generated, do not edit) ---'
END = '# --- end CloudFile ---'
BACKEND_SECTIONS = frozenset(('storage', 'commit_object_backend', 'fs_object_backend', 'block_backend'))


def _read_config(path):
    config = ConfigParser(interpolation=None)
    if path.exists():
        with path.open() as stream:
            config.read_file(stream)
    return config


def auto_storage_enabled(path, environment, *, fresh=False):
    mode = environment.get('CF_LIBRARY_STORAGE', '').strip()
    if mode not in ('', 'auto'):
        raise ValueError('CF_LIBRARY_STORAGE must be auto or unset')
    if mode == 'auto':
        return True
    if fresh and environment.get('CF_ENABLE_S3_STORAGE', 'false').lower() != 'true' and not environment.get('SEAF_SERVER_STORAGE_TYPE', ''):
        return True
    # Retain an already selected V2 mode across restarts without opting an
    # existing legacy installation into a transition when its variable is absent.
    return bool(_read_config(Path(path)).get('cloudfile_v2', 'auto_local_root', fallback=''))


def retained_legacy_storage(path):
    """Preserve persisted generated multi/S3 settings when legacy mode is unset.

    The old Compose overlay supplied values independently of .env; removing
    that overlay's defaults must not erase those persisted backend settings.
    """
    path = Path(path)
    if not path.exists():
        return ''
    current = _read_config(path)
    outside = ConfigParser(interpolation=None)
    outside.read_string(_without_generated(path.read_text()))
    retained = ConfigParser(interpolation=None)
    for section in sorted(BACKEND_SECTIONS):
        if current.has_section(section) and not outside.has_section(section):
            retained[section] = dict(current.items(section))
    output = StringIO()
    retained.write(output)
    return output.getvalue()


def retained_legacy_switch(path):
    """Keep the legacy allocator switch together with retained storage classes.

    The removed Compose overlay also supplied CF_ENABLE_S3_STORAGE=true. Its
    persisted multi routing survives without that value, so new libraries must
    keep the same automatic allocation rather than silently using the default.
    """
    path = Path(path)
    if not path.exists():
        return False
    current = _read_config(path)
    return (current.getboolean('storage', 'enable_storage_classes', fallback=False) and
            current.getboolean('cloudfile', 's3_storage_enabled', fallback=False))


def _require_root():
    root = Path(LIBRARY_ROOT)
    for path in (root, *root.parents):
        if path.is_symlink():
            raise ValueError('Storage root and its ancestors must not be symbolic links: ' + str(path))
    if not root.is_dir():
        raise ValueError('Storage root must already exist as a directory: ' + str(root))


def _without_generated(text):
    lines = text.splitlines(keepends=True)
    starts = [i for i, line in enumerate(lines) if line.strip() == BEGIN]
    ends = [i for i, line in enumerate(lines) if line.strip() == END]
    if not starts and not ends:
        return text
    if len(starts) != 1 or len(ends) != 1 or ends[0] < starts[0]:
        raise ValueError('Invalid generated configuration markers')
    return ''.join(lines[:starts[0]] + lines[ends[0] + 1:])


def _render_auto(original, generated_body):
    # Explicit transition owns the storage backend sections. Preserve other
    # operator sections verbatim; retire legacy classes only after preflight.
    out, skipping = [], False
    for line in _without_generated(original).splitlines(keepends=True):
        match = re.match(r'^\s*\[([^]]+)\]', line)
        if match:
            skipping = match.group(1).strip() in BACKEND_SECTIONS or match.group(1).strip() == 'cloudfile_v2'
        if not skipping:
            out.append(line)
    body = generated_body + '\n[cloudfile_v2]\nauto_local_root = %s\n' % LIBRARY_ROOT
    body += '\n[storage]\nenable_storage_classes = false\n'
    for section in ('commit_object_backend', 'fs_object_backend', 'block_backend'):
        body += '\n[%s]\nname = filesystem\n' % section
    return ''.join(out).rstrip() + '\n\n' + BEGIN + '\n' + body + END + '\n'


def configure_auto_storage(conf, generated_body, installdir, environment=None):
    """Preflight old routing, register supported libraries, then replace config.

    Neither a failed preflight nor a failed apply changes seafile.conf. Apply
    is per-library transactional and may be retried after partial success.
    """
    environment = dict(os.environ if environment is None else environment)
    conf, installdir = Path(conf), Path(installdir)
    _require_root()
    original = conf.read_text() if conf.exists() else ''
    current = _read_config(conf)
    current_root = current.get('cloudfile_v2', 'auto_local_root', fallback='')
    if current_root and current_root != LIBRARY_ROOT:
        raise ValueError('Existing auto_local_root differs from the required storage root')
    # Validate the final output before any SQL write, while inventory continues
    # to see original storage classes/backend paths in its temporary candidate.
    final = _render_auto(original, generated_body)
    check = ConfigParser(interpolation=None)
    check.read_string(final)
    if not current.has_section('cloudfile_v2'):
        current.add_section('cloudfile_v2')
    current.set('cloudfile_v2', 'auto_local_root', LIBRARY_ROOT)
    hub = installdir / 'seahub'
    # CE commonly links /opt/seafile/seafile-data to the persisted native tree.
    # Resolve that upstream layout without relaxing managed-root validation.
    native = (conf.parent.parent / 'seafile-data').resolve(strict=True)
    cli_env = dict(environment)
    cli_env['SEAFILE_DATA_DIR'] = str(native)
    cli_env['SEAFILE_CENTRAL_CONF_DIR'] = str(conf.parent.resolve(strict=True))
    # The persisted Seafile configuration, rather than a future Compose value,
    # describes the current routing that must pass the transition preflight.
    cli_env.pop('CF_STORAGE_CLASSES_JSON', None)
    for suffix, source, default in (
            ('HOST', 'SEAFILE_MYSQL_DB_HOST', 'db'),
            ('PORT', 'SEAFILE_MYSQL_DB_PORT', '3306'),
            ('USER', 'SEAFILE_MYSQL_DB_USER', 'seafile'),
            ('PASSWORD', 'SEAFILE_MYSQL_DB_PASSWORD', ''),
            ('NAME', 'SEAFILE_MYSQL_DB_SEAFILE_DB_NAME', 'seafile_db')):
        cli_env['CF_V2_DB_' + suffix] = environment.get(source, default)
    cli_env['PYTHONPATH'] = str(hub) + os.pathsep + environment.get('PYTHONPATH', '')
    candidate_path = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', prefix='.storage-preflight-', suffix='.conf',
                                         dir=conf.parent, delete=False) as stream:
            candidate_path = stream.name
            current.write(stream)
        command = [sys.executable, '-m', 'cloudfile_ext.v2', 'storage-reconcile',
                   '--seafile-conf', candidate_path, '--seafile-data', str(native)]
        for mode in ('--dry-run', '--apply'):
            result = subprocess.run(command + [mode], cwd=hub, env=cli_env,
                                    capture_output=True, text=True, timeout=120)
            # Preserve the CLI's complete single JSON report in startup output.
            print(result.stdout, end='' if result.stdout.endswith('\n') else '\n', flush=True)
            try:
                report = json.loads(result.stdout)
                if (report.get('mode') != ('apply' if mode == '--apply' else 'dry-run') or
                        not isinstance(report.get('items'), list) or
                        not isinstance(report.get('orphan_directories'), list)):
                    raise ValueError()
                summary = report['summary']
                if not isinstance(summary, dict) or any(type(value) is not int or value < 0 for value in summary.values()):
                    raise ValueError()
                blocked = summary.get('BLOCKED', 0) or summary.get('NATIVE_CLASS_PINNED', 0)
            except (ValueError, KeyError, TypeError):
                raise RuntimeError('Invalid storage preflight report; seafile.conf is unchanged') from None
            if result.returncode or blocked:
                raise RuntimeError('Storage transition refused; inspect the JSON report and explicitly normalize pinned native classes before retrying')
        _atomic_write(conf, final)
    finally:
        if candidate_path is not None:
            Path(candidate_path).unlink(missing_ok=True)


def _atomic_write(path, body):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', prefix='.storage-config-', dir=path.parent, delete=False) as stream:
            temporary = stream.name
            if path.exists():
                os.fchmod(stream.fileno(), stat.S_IMODE(path.stat().st_mode))
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)
