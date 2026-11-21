#!/usr/bin/env python3
"""Query versioned offline English skill candidates; never select a skill."""

import argparse
from copy import deepcopy
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


class SkillLookup:
    def __init__(self, index, expected_source=None):
        if not isinstance(index, dict) or type(index.get('schema_version')) is not int or index['schema_version'] != 1:
            raise ValueError('skill index: expected schema_version 1')
        source = index.get('source')
        if (not isinstance(source, dict)
                or any(not isinstance(source.get(k), str) or not source[k]
                       for k in ('repository', 'branch', 'commit'))
                or not re.fullmatch(r'[0-9a-f]{40}', source['commit'])):
            raise ValueError('skill index: missing versioned source')
        self.source = {k: source[k] for k in ('repository', 'branch', 'commit')}
        if expected_source is not None and self.source != expected_source:
            raise ValueError('skill index source does not match pinned manifest')
        if not isinstance(index.get('skills'), list):
            raise ValueError('skill index: expected skills list')
        self.by_id, self.by_name = {}, {}
        for row in index['skills']:
            if (not isinstance(row, dict)
                    or not isinstance(row.get('id'), str) or not row['id'].strip()
                    or not isinstance(row.get('name_en'), str)
                    or not isinstance(row.get('declarations'), list) or not row['declarations']):
                raise ValueError('skill index: invalid skill record')
            if row['id'] in self.by_id:
                raise ValueError(f"skill index: duplicate ID {row['id']}")
            for declaration in row['declarations']:
                if (not isinstance(declaration, dict)
                        or not isinstance(declaration.get('source_file'), str) or not declaration['source_file']
                        or type(declaration.get('source_line')) is not int or declaration['source_line'] < 1):
                    raise ValueError('skill index: invalid declaration')
            candidate = deepcopy(row)
            self.by_id[row['id']] = candidate
            if row['name_en'].strip():
                self.by_name.setdefault(row['name_en'], []).append(candidate)

    def query(self, by, value):
        if by not in ('name', 'id') or not isinstance(value, str):
            raise ValueError('query requires name or id and a text value')
        candidates = []
        if value.strip():
            if by == 'name':
                candidates = self.by_name.get(value, [])
            elif value in self.by_id:
                candidates = [self.by_id[value]]
        status = ('empty_query' if not value.strip() else
                  'not_found' if not candidates else
                  'single_candidate' if len(candidates) == 1 else 'ambiguous')
        return dict(schema_version=1, source=deepcopy(self.source),
                    query=dict(by=by, value=value), status=status,
                    candidate_count=len(candidates),
                    candidates=deepcopy(sorted(candidates, key=lambda row: row['id'])))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--index', type=Path, default=ROOT / 'sources/pob-skills.en.json')
    parser.add_argument('--by', choices=('name', 'id'), required=True)
    parser.add_argument('value')
    args = parser.parse_args()
    try:
        index = json.loads(args.index.read_text(encoding='utf-8'))
        manifest = json.loads((ROOT / 'sources/pob.json').read_text(encoding='utf-8'))
        result = SkillLookup(index, manifest).query(args.by, args.value)
    except (OSError, ValueError) as error:
        parser.exit(1, f'Skill query failed: {error}\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
