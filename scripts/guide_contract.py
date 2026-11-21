#!/usr/bin/env python3
"""Validate an authored guide extraction; does not extract prose or generate PoB."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from query_pob_skills import ROOT, SkillLookup
from query_pob_classes import ClassLookup
from query_pob_nodes import NodeLookup


TEXT_FIELDS = ('realm', 'league', 'game_version', 'stage', 'class_name',
               'ascendancy_name', 'main_skill_name', 'main_skill_id',
               'tree_version', 'equipment_text', 'config_text')
INT_FIELDS = ('level', 'main_skill_level', 'main_skill_quality')
FIELDS = TEXT_FIELDS + INT_FIELDS + ('passive_nodes',)


def keys(value, expected, path):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise ValueError(f'{path}: expected keys {", ".join(expected)}')


def text(value, path):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{path}: expected non-empty text')


def snapshot_sha256(value):
    """Bind JSON values including types, independent of object key order."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def main_skill_candidates(fields, lookup):
    results = {}
    for by, field in (('name', 'main_skill_name'), ('id', 'main_skill_id')):
        fact = fields[field]
        results[by] = (None if fact['origin'] == 'missing'
                       else lookup.query(by, fact['value']))
    name, skill_id = results['name'], results['id']
    consistency = 'not_comparable'
    if name and skill_id and name['candidates'] and skill_id['candidates']:
        name_ids = {row['id'] for row in name['candidates']}
        consistency = ('overlap' if skill_id['candidates'][0]['id'] in name_ids
                       else 'conflict')
    return dict(confirmation='pending', name_id_consistency=consistency, **results)


def class_ascendancy_candidates(fields, lookup):
    version = fields['tree_version']['value']
    result = dict(confirmation='pending', source=deepcopy(lookup.source),
                  tree_version=version, status='ready',
                  class_ascendancy_consistency='not_comparable',
                  class_name=None, ascendancy_name=None)
    if fields['tree_version']['origin'] == 'missing':
        result['status'] = 'missing_tree_version'
        return result
    if version not in lookup.versions:
        result['status'] = 'unknown_tree_version'
        return result
    for kind, field in (('class', 'class_name'), ('ascendancy', 'ascendancy_name')):
        fact = fields[field]
        if fact['origin'] != 'missing':
            result[field] = lookup.query(version, kind, 'name', fact['value'])
    classes, ascendancies = result['class_name'], result['ascendancy_name']
    if classes and ascendancies and classes['candidates'] and ascendancies['candidates']:
        owners = {row['class_identity']['integer_id'] for row in classes['candidates']}
        asc_owners = {row['class_identity']['integer_id'] for row in ascendancies['candidates']}
        result['class_ascendancy_consistency'] = 'overlap' if owners & asc_owners else 'conflict'
    return result


def passive_node_candidates(fields, lookup):
    version = fields['tree_version']['value']
    result = dict(confirmation='pending', source=deepcopy(lookup.source),
                  tree_version=version, status='ready', nodes=None)
    if fields['tree_version']['origin'] == 'missing':
        result['status'] = 'missing_tree_version'
    elif version not in lookup.versions:
        result['status'] = 'unknown_tree_version'
    elif fields['passive_nodes']['origin'] == 'missing':
        result['status'] = 'missing_passive_nodes'
    else:
        result['nodes'] = [lookup.query(version, node_id)
                           for node_id in fields['passive_nodes']['value']]
    return result


