#!/usr/bin/env python3
"""Standalone bounded audit exports and expiry cleanup; no web-process thread."""
import argparse
import json
from pathlib import Path
import runpy
import signal
import sys
import threading
from uuid import uuid4


def bootstrap():
    entry = runpy.run_path(str(Path(__file__).with_name('cloudfile-jit-worker.py')))
    entry['bootstrap']()


def database_environment(config):
    # Derive from the authority host, never a second independently selected DB.
    database = config['database']
    return {'CLOUDFILE_DB_' + name.upper(): str(database.get('port', 3306) if name == 'port' else database[name])
            for name in ('host', 'user', 'name', 'password', 'port')}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Run CloudFile audit exports and private result cleanup')
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--poll-seconds', type=int, default=2)
    parser.add_argument('--lease-seconds', type=int, default=30)
    arguments = parser.parse_args(argv)
    initialized = False
    hooks = None
    previous_signals = {}
    result = 0
    try:
        if not 1 <= arguments.poll_seconds <= 30 or not 1 <= arguments.lease_seconds <= 300:
            raise ValueError('invalid worker limits')
        bootstrap()
        from django.conf import settings
        from cloudfile_extensions.authorization import gunicorn
        from cloudfile_extensions.events.background import AuditBackground
        from cloudfile_extensions.events.configuration import require_export_configuration
        require_export_configuration(settings)
        hooks = gunicorn
        if hooks._host is not None:
            raise ValueError('standalone process required')
        hooks.post_worker_init(None)
        initialized = True
        stop = threading.Event()
        for number in (signal.SIGTERM, signal.SIGINT):
            previous_signals[number] = signal.signal(number, lambda *_: stop.set())
        with AuditBackground(hooks._host.deployment.audit_factory,
                environment=database_environment(settings.CLOUDFILE_POLICY_CONFIG),
                owner='audit-' + uuid4().hex, lease_seconds=arguments.lease_seconds) as worker:
            worker.run(stop, poll_seconds=arguments.poll_seconds, once=arguments.once,
                emit=lambda value: print(json.dumps(value), flush=True))
    except Exception:
        print('CloudFile audit worker failed; check enablement, private results, schema and authority',
              file=sys.stderr)
        result = 1
    finally:
        for number, previous in previous_signals.items():
            signal.signal(number, previous)
        if initialized:
            try:
                hooks.worker_exit(None, None)
            except Exception:
                print('CloudFile audit worker cleanup failed', file=sys.stderr)
                result = 1
    return result


if __name__ == '__main__':
    sys.exit(main())
