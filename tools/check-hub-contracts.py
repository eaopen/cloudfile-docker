#!/usr/bin/env python3
"""Run full-fork contracts or pinned clean-V2 HTTP units in isolated processes."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

here = Path(__file__).resolve().parent
workspace = here.parents[1]
hub = workspace / 'cloudfile-hub'

if '--v2' in sys.argv:
    # V2 native seams are immutable reviewed overlays, not the full fork tree.
    # Reuse production assembly and its receipt; never copy candidate files into dev.
    spec = importlib.util.spec_from_file_location('prepare_v2_source', here / 'prepare-v2-source.py')
    prepare = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prepare)
    sources = json.loads((here.parent / 'build/v2/source-set.json').read_text())
    refs = {name: config['overlay_commit'] for name, config in sources['components'].items()}
    with tempfile.TemporaryDirectory(prefix='cf-v2-http-') as temporary:
        output = Path(temporary) / 'source'
        receipt = prepare.assemble(workspace, output, sources, refs)
        print('V2 HTTP native source pins: ' + json.dumps(refs), flush=True)
        assert receipt['components']['cloudfile-hub']['overlay_commit'] == refs['cloudfile-hub']
        env = dict(os.environ, CF_CHECK_NATIVE_ROOT=str(output / 'seahub'))
        # Current regression tests run against the pinned production modules.
        raise SystemExit(subprocess.call([sys.executable, __file__,
            str(hub / 'cloudfile_ext/v2/tests'), '--import-mode=importlib'], env=env))

os.chdir(hub)
sys.path.insert(0, str(hub))
if os.environ.get('CF_CHECK_NATIVE_ROOT'):
    sys.path.insert(0, os.environ['CF_CHECK_NATIVE_ROOT'])
sys.path.insert(0, str(hub / 'tests'))
from isolated_native import install
install(os.environ.get('CF_CHECK_NATIVE_ROOT'))
import pytest

raise SystemExit(pytest.main(['-q', '--tb=short', '-c', os.devnull, '--rootdir', str(hub),
    *(sys.argv[1:] or ['cloudfile_extensions/tests'])]))
