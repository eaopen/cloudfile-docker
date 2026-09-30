#!/usr/bin/env python3
"""Run isolated Hub contracts without upstream native runtime settings."""
import os
from pathlib import Path
import sys

import django
from django.conf import settings
import pytest

hub = Path(__file__).resolve().parents[2] / 'cloudfile-hub'
os.chdir(hub)
sys.path.insert(0, str(hub))
settings.configure(SECRET_KEY='fixture-only', ALLOWED_HOSTS=['testserver'],
    DEFAULT_CHARSET='utf-8', INSTALLED_APPS=[],
    REST_FRAMEWORK={'UNAUTHENTICATED_USER': None})
django.setup()


class FailureDetails:
    def pytest_runtest_logreport(self, report):
        if report.failed:
            print('\n' + str(report.longrepr), flush=True)


raise SystemExit(pytest.main(['-q', '-c', os.devnull, '--rootdir', str(hub),
    'cloudfile_extensions/tests', *sys.argv[1:]], plugins=[FailureDetails()]))
