#!/usr/bin/env python3
"""Wait for the CloudFile stack to be ready (ping 200 + settle).

Small CLI so shell orchestration scripts can block on readiness without
re-importing the whole review_harness machinery.
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from review_harness import request


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--url', required=True)
    ap.add_argument('--timeout', type=int, default=600)
    args = ap.parse_args()
    deadline = time.time() + args.timeout
    while time.time() < deadline:
        status, body = request(args.url.rstrip('/') + '/api2/ping/')
        if status == 200 and 'pong' in body:
            print('就绪', flush=True)
            return 0
        time.sleep(5)
    print('超时未就绪', file=sys.stderr)
    return 1


if __name__ == '__main__':
    sys.exit(main())
