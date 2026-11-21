#!/usr/bin/env python3
"""Extract class/ascendancy and tree versions from pinned local Git blobs."""
import argparse
from bisect import bisect_right
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
VERSIONS = 'src/GameVersions.lua'


def declaration(path, text, offset):
    return dict(source_file=path, source_line=text.count('\n', 0, offset) + 1)


def table_at(text, offset, path, *, escaped_strings=False):
    # Restricted data-table grammar, never executes Lua. Locations use original offsets.
    token = re.compile(r'\s+|--[^\n]*|"[^"\\\n]*"|[A-Za-z_][A-Za-z_0-9]*|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|[{}\[\]=,]')
    if escaped_strings:
        token = re.compile(r'\s+|--[^\n]*|"(?:[^"\\\n]|\\[n"\\])*"|[A-Za-z_][A-Za-z_0-9]*|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|[{}\[\]=,]')
    line_starts = [0] + [m.end() for m in re.finditer("\n", text)]
    pos = offset

    def take():
        nonlocal pos
        while True:
            if pos == len(text):
                return '<EOF>', pos
            m = token.match(text, pos)
            if not m:
                raise ValueError(f'unsupported table format: {path}:{text.count(chr(10), 0, pos)+1}')
            pos = m.end()
            if not m[0].isspace() and not m[0].startswith('--'):
                return m[0], m.start()

    current = take()

    def advance(expected=None):
        nonlocal current
        old = current
        if expected is not None and old[0] != expected:
            raise ValueError(f'expected {expected} in {path}, got {old[0]}')
        current = take()
        return old

    def scalar(raw):
        if raw.startswith('"'):
            return json.loads(raw) if escaped_strings else raw[1:-1]
        if raw in ('true', 'false'):
            return raw == 'true'
        if re.fullmatch(r'-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?', raw):
            return float(raw) if any(c in raw for c in '.eE') else int(raw)
        raise ValueError(f'unsupported scalar in {path}: {raw}')

    def parse():
        start = advance('{')[1]
        fields = {}
        while current[0] != '}':
            if current[0] == '[':
                advance('[')
                key = scalar(advance()[0])
                advance(']')
            else:
                key = advance()[0]
                if not re.fullmatch(r'[A-Za-z_]\w*', key):
                    raise ValueError(f'unsupported key in {path}')
            advance('=')
            value = parse() if current[0] == '{' else scalar(advance()[0])
            if key in fields:
                raise ValueError(f'duplicate key in {path}: {key}')
            fields[key] = value
            if current[0] == ',':
                advance(',')
            elif current[0] != '}':
                raise ValueError(f'missing comma in {path}')
        advance('}')
        return dict(fields=fields, declaration=dict(source_file=path, source_line=bisect_right(line_starts, start)))

    return parse()


def parse_versions(text):
    match = re.search(r'^treeVersionList = \{([^}\n]+)\}$', text, re.M)
    if not match or not re.fullmatch(r'\s*"\w+"(?:\s*,\s*"\w+")*\s*', match[1]):
        raise ValueError('unsupported treeVersionList')
    versions = re.findall(r'"(\w+)"', match[1])
    if len(set(versions)) != len(versions):
        raise ValueError('duplicate tree version')
    for key, expr in [('latestTreeVersion', '#treeVersionList'), ('defaultTreeVersion', '1')]:
        if not re.search(r'^' + key + r' = treeVersionList\[' + re.escape(expr) + r'\]$', text, re.M):
            raise ValueError(f'unsupported {key}')
    m = re.search(r'^treeVersions = (\{)', text, re.M)
    if not m:
        raise ValueError('missing treeVersions')
    definitions = table_at(text, m.start(1), VERSIONS)['fields']
    if set(definitions) != set(versions):
        raise ValueError('tree version list/definitions mismatch')
    rows = []
    for version in versions:
        node = definitions[version]
        fields = node['fields']
        if set(fields) != {'display', 'num'} or not isinstance(fields['display'], str) or type(fields['num']) not in (int, float):
            raise ValueError('unsupported tree version metadata')
        rows.append(dict(tree_version=version, display=fields['display'], num=fields['num'],
                         declaration=node['declaration']))
    return rows


def parse_classes(text, path):
    matches = list(re.finditer(r'^\tclasses=(\{)', text, re.M))
    if len(matches) != 1:
        raise ValueError(f'expected one root classes table: {path}')
    nodes = table_at(text, matches[0].start(1), path)['fields']
    rows, ids = [], set()
    for index, node in nodes.items():
        fields = node['fields']
        if type(index) is not int or type(fields.get('integerId')) is not int or not isinstance(fields.get('name'), str):
            raise ValueError(f'invalid class identity: {path}')
        identity = fields['integerId']
        if identity in ids:
            raise ValueError(f'duplicate class integerId: {path}')
        ids.add(identity)
        ascendancies = []
        for asc_index, asc in fields['ascendancies']['fields'].items():
            values = asc['fields']
            if type(asc_index) is not int or any(not isinstance(values.get(k), str) or not values[k] for k in ('id', 'internalId', 'name')):
                raise ValueError(f'invalid ascendancy identity: {path}')
            ascendancies.append(dict(ascendancy_index=asc_index, id=values['id'], internal_id=values['internalId'],
                                     name_en=values['name'], declaration=asc['declaration']))
        rows.append(dict(source_index=index, integer_id=identity, name_en=fields['name'],
                         declaration=node['declaration'], ascendancies=ascendancies))
    if not rows:
        raise ValueError(f'empty classes: {path}')
    return rows


def build_tree_index(source, manifest, field, parse_tree):
    def git(*args):
        return subprocess.check_output(['git', '-C', str(source), *args])
    commit = manifest['commit']
    if not re.fullmatch('[0-9a-f]{40}', commit):
        raise ValueError('manifest requires full commit SHA')
    if git('rev-parse', 'HEAD').decode().strip() != commit:
        raise ValueError('local HEAD does not match pinned commit')
    files = []
    def read(path):
        blob = git('show', f'{commit}:{path}')
        files.append(dict(path=path, sha256=hashlib.sha256(blob).hexdigest()))
        return blob.decode('utf-8')
    versions = parse_versions(read(VERSIONS))
    for row in versions:
        path = f"src/TreeData/{row['tree_version']}/tree.lua"
        row[field] = parse_tree(read(path), path)
    return dict(schema_version=1, source=dict(repository=manifest['repository'], branch=manifest['branch'],
                commit=commit, files=files), default_tree_version=versions[0]['tree_version'],
                latest_tree_version=versions[-1]['tree_version'], tree_versions=versions)


def build_index(source, manifest):
    return build_tree_index(source, manifest, 'classes', parse_classes)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    try:
        index = build_index(args.source, json.loads((ROOT / 'sources/pob.json').read_text()))
        args.output.write_text(json.dumps(index, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        parser.exit(1, f'Class index failed: {error}\n')
    print(json.dumps({r['tree_version']: len(r['classes']) for r in index['tree_versions']}))


if __name__ == '__main__':
    main()
