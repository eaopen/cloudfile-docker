#!/usr/bin/env python3
"""Read one value out of release.yaml.

A deliberately tiny line-based reader rather than PyYAML: the build image
installs no extra Python packages, and release.yaml is a flat two-level
mapping that does not need a real parser.

Usage:
    read-manifest.py <release.yaml> upstream.seafobj
    read-manifest.py <release.yaml> forks.cloudfile_server.ref

Exits non-zero and prints nothing when the key is absent, so callers can tell
"missing" apart from "empty".
"""

import re
import sys


def load(path):
    """Parse the file into {dotted.key: value}."""
    values = {}
    stack = []          # [(indent, key), ...]

    with open(path, encoding='utf-8') as fp:
        for raw in fp:
            line = raw.rstrip('\n')
            if not line.strip() or line.lstrip().startswith('#'):
                continue

            indent = len(line) - len(line.lstrip(' '))
            match = re.match(r'^\s*([A-Za-z0-9_]+):\s*(.*)$', line)
            if not match:
                continue

            key, value = match.group(1), match.group(2)

            while stack and stack[-1][0] >= indent:
                stack.pop()

            path_parts = [k for _, k in stack] + [key]

            # Strip trailing comments, then quotes.
            value = re.sub(r'\s+#.*$', '', value).strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in '"\'':
                value = value[1:-1]

            if value == '':
                stack.append((indent, key))
            else:
                values['.'.join(path_parts)] = value

    return values


def main():
    if len(sys.argv) != 3:
        sys.stderr.write(__doc__)
        return 2

    values = load(sys.argv[1])
    key = sys.argv[2]
    if key not in values:
        return 1

    print(values[key])
    return 0


if __name__ == '__main__':
    sys.exit(main())
