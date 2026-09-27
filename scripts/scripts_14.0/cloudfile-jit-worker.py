#!/usr/bin/env python3
"""Explicit standalone worker for authenticated, queued identity provisioning."""
import argparse
import json
import os
from pathlib import Path
import signal
import sys
import threading
from uuid import uuid4


def require_enabled(settings):
    if (getattr(settings, 'CLOUDFILE_OIDC_ENABLED', False) is not True or
            getattr(settings, 'CLOUDFILE_OIDC_JIT_ENABLED', False) is not True):
        raise ValueError('explicit OIDC and JIT enablement required')


def bootstrap():
    package = Path('/opt/seafile/seafile-server-latest')
    if not (package / 'seahub').is_dir():
        raise ValueError('initialized CE14 package required')
    sys.path[:0] = [str(package / 'seahub'), str(package / 'seahub/thirdpart'),
                   str(package / 'seafile/lib/python3/site-packages'), str(package / 'pro/python')]
    os.chdir(package / 'seahub')
    for key, value in dict(DJANGO_SETTINGS_MODULE='seahub.settings', SEAHUB_DIR=str(package / 'seahub'),
        SEAFES_DIR=str(package / 'pro/python'), SEAFILE_DATA_DIR='/shared/seafile/seafile-data',
        SEAFILE_CENTRAL_CONF_DIR='/shared/seafile/conf', SEAFILE_RPC_PIPE_PATH=str(package / 'runtime')).items():
        os.environ.setdefault(key, value)
    import django
    django.setup()


def main(argv=None):
    parser = argparse.ArgumentParser(description='Drain verified CloudFile JIT jobs; never start from a web request')
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--poll-seconds', type=int, default=2)
    parser.add_argument('--lease-seconds', type=int, default=30)
    arguments = parser.parse_args(argv)
    hooks = None
    initialized = False
    previous_signals = {}
    result = 0
    try:
        if not 1 <= arguments.poll_seconds <= 30 or not 1 <= arguments.lease_seconds <= 300:
            raise ValueError('invalid worker limits')
        bootstrap()
        from django.conf import settings
        from cloudfile_extensions.authorization import gunicorn
        from cloudfile_extensions.identity.background import ProvisioningBackground
        require_enabled(settings)
        hooks = gunicorn
        # Own a fresh process host; never close an existing caller's host.
        if hooks._host is not None:
            raise ValueError('standalone process required')
        hooks.post_worker_init(None)
        initialized = True
        stop = threading.Event()
        for number in (signal.SIGTERM, signal.SIGINT):
            previous_signals[number] = signal.signal(number, lambda *_: stop.set())
        with hooks.login_resources_scope() as resources:
            with ProvisioningBackground(resources.resources, issuer=resources.oidc.issuer,
                    owner='jit-' + uuid4().hex, enabled=True, lease_seconds=arguments.lease_seconds) as worker:
                worker.run(stop, poll_seconds=arguments.poll_seconds, once=arguments.once,
                    emit=lambda value: print(json.dumps(value), flush=True))
    except Exception:
        print('CloudFile JIT worker failed; check explicit enablement, configuration, schema and worker state',
              file=sys.stderr)
        result = 1
    finally:
        for number, previous in previous_signals.items():
            signal.signal(number, previous)
        if initialized:
            try:
                hooks.worker_exit(None, None)
            except Exception:
                print('CloudFile JIT worker cleanup failed', file=sys.stderr)
                result = 1
    return result


if __name__ == '__main__':
    sys.exit(main())
