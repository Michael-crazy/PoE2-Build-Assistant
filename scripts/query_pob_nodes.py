#!/usr/bin/env python3
"""Query passive node IDs offline within an explicit pinned tree version."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def _declaration(record):
    declaration = record.get('declaration')
    if (not isinstance(declaration, dict)
            or not isinstance(declaration.get('source_file'), str) or not declaration['source_file']
            or type(declaration.get('source_line')) is not int or declaration['source_line'] < 1):
        raise ValueError('node index: invalid declaration')


class NodeLookup:
    def __init__(self, index, expected_source=None):
        if not isinstance(index, dict) or type(index.get('schema_version')) is not int or index['schema_version'] != 1:
            raise ValueError('node index: expected schema_version 1')
        source = index.get('source')
        if (not isinstance(source, dict)
                or any(not isinstance(source.get(k), str) or not source[k]
                       for k in ('repository', 'branch', 'commit'))
                or not re.fullmatch(r'[0-9a-f]{40}', source['commit'])):
            raise ValueError('node index: missing versioned source')
        if expected_source is not None and {k: source.get(k) for k in expected_source} != expected_source:
            raise ValueError('node index source does not match pinned manifest')
        self.source = deepcopy(source)
        versions = index.get('tree_versions')
        if not isinstance(versions, list) or not versions:
            raise ValueError('node index: expected tree_versions list')
        self.versions, self.by_id = {}, {}
        for version in versions:
            if (not isinstance(version, dict)
                    or any(not isinstance(version.get(k), str) or not version[k]
                           for k in ('tree_version', 'display'))):
                raise ValueError('node index: invalid tree version')
            _declaration(version)
            key = version['tree_version']
            if key in self.versions:
                raise ValueError('node index: duplicate tree_version')
            nodes = version.get('nodes')
            if not isinstance(nodes, list):
                raise ValueError('node index: expected nodes list')
            identities, source_keys = {}, set()
            for node in nodes:
                if (not isinstance(node, dict)
                        or any(type(node.get(k)) is not int or node[k] < 0 for k in ('id', 'source_key'))
                        or not isinstance(node.get('name_en'), str)
                        or 'string_id' not in node
                        or (node['string_id'] is not None and not isinstance(node['string_id'], str))):
                    raise ValueError('node index: invalid node record')
                _declaration(node)
                if node['id'] in identities or node['source_key'] in source_keys:
                    raise ValueError('node index: duplicate node ID/source_key')
                identities[node['id']] = deepcopy(node)
                source_keys.add(node['source_key'])
            self.versions[key] = deepcopy({k: v for k, v in version.items() if k != 'nodes'})
            self.by_id[key] = identities

    def query(self, tree_version, node_id):
        if not isinstance(tree_version, str) or tree_version not in self.versions:
            raise ValueError(f'unknown tree version: {tree_version!r}')
        if type(node_id) is not int or node_id < 0:
            raise ValueError('node ID must be a nonnegative integer')
        node = self.by_id[tree_version].get(node_id)
        return deepcopy(dict(schema_version=1, source=self.source,
                             tree_version=self.versions[tree_version],
                             query=dict(tree_version=tree_version, by='id', value=node_id),
                             status='not_found' if node is None else 'single_candidate',
                             candidate_count=0 if node is None else 1,
                             candidates=[] if node is None else [node]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--index', type=Path, default=ROOT / 'sources/pob-nodes.en.json')
    parser.add_argument('--tree-version', required=True)
    parser.add_argument('node_id', type=int)
    args = parser.parse_args()
    try:
        index = json.loads(args.index.read_text(encoding='utf-8'))
        manifest = json.loads((ROOT / 'sources/pob.json').read_text(encoding='utf-8'))
        result = NodeLookup(index, manifest).query(args.tree_version, args.node_id)
    except (OSError, ValueError) as error:
        parser.exit(1, f'Node query failed: {error}\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
