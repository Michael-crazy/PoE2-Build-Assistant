#!/usr/bin/env python3
"""Query pinned offline class/ascendancy candidates for an explicit tree version."""

import argparse
from copy import deepcopy
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
FIELDS = {'class': ('name', 'integer_id', 'source_index'),
          'ascendancy': ('name', 'id', 'internal_id', 'ascendancy_index')}
NUMERIC = ('integer_id', 'source_index', 'ascendancy_index')


def _record(row, text_fields, number_fields):
    if (not isinstance(row, dict)
            or any(not isinstance(row.get(k), str) or not row[k].strip() for k in text_fields)
            or any(type(row.get(k)) is not int or row[k] < 0 for k in number_fields)):
        raise ValueError('class index: invalid identity record')
    declaration = row.get('declaration')
    if (not isinstance(declaration, dict)
            or not isinstance(declaration.get('source_file'), str) or not declaration['source_file']
            or type(declaration.get('source_line')) is not int or declaration['source_line'] < 1):
        raise ValueError('class index: invalid declaration')


def _unique(rows, fields):
    for field in fields:
        values = [row[field] for row in rows]
        if len(set(values)) != len(values):
            raise ValueError(f'class index: duplicate {field}')


class ClassLookup:
    def __init__(self, index, expected_source=None):
        if not isinstance(index, dict) or type(index.get('schema_version')) is not int or index['schema_version'] != 1:
            raise ValueError('class index: expected schema_version 1')
        source = index.get('source')
        if (not isinstance(source, dict)
                or any(not isinstance(source.get(k), str) or not source[k]
                       for k in ('repository', 'branch', 'commit'))
                or not re.fullmatch(r'[0-9a-f]{40}', source['commit'])):
            raise ValueError('class index: missing versioned source')
        self.source = deepcopy(source)
        if expected_source is not None and {k: source[k] for k in expected_source} != expected_source:
            raise ValueError('class index source does not match pinned manifest')
        versions = index.get('tree_versions')
        if not isinstance(versions, list) or not versions:
            raise ValueError('class index: expected tree_versions list')
        self.versions = {}
        for version in versions:
            _record(version, ('tree_version', 'display'), ())
            key = version['tree_version']
            if key in self.versions:
                raise ValueError('class index: duplicate tree_version')
            classes = version.get('classes')
            if not isinstance(classes, list):
                raise ValueError('class index: expected classes list')
            for row in classes:
                _record(row, ('name_en',), ('integer_id', 'source_index'))
                ascendancies = row.get('ascendancies')
                if not isinstance(ascendancies, list):
                    raise ValueError('class index: expected ascendancies list')
                for asc in ascendancies:
                    _record(asc, ('name_en', 'id', 'internal_id'), ('ascendancy_index',))
                _unique(ascendancies, ('ascendancy_index', 'id', 'internal_id'))
            _unique(classes, ('integer_id', 'source_index'))
            self.versions[key] = deepcopy(version)

    def query(self, tree_version, kind, by, value, class_integer_id=None):
        if not isinstance(tree_version, str) or tree_version not in self.versions:
            raise ValueError(f'unknown tree version: {tree_version!r}')
        if kind not in FIELDS or by not in FIELDS[kind]:
            raise ValueError('query requires an explicit class/ascendancy identity namespace')
        if ((by in NUMERIC and (type(value) is not int or value < 0))
                or (by not in NUMERIC and not isinstance(value, str))):
            raise ValueError('query value must match the identity namespace type')
        if class_integer_id is not None and (kind != 'ascendancy'
                or type(class_integer_id) is not int or class_integer_id < 0):
            raise ValueError('class_integer_id requires an ascendancy query and an integer ID')
        version = self.versions[tree_version]
        field = 'name_en' if by == 'name' else by
        candidates = []
        for row in version['classes']:
            owner = {k: v for k, v in row.items() if k != 'ascendancies'}
            if kind == 'class':
                if row[field] == value:
                    candidates.append(dict(class_identity=owner))
            elif class_integer_id is None or row['integer_id'] == class_integer_id:
                for asc in row['ascendancies']:
                    if asc[field] == value:
                        candidates.append(dict(class_identity=owner, ascendancy=asc))
        status = ('empty_query' if isinstance(value, str) and not value.strip() else
                  'not_found' if not candidates else
                  'single_candidate' if len(candidates) == 1 else 'ambiguous')
        return deepcopy(dict(schema_version=1, source=self.source,
                             tree_version={k: v for k, v in version.items() if k != 'classes'},
                             query=dict(tree_version=tree_version, kind=kind, by=by, value=value,
                                        class_integer_id=class_integer_id),
                             status=status, candidate_count=len(candidates), candidates=candidates))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--index', type=Path, default=ROOT / 'sources/pob-classes.en.json')
    parser.add_argument('--tree-version', required=True)
    parser.add_argument('--kind', choices=tuple(FIELDS), required=True)
    parser.add_argument('--by', choices=tuple(dict.fromkeys(f for fs in FIELDS.values() for f in fs)), required=True)
    parser.add_argument('--class-integer-id', type=int)
    parser.add_argument('value')
    args = parser.parse_args()
    try:
        index = json.loads(args.index.read_text(encoding='utf-8'))
        manifest = json.loads((ROOT / 'sources/pob.json').read_text(encoding='utf-8'))
        value = int(args.value) if args.by in NUMERIC else args.value
        result = ClassLookup(index, manifest).query(args.tree_version, args.kind, args.by, value,
                                                   args.class_integer_id)
    except (OSError, ValueError) as error:
        parser.exit(1, f'Class query failed: {error}\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
