#!/usr/bin/env python3
"""Standalone bounded resource search initialization, rebuild and consumption."""
import argparse
import json
import os
import traceback
from pathlib import Path
import runpy
import signal
import sys
import threading
from uuid import UUID, uuid4


def main(argv=None):
    parser = argparse.ArgumentParser(description='Operate the configured CloudFile resource search generation')
    parser.add_argument('operation', choices=('initialize', 'rebuild', 'consume'))
    parser.add_argument('--repo-id')
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--poll-seconds', type=int, default=2)
    arguments = parser.parse_args(argv)
    hooks = None
    initialized = False
    previous = {}
    result = 0
    try:
        if not 1 <= arguments.poll_seconds <= 30:
            raise ValueError('bounded poll interval required')
        if (arguments.operation == 'rebuild') != (arguments.repo_id is not None):
            raise ValueError('only rebuild requires a fixed repository')
        if arguments.repo_id is not None and str(UUID(arguments.repo_id)) != arguments.repo_id:
            raise ValueError('canonical repository required')
        runpy.run_path(str(Path(__file__).with_name('cloudfile-jit-worker.py')))['bootstrap']()
        from django.conf import settings
        from cloudfile_extensions.common.errors import ContractError
        from cloudfile_extensions.search.configuration import require_configuration
        from cloudfile_extensions.identity.configuration import configure_oidc_host
        from cloudfile_extensions.authorization import gunicorn
        if require_configuration(settings) is None:
            raise ValueError('resource search is disabled')
        configure_oidc_host(settings)
        hooks = gunicorn
        if hooks._host is not None:
            raise ValueError('standalone process required')
        hooks.post_worker_init(None)
        initialized = True
        host = hooks._host.deployment.search_host
        stop = threading.Event()
        for number in (signal.SIGTERM, signal.SIGINT):
            previous[number] = signal.signal(number, lambda *_: stop.set())
        owner = 'search-' + uuid4().hex
        while not stop.is_set():
            if arguments.operation == 'initialize':
                with host.initialize.open() as runtime:
                    state = runtime.store.registry.register(runtime.generation, runtime.client.index)
                    if state != 'building':
                        raise ValueError('retired generation cannot initialize')
                    complete = runtime.advance()
                if complete:
                    host.capture_global_baseline()
                value = dict(state='initialized' if complete else 'pending')
            elif arguments.operation == 'consume':
                with host.consumer(owner).open() as runtime:
                    value = dict(state=runtime.run_once())
                complete = False
            else:
                with host.rebuild.open() as runtime:
                    runtime.start(repo_id=arguments.repo_id)
                    value = runtime.advance(repo_id=arguments.repo_id)
                    if value['state'] == 'scanned':
                        local = runtime.advance_catchup(repo_id=arguments.repo_id)
                        global_state = runtime.advance_global_catchup()
                        needs_consumer = True
                        if local['state'] == global_state['state'] == 'observed_cutoff_checked':
                            local = runtime.refresh_catchup_target(repo_id=arguments.repo_id)
                            global_state = runtime.refresh_global_catchup_target()
                            if local['state'] == global_state['state'] == 'complete':
                                try:
                                    value = dict(state='published', **runtime.publish(repo_id=arguments.repo_id))
                                    needs_consumer = False
                                except ContractError as error:
                                    if error.code not in {'SEARCH_TASK_PENDING', 'SEARCH_CATCHUP_PENDING'}:
                                        raise
                        if needs_consumer:
                            with host.consumer(owner).open() as consumer:
                                if consumer.run_once() == 'recovery_required':
                                    raise ValueError('durable projection recovery required')
                            value = dict(state='pending')
                    complete = value['state'] == 'published'
            # State only: never print document contents, credentials or cursors.
            print(json.dumps({'operation': arguments.operation, 'state': value['state']}), flush=True)
            if arguments.once or complete:
                break
            if value['state'] == 'recovery_required':
                raise ValueError('durable projection recovery required')
            stop.wait(arguments.poll_seconds)
    except Exception as error:
        if os.environ.get('CF_DISPOSABLE_IDENTITY_PROBE') == 'true':
            print('CF_SEARCH_WORKER_DIAGNOSTIC=' + json.dumps({'type': type(error).__name__,
                'frames': [(frame.filename.rsplit('/', 1)[-1], frame.name, frame.lineno)
                    for frame in traceback.extract_tb(error.__traceback__)[-5:]]}), file=sys.stderr)
        print('CloudFile search worker failed; check configuration, schema, native snapshot and durable task state', file=sys.stderr)
        result = 1
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)
        if initialized:
            try:
                hooks.worker_exit(None, None)
            except Exception:
                print('CloudFile search worker cleanup failed', file=sys.stderr)
                result = 1
    return result


if __name__ == '__main__':
    sys.exit(main())
