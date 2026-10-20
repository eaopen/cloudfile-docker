#!/usr/bin/env python3
"""Check reviewed cross-repository CREATE contracts without touching a database.

The complete migration runner remains responsible for ALTER/DROP and ledger
checks. This gate catches new table-name collisions and optional Checkout
columns/indexes drifting away from their actual reader before a build ships.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re


KNOWN_ISOLATED_LAYOUTS = {'cf_dir_acl', 'cf_sso_group_map', 'cf_edit_guard'}


def sql_steps(value):
    if isinstance(value, dict):
        for name, child in value.items():
            if name == 'sql' and isinstance(child, str):
                yield child
            else:
                yield from sql_steps(child)
    elif isinstance(value, list):
        for child in value:
            yield from sql_steps(child)


def split_definitions(body):
    depth, quote, start = 0, None, 0
    for index, char in enumerate(body):
        if char in "'\"`" and (index == 0 or body[index - 1] != '\\'):
            if quote == char:
                quote = None
            elif quote is None:
                quote = char
        if quote is None:
            if char == '(':
                depth += 1
            elif char == ')':
                depth -= 1
            elif char == ',' and depth == 0:
                yield body[start:index].strip()
                start = index + 1
    yield body[start:].strip()


def creates(sql):
    sql = re.sub(r'--[^\n]*', '', sql)
    for match in re.finditer(r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?`?(cf_\w+)`?\s*\((.*?)\)\s*ENGINE', sql, re.I | re.S):
        name, body = match.groups()
        columns, indexes = set(), {}
        for definition in split_definitions(body):
            first = definition.split()[0].strip('`').upper()
            if first not in {'PRIMARY', 'KEY', 'UNIQUE', 'CONSTRAINT', 'FOREIGN', 'CHECK', 'INDEX'}:
                columns.add(definition.split()[0].strip('`'))
            primary = re.match(r'PRIMARY\s+KEY\s*\(([^)]+)\)', definition, re.I)
            key = re.match(r'(UNIQUE\s+)?KEY\s+`?(\w+)`?\s*\(([^)]+)\)', definition, re.I)
            if primary:
                indexes['PRIMARY'] = (0, tuple(x.strip(' `') for x in primary[1].split(',')))
            elif key:
                indexes[key[2]] = (0 if key[1] else 1, tuple(x.strip(' `') for x in key[3].split(',')))
        yield name, frozenset(columns), indexes


def ddl_sources(server, hub):
    for name in ('cloudfile.sql', 'cloudfile-v2.sql', 'cloudfile-v2-edit.sql'):
        yield 'server/' + name, server / 'scripts/sql/mysql' / name
    for path in sorted((hub / 'cloudfile_extensions/schema/migrations').glob('*.json')):
        yield 'hub/' + path.name, path


def reviewed_ddl_digest(path):
    # Include ALTER/DROP, types, defaults and checks, not just CREATE column names.
    # Canonical JSON ignores formatting while preserving every SQL statement.
    value = path.read_text()
    if path.suffix == '.json':
        value = json.dumps(json.loads(value), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(value.encode()).hexdigest()


def audit(server, hub):
    contracts = {}
    definitions = 0
    for name in ('cloudfile.sql', 'cloudfile-v2.sql', 'cloudfile-v2-edit.sql'):
        path = server / 'scripts/sql/mysql' / name
        for table, columns, indexes in creates(path.read_text()):
            contracts.setdefault(table, []).append((name, columns, indexes))
            definitions += 1
    for path in sorted((hub / 'cloudfile_extensions/schema/migrations').glob('*.json')):
        for statement in sql_steps(json.loads(path.read_text())):
            for table, columns, indexes in creates(statement):
                contracts.setdefault(table, []).append((path.name, columns, indexes))
                definitions += 1
    collisions = {name for name, layouts in contracts.items()
                  if len({layout[1] for layout in layouts}) > 1}
    unexpected = collisions - KNOWN_ISOLATED_LAYOUTS
    if unexpected:
        raise ValueError('new incompatible table-name collision: ' + ', '.join(sorted(unexpected)))
    # Load only the dependency-free contract checker, never Django/settings/DDL.
    path = hub / 'cloudfile_ext/v2/checkout_schema.py'
    spec = importlib.util.spec_from_file_location('checkout_schema_contract', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    guards = contracts.get('cf_edit_guard', [])
    path_guard = next((x for x in guards if x[0] == 'cloudfile-v2-edit.sql'), None)
    resource_guard = next((x for x in guards if x[0] == '029_editing_core.json'), None)
    if path_guard is None or path_guard[1] != module.PATH_COLUMNS or path_guard[2] != module.PATH_INDEXES:
        raise ValueError('path Checkout reader and CREATE DDL columns/indexes differ')
    if resource_guard is None or resource_guard[1] != module.RESOURCE_COLUMNS:
        raise ValueError('resource Checkout detector and migration DDL differ')
    # A source change requires a deliberate SQL review and baseline update;
    # merely retaining a known table name must never bless a new layout.
    baseline = json.loads((Path(__file__).with_name('reviewed-sql-contracts.json')).read_text())
    actual = {name: reviewed_ddl_digest(path) for name, path in ddl_sources(server, hub)}
    drift = sorted(name for name in set(actual) | set(baseline) if actual.get(name) != baseline.get(name))
    if drift:
        raise ValueError('SQL review baseline changed: ' + ', '.join(drift))
    return {'reviewed_ddl_sources': len(actual), 'create_definitions': definitions, 'table_names': len(contracts),
            'isolated_layout_collisions': sorted(collisions),
            'checkout_reader_contracts': 'matched'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    workspace = Path(__file__).resolve().parents[2]
    parser.add_argument('--server', type=Path, default=workspace / 'cloudfile-server')
    parser.add_argument('--hub', type=Path, default=workspace / 'cloudfile-hub')
    args = parser.parse_args()
    try:
        print(json.dumps(audit(args.server, args.hub), ensure_ascii=False, sort_keys=True))
    except (OSError, ValueError, ImportError) as error:
        parser.exit(1, 'SQL contract check failed: ' + str(error) + '\n')


if __name__ == '__main__':
    main()
