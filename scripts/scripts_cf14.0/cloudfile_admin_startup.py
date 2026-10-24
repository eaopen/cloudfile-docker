"""One bounded CloudFile administrator sync after a normal Seafile startup.

Do not run from Seahub/Gunicorn worker initialization: those launch repeatedly
and must never create another background reconciliation loop.
"""
import os
import shlex
import subprocess


def run_provider_admin_sync(seahub_script, manage_script, *, non_root=False,
                            enabled=None, runner=subprocess.run):
    if enabled is None:
        enabled = os.getenv('CF_PROVIDER_ADMIN_STARTUP_SYNC_ENABLED', 'false').lower() == 'true'
    if enabled is not True:
        return 'SKIPPED'
    command = [seahub_script, 'python-env', 'python3', manage_script,
               'cf_sync_provider_admins']
    if non_root:
        command = ['su', '-p', 'seafile', '-c', shlex.join(command)]
    try:
        # Only one process per container start. Provider request has its own
        # 5s bound; leave some time for CE SQL/RPC. Never block the file service
        # if an external enterprise Directory is unavailable.
        result = runner(command, capture_output=True, text=True, timeout=30,
                        check=False)
        if result.returncode:
            print('CF_ADMIN_SYNC FAILED (nonfatal): command returned %d'
                  % result.returncode, flush=True)
            return 'FAILED'
        # The command prints counts only. Do not leak accounts or credentials.
        line = (result.stdout or '').strip().splitlines()
        print(line[-1] if line else 'CF_ADMIN_SYNC COMPLETED', flush=True)
        return 'APPLIED'
    except (OSError, subprocess.SubprocessError):
        print('CF_ADMIN_SYNC FAILED (nonfatal): command unavailable', flush=True)
        return 'FAILED'
