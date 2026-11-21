#!/usr/bin/env python3
"""Build a versioned skill ID/name index from local pinned Git objects only."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SKILLS = 'src/Data/Skills/'
# This is the generated format at the pinned revision, not a Lua interpreter.
HEADER = re.compile(r'^skills\[', re.MULTILINE)
RECORD = re.compile(
    r'^skills\["([^"\\]+)"\] = \{\n[ \t]*name = "([^"\\\n]*)",[ \t]*$',
    re.MULTILINE,
)


def parse_skills(text, source_file):
    matches = list(RECORD.finditer(text))
    if [m.start() for m in matches] != [m.start() for m in HEADER.finditer(text)]:
        raise ValueError(f'unsupported skill declaration/name format: {source_file}')
    return [dict(id=m[1], name_en=m[2], source_file=source_file,
                 source_line=text.count('\n', 0, m.start()) + 1) for m in matches]


def build_index(source, manifest):
    def git(*args):
        return subprocess.check_output(['git', '-C', str(source), *args])

    commit = manifest['commit']
    if not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise ValueError('manifest requires a full commit SHA')
    if git('rev-parse', 'HEAD').decode().strip() != commit:
        raise ValueError('local HEAD does not match pinned commit')
    files = sorted(p for p in git('ls-tree', '-r', '--name-only', commit, '--', SKILLS)
                   .decode().splitlines() if p.endswith('.lua'))
    if not files:
        raise ValueError('no local skill Lua files at pinned commit')
    records, provenance = [], []
    for path in files:
        # Read committed blobs: local edits/untracked files cannot alter the index.
        content = git('show', f'{commit}:{path}')
        entries = parse_skills(content.decode('utf-8'), path)
        provenance.append(dict(path=path, sha256=hashlib.sha256(content).hexdigest(),
                               record_count=len(entries)))
        records.extend(entries)
    by_id = {}
    for row in records:
        entry = by_id.setdefault(row['id'], dict(id=row['id'], name_en=row['name_en'],
                                                declarations=[]))
        if entry['name_en'] != row['name_en']:
            raise ValueError(f"conflicting names for skill ID: {row['id']}")
        entry['declarations'].append(dict(source_file=row['source_file'],
                                          source_line=row['source_line']))
    declaration_count = len(records)
    records = list(by_id.values())
    if not records:
        raise ValueError('no skill declarations found')
    names = Counter(row['name_en'] for row in records if row['name_en'])
    return dict(schema_version=1, source=dict(repository=manifest['repository'],
                branch=manifest['branch'], commit=commit, files=provenance),
                summary=dict(record_count=len(records), declaration_count=declaration_count,
                             unnamed_count=sum(not row['name_en'] for row in records),
                             ambiguous_name_count=sum(n > 1 for n in names.values())),
                skills=sorted(records, key=lambda row: row['id']))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path, help='existing pinned local fork checkout')
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    try:
        index = build_index(args.source, json.loads((ROOT / 'sources/pob.json').read_text()))
        args.output.write_text(json.dumps(index, ensure_ascii=False, indent=2) + '\n',
                               encoding='utf-8')
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        parser.exit(1, f'Skill index failed: {error}\n')
    print(json.dumps(index['summary'], sort_keys=True))


if __name__ == '__main__':
    main()
