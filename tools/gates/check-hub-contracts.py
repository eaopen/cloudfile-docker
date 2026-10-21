#!/usr/bin/env python3
"""Run existing current-fork HTTP contracts with isolated native adapters."""
import os
from pathlib import Path
import sys

here = Path(__file__).resolve().parent
workspace = here.parents[2]
hub = workspace / 'cloudfile-hub'

# V2 runs the current fork's existing contracts. The retired overlay/source-set
# assembly no longer exists and must not select a second permission runtime.
arguments = sys.argv[1:]
if '--v2' in arguments:
    arguments.remove('--v2')
    if not arguments:
        arguments = ['cloudfile_ext/v2/tests']
if os.environ.get('CF_CHECK_NATIVE_ROOT'):
    hub = Path(os.environ['CF_CHECK_NATIVE_ROOT']).resolve()

os.chdir(hub)
sys.path.insert(0, str(hub))
if os.environ.get('CF_CHECK_NATIVE_ROOT'):
    sys.path.insert(0, os.environ['CF_CHECK_NATIVE_ROOT'])
sys.path.insert(0, str(hub / 'tests'))
from isolated_native import install
install(os.environ.get('CF_CHECK_NATIVE_ROOT'))
import pytest

raise SystemExit(pytest.main(['-q', '--tb=short', '-c', os.devnull, '--rootdir', str(hub),
    *(arguments or ['cloudfile_ext/v2/tests'])]))
