#!/usr/bin/env python3
"""Validate and count the P2-02 review-checklist case sets.

Each module's contract is docs/review-<module>-cases.json. This script checks the
schema (so the files stay machine-readable) and prints a per-module count of
api vs ui cases (so they stay countable). It is the fast, no-container gate for
P2-02: the case set is the contract that P2-03/P2-06/P2-07 implement against.

Usage:

    python3 tools/validate-review-cases.py
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.abspath(os.path.join(HERE, '..', 'docs'))

MODULES = ['tree', 'icon', 'copy', 'move', 'tags', 'search', 'history',
           'recycle', 'share']

REQUIRED_CASE_KEYS = ['id', 'name', 'review', 'channel', 'perm', 'expect']
CHANNELS = {'api', 'ui'}


def fail(msg):
    print(f'✗ {msg}', file=sys.stderr)


def validate_case(module, case, seen_ids):
    errors = []
    for key in REQUIRED_CASE_KEYS:
        if key not in case:
            errors.append(f'missing key {key!r}')
    cid = case.get('id', '<missing>')
    if not isinstance(cid, str) or not cid.startswith(module + '-'):
        errors.append(f'id {cid!r} must be a string prefixed {module}-')
    if cid in seen_ids:
        errors.append(f'duplicate id {cid!r}')
    seen_ids.add(cid)
    if case.get('channel') not in CHANNELS:
        errors.append(f'channel {case.get("channel")!r} must be one of {sorted(CHANNELS)}')
    return errors


def main():
    problems = 0
    total = api = ui = 0
    print('module   api  ui  total')
    print('------   ---  --  -----')
    for module in MODULES:
        path = os.path.join(DOCS, f'review-{module}-cases.json')
        if not os.path.isfile(path):
            fail(f'{module}: missing {path}')
            problems += 1
            continue
        with open(path, encoding='utf-8') as fh:
            doc = json.load(fh)

        mod_errors = []
        if doc.get('version') != 1:
            mod_errors.append(f'version {doc.get("version")!r} != 1')
        if doc.get('module') != module:
            mod_errors.append(f'module {doc.get("module")!r} != filename {module}')
        if not isinstance(doc.get('cases'), list) or not doc['cases']:
            mod_errors.append('cases must be a non-empty list')

        seen_ids = set()
        a = u = 0
        for case in doc.get('cases', []):
            case_errors = validate_case(module, case, seen_ids)
            if case_errors:
                mod_errors.append(f'{case.get("id", "<no-id>")}: {"; ".join(case_errors)}')
            if case.get('channel') == 'api':
                a += 1
            elif case.get('channel') == 'ui':
                u += 1

        if mod_errors:
            problems += 1
            for e in mod_errors:
                fail(f'{module}: {e}')
        else:
            print(f'{module:6}  {a:3}  {u:2}  {a + u:5}')
        api += a
        ui += u
        total += a + u

    print('------   ---  --  -----')
    print(f'{"TOTAL":6}  {api:3}  {ui:2}  {total:5}')
    print()
    if problems:
        print(f'{problems} module(s) have schema errors', file=sys.stderr)
        return 1
    print('schema OK; all case ids unique and channel-tagged.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