def validate_guide(data, *, skill_lookup=None, class_lookup=None, node_lookup=None):
    keys(data, ('schema_version', 'source', 'fields'), 'guide')
    if type(data['schema_version']) is not int or data['schema_version'] != 1:
        raise ValueError('schema_version: expected 1')
    source = data['source']
    keys(source, ('id', 'kind', 'title', 'text'), 'source')
    for name, value in source.items():
        text(value, f'source.{name}')
    if source['kind'] not in ('authored_prose', 'authored_structured'):
        raise ValueError('source.kind: expected authored_prose or authored_structured')
    keys(data['fields'], FIELDS, 'fields')
    missing, inferred = [], []
    for name, fact in data['fields'].items():
        path = f'fields.{name}'
        keys(fact, ('value', 'origin', 'evidence', 'reason'), path)
        value, origin = fact['value'], fact['origin']
        if origin == 'missing':
            if value is not None or fact['evidence'] is not None:
                raise ValueError(f'{path}: missing requires null value and evidence')
            text(fact['reason'], path + '.reason')
            missing.append(name)
            continue
        if origin not in ('stated', 'inferred'):
            raise ValueError(f'{path}.origin: expected stated, inferred or missing')
        text(fact['evidence'], path + '.evidence')
        if fact['evidence'] not in source['text']:
            raise ValueError(f'{path}.evidence: not found verbatim in source.text')
        if origin == 'inferred':
            text(fact['reason'], path + '.reason')
            inferred.append(name)
        elif fact['reason'] is not None:
            raise ValueError(f'{path}.reason: stated requires null')
        if name in TEXT_FIELDS:
            text(value, path + '.value')
        elif name in INT_FIELDS:
            if type(value) is not int or value < (0 if name == 'main_skill_quality' else 1):
                raise ValueError(f'{path}.value: invalid integer')
            if name == 'level' and value > 100:
                raise ValueError(f'{path}.value: level exceeds 100')
        elif (not isinstance(value, list)
              or any(type(node) is not int or node < 0 for node in value)
              or len(set(value)) != len(value)):
            raise ValueError(f'{path}.value: expected unique non-negative integer node IDs')
        if name == 'realm' and value not in ('international', 'tencent'):
            raise ValueError(f'{path}.value: expected international or tencent')
    if skill_lookup is None:
        index = json.loads((ROOT / 'sources/pob-skills.en.json').read_text(encoding='utf-8'))
        manifest = json.loads((ROOT / 'sources/pob.json').read_text(encoding='utf-8'))
        skill_lookup = SkillLookup(index, manifest)
    if class_lookup is None:
        index = json.loads((ROOT / 'sources/pob-classes.en.json').read_text(encoding='utf-8'))
        manifest = json.loads((ROOT / 'sources/pob.json').read_text(encoding='utf-8'))
        class_lookup = ClassLookup(index, manifest)
    if node_lookup is None:
        index = json.loads((ROOT / 'sources/pob-nodes.en.json').read_text(encoding='utf-8'))
        manifest = json.loads((ROOT / 'sources/pob.json').read_text(encoding='utf-8'))
        node_lookup = NodeLookup(index, manifest)
    result = {'guide': deepcopy(data),
            'passive_node_candidates': passive_node_candidates(data['fields'], node_lookup),
            'main_skill_candidates': main_skill_candidates(data['fields'], skill_lookup),
            'class_ascendancy_candidates': class_ascendancy_candidates(data['fields'], class_lookup),
            'missing_fields': sorted(missing),
            'inferred_fields': sorted(inferred), 'pob_generation': 'pending',
            'mcp_acceptance': 'pending'}
    result['confirmation_context'] = dict(
        sources=deepcopy(dict(skills=skill_lookup.source, classes=class_lookup.source,
                              nodes=node_lookup.source)),
        tree_version=data['fields']['tree_version']['value'],
        snapshot_sha256=snapshot_sha256(result))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--confirmation', type=Path, help='候选确认 JSON 文件；省略时仅查询')
    args = parser.parse_args()
    try:
        guide = json.loads(args.input.read_text(encoding='utf-8'))
        if args.confirmation is None:
            result = validate_guide(guide)
        else:
            from guide_confirmation import validate_confirmation
            confirmation = json.loads(args.confirmation.read_text(encoding='utf-8'))
            result = validate_confirmation(guide, confirmation)
    except (OSError, ValueError) as error:
        parser.exit(1, f'{error}\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
