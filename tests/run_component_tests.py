"""Source-mounted development tests; deliberately not release evidence."""
import io
import json
import os
import sys
import time
import unittest

import pymysql
import redis

deadline = time.monotonic() + 120
while True:
    try:
        connection = pymysql.connect(host='test-db', user='root', password='')
        connection.close()
        redis.Redis(host='test-redis').ping()
        break
    except (pymysql.MySQLError, redis.RedisError):
        if time.monotonic() >= deadline:
            raise SystemExit('Component services readiness timeout')
        time.sleep(1)

modules = json.load(sys.stdin)
suite = unittest.defaultTestLoader.loadTestsFromNames(modules)
output = io.StringIO()
started = time.monotonic()
result = unittest.TextTestRunner(stream=output, verbosity=2).run(suite)
report = dict(tests=result.testsRun, skipped=[test.id() for test, reason in result.skipped],
    failures=[test.id() for test, trace in result.failures],
    errors=[test.id() for test, trace in result.errors],
    seconds=round(time.monotonic() - started, 3))
# Test output and tracebacks can contain fixture secrets; report IDs only.
print(json.dumps(report))
raise SystemExit(0 if result.wasSuccessful() and not result.skipped and result.testsRun else 1)
