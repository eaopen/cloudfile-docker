#!/usr/bin/env python3
"""Explicit fixed backchannel worker, using the verified standalone lifecycle."""
from pathlib import Path
import runpy
import sys

if __name__ == '__main__':
    entry = runpy.run_path(str(Path(__file__).with_name('cloudfile-jit-worker.py')))
    sys.exit(entry['main'](logout=True))
