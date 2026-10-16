#!/usr/bin/env python3
"""Test the assembled source in an isolated interpreter, never the fork runtime."""
import argparse
from pathlib import Path
import subprocess
import sys

parser = argparse.ArgumentParser()
parser.add_argument('--source', type=Path, required=True)
args = parser.parse_args()
source = args.source.resolve()
program = '''
import os, sys, unittest
from pathlib import Path
source = Path(sys.argv[1])
assert not (source / 'seahub/cloudfile_extensions').exists()
assert not (source / 'seahub/cloudfile_ext/apps.py').exists()
sys.path.insert(0, str(source / 'seahub'))
os.environ['CF_V2_SOURCE'] = str(source)
os.environ['CF_V2_DDL'] = str(source / 'seafile-server/scripts/sql/mysql/cloudfile-v2.sql')
suite = unittest.defaultTestLoader.loadTestsFromName('cloudfile_ext.v2.tests.test_fresh')
result = unittest.TextTestRunner(verbosity=2).run(suite)
assert not any(name == 'cloudfile_extensions' or name.startswith('cloudfile_extensions.') for name in sys.modules)
sys.exit(not result.wasSuccessful() or bool(result.skipped) or result.testsRun < 14)
'''
raise SystemExit(subprocess.call([sys.executable, '-I', '-c', program, str(source)]))
