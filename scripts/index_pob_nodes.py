#!/usr/bin/env python3
"""Extract version-specific passive node identities from pinned local Git blobs."""
import argparse
import json
from pathlib import Path
import re
import subprocess

from index_pob_classes import ROOT, build_tree_index, table_at


def parse_nodes(text, path):
    # Match the generated top-level table, never group nodes or nested identities.
    matches = list(re.finditer(r'^\tnodes=\{', text, re.M))
    if len(matches) != 1:
        raise ValueError(f'expected one top-level nodes table: {path}')
    table = table_at(text, matches[0].end() - 1, path, escaped_strings=True)
    rows, ids = [], set()
    for key, node in table['fields'].items():
        values = node['fields']
        identity = values.get('skill')
        if type(key) is not int or key < 0 or type(identity) is not int or identity < 0:
            raise ValueError(f'node key and skill must be nonnegative integers: {path}')
        if identity in ids:
            raise ValueError(f'duplicate node ID in {path}: {identity}')
        ids.add(identity)
        if not isinstance(values.get('name'), str) or ('stringId' in values and not isinstance(values['stringId'], str)):
            raise ValueError(f'missing node name/stringId: {path}: {identity}')
        rows.append(dict(id=identity, source_key=key, name_en=values['name'],
                         string_id=values.get('stringId'), declaration=node['declaration']))
    if not rows:
        raise ValueError(f'empty nodes table: {path}')
    return sorted(rows, key=lambda row: row['id'])


def build_index(source, manifest):
    return build_tree_index(source, manifest, 'nodes', parse_nodes)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    try:
        index = build_index(args.source, json.loads((ROOT / 'sources/pob.json').read_text()))
        args.output.write_text(json.dumps(index, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        parser.exit(1, f'Node index failed: {error}\n')
    print(json.dumps({v['tree_version']: len(v['nodes']) for v in index['tree_versions']}))


if __name__ == '__main__':
    main()
