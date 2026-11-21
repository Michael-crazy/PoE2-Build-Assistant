#!/usr/bin/env python3
"""Index gem identities and primary player-skill eligibility from pinned local blobs."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
GEMS = 'src/Data/Gems.lua'
DATA = 'src/Modules/Data.lua'
REVIEWED = (DATA, 'src/Classes/SkillsTab.lua', 'src/Modules/CalcTools.lua')
TERMS = ROOT / 'data/terms/poe2db-1.0'
TERM_FILES = ('skill_gems', 'spirit_gems', 'meta_skill_gem', 'support_gems', 'lineage_supports')


def mask_comments(text):
    """Remove Lua comments/long strings without moving source positions."""
    parts, start, i = [], 0, 0
    while i < len(text):
        if text[i] in ('"', "'"):
            quote = text[i]
            i += 1
            while i < len(text) and text[i] != quote:
                i += 2 if text[i] == "\\" else 1
            i += 1
            continue
        comment = text.startswith('--', i)
        opening = re.match(r'\[(=*)\[', text[i + 2:] if comment else text[i:]) if (comment or text[i] == '[') else None
        if comment or opening:
            parts.append(text[start:i])
            if opening:
                end = text.find(']' + opening[1] + ']', i + (2 if comment else 0) + opening.end())
                if end < 0:
                    raise ValueError('unterminated Lua long bracket')
                end += len(opening[1]) + 2
            else:
                end = text.find('\n', i)
                if end < 0:
                    end = len(text)
            parts.append(''.join('\n' if c == '\n' else ' ' for c in text[i:end]))
            i = start = end
        else:
            i += 1
    parts.append(text[start:])
    return ''.join(parts)


def fields(block, indent):
    """Only direct fields in the reviewed generated format; never nested flags."""
    result = {}
    for key, value in re.findall(r'^' + indent + r'(\w+) = ([^\n]*)$', block, re.M):
        if value.endswith(','):
            value = value[:-1]
        elif value != '{' and not value.startswith('function('):
            raise ValueError(f'unsupported direct field format: {key}')
        if key in result:
            raise ValueError(f'duplicate direct field: {key}')
        result[key] = value
    return result


def string(value):
    if not isinstance(value, str) or not re.fullmatch(r'"[^"\\\n]*"', value):
        raise ValueError(f'unsupported string: {value!r}')
    return value[1:-1]


def integer(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d+', value):
        raise ValueError(f'unsupported integer: {value!r}')
    return int(value)


def boolean(value):
    if value not in ('true', 'false'):
        raise ValueError(f'unsupported boolean: {value!r}')
    return value == 'true'


def parse_effects(text, path):
    text = mask_comments(text)
    # Generated declarations start at column 0; a few hand-written ones are
    # indented between them (e.g. TriggeredBarbsPlayer). Each ends at its own indent.
    starts = list(re.finditer(r'^(\t*)skills\["([^"\\]+)"\] = \{\n', text, re.M))
    if len(starts) != len(re.findall(r'^[ \t]*skills\[', text, re.M)):
        raise ValueError(f'unsupported skill declaration format: {path}')
    rows = []
    for start in starts:
        indent, skill_id = start[1], start[2]
        end = re.compile(r'^' + indent + r'\}\n?', re.M).search(text, start.end())
        if end is None:
            raise ValueError(f'unterminated skill declaration: {path}:{skill_id}')
        block = text[start.end():end.start()]
        direct = fields(block, indent + r'\t')
        levels = re.findall(r'^' + indent + r'\tlevels = \{\n(.*?)^' + indent + r'\t\},', block, re.M | re.S)
        if len(levels) != 1:
            raise ValueError(f'expected one direct levels table: {path}:{skill_id}')
        entries = re.findall(r'^' + indent + r'\t\t\[(\d+)\] = \{ ([^\n]*?),? \},?\n', levels[0], re.M)
        if not entries or len(entries) != levels[0].count('\n'):
            raise ValueError(f'unsupported levels format: {path}:{skill_id}')
        requirements = {}
        for key, value in entries:
            requirement = re.findall(r'(?:^|, )levelRequirement = (\d+)(?:,|$)', value)
            if len(requirement) != 1 or int(key) in requirements:
                raise ValueError('missing/duplicate level or levelRequirement')
            requirements[int(key)] = int(requirement[0])
        rows.append(dict(id=skill_id, name_en=string(direct.get('name')),
                         support=boolean(direct.get('support', 'false')),
                         hideFromSideBar=boolean(direct.get('hideFromSideBar', 'false')),
                         # Exact keys, not an inferred continuous range.
                         levels=sorted(requirements),
                         level_requirements=[requirements[k] for k in sorted(requirements)],
                         declarations=[dict(source_file=path,
                                            source_line=text.count('\n', 0, start.start()) + 1)]))
    return rows


def parse_gems(text):
    text = mask_comments(text)
    header = r'^\t\["([^"\\]+)"\] = \{\n'
    starts = list(re.finditer(header, text, re.M))
    if len(starts) != len(re.findall(r'^\t\[', text, re.M)) or not starts:
        raise ValueError('unsupported gem declaration format')
    rows = []
    for n, start in enumerate(starts):
        block = text[start.end():starts[n + 1].start() if n + 1 < len(starts) else len(text)]
        direct = fields(block, r'\t\t')
        row = dict(id=start[1], name_en=string(direct.get('name')),
                   gameId=string(direct.get('gameId')), variantId=string(direct.get('variantId')),
                   grantedEffectId=string(direct.get('grantedEffectId')),
                   naturalMaxLevel=integer(direct.get('naturalMaxLevel')),
                   declaration=dict(source_file=GEMS, source_line=text.count('\n', 0, start.start()) + 1))
        if any(not row[k] for k in ('id', 'gameId', 'variantId', 'grantedEffectId')):
            raise ValueError('empty gem identity')
        additions = sorted((int(k.removeprefix('additionalGrantedEffectId')), string(v))
                           for k, v in direct.items() if k.startswith('additionalGrantedEffectId'))
        if [k for k, _ in additions] != list(range(1, len(additions) + 1)):
            raise ValueError('noncontiguous additionalGrantedEffectId fields')
        row['additionalGrantedEffectIds'] = [v for _, v in additions]
        # additionalStatSetN is NOT an additional granted effect.
        row['additionalStatSets'] = {k: string(v) for k, v in direct.items()
                                    if k.startswith('additionalStatSet')}
        order = direct.get('grantedEffectDisplayOrder')
        if order is not None and not re.fullmatch(r'\{ \d+(?:, \d+)* \}', order):
            raise ValueError('unsupported grantedEffectDisplayOrder')
        row['grantedEffectDisplayOrder'] = [int(v) for v in re.findall(r'\d+', order)] if order else None
        rows.append(row)
    # Lua table constructors retain the LAST value for repeated literal keys.
    effective = {}
    for row in rows:
        old = effective.get(row['id'])
        row['declarations'] = (old['declarations'] if old else []) + [row.pop('declaration')]
        effective[row['id']] = row
    return list(effective.values())


def assemble(gems, effects):
    by_effect = {}
    for row in effects:
        old = by_effect.get(row['id'])
        if old is not None:
            if {k: v for k, v in old.items() if k != 'declarations'} != {k: v for k, v in row.items() if k != 'declarations'}:
                raise ValueError(f'conflicting effect declarations: {row["id"]}')
            old['declarations'].extend(row['declarations'])
        else:
            by_effect[row['id']] = row
    gem_ids, game_variants = set(), set()
    for gem in gems:
        pair = (gem['gameId'], gem['variantId'])
        if gem['id'] in gem_ids or pair in game_variants:
            raise ValueError('duplicate gem ID or gameId/variantId pair')
        gem_ids.add(gem['id'])
        game_variants.add(pair)
        effect = by_effect.get(gem['grantedEffectId'])
        if effect is None:
            raise ValueError(f'missing primary grantedEffectId: {gem["grantedEffectId"]}')
        if gem['naturalMaxLevel'] < 1:
            raise ValueError('naturalMaxLevel must be positive')
        gem['natural_max_level_in_effect_levels'] = gem['naturalMaxLevel'] in effect['levels']
        # Data.setupGem injects these three effects by gem name.
        injected = []
        if gem['name_en'].startswith('Barbs I'):
            injected = ['TriggeredBarbsPlayer' + {'Barbs II': 'Two', 'Barbs III': 'Three'}.get(gem['name_en'], '')]
        gem['runtimeAdditionalGrantedEffectIds'] = injected
        effect_ids = [gem['grantedEffectId'], *gem['additionalGrantedEffectIds'], *injected]
        # table.insert(list, nil) adds no entry; retain unresolved references for review.
        gem['unresolvedAdditionalGrantedEffectIds'] = [k for k in effect_ids if k not in by_effect]
        effect_ids = [k for k in effect_ids if k in by_effect]
        order = gem['grantedEffectDisplayOrder']
        if order is not None:
            ordered, used = [], set()
            for n, value in enumerate(order):
                index = value if value < len(effect_ids) and value not in used else n
                if index >= len(effect_ids):
                    raise ValueError('unsupported display order fallback')
                ordered.append(effect_ids[index])
                used.add(index)
            ordered.extend(k for n, k in enumerate(effect_ids) if n not in used)
            effect_ids = ordered
        gem['initializedGrantedEffectIds'] = effect_ids
        reasons = [key for key in ('support', 'hideFromSideBar') if effect[key]]
        gem['primary_player_skill_eligible'] = not reasons
        gem['ineligible_reasons'] = reasons
        effect.setdefault('primary_gem_ids', []).append(gem['id'])
    for row in by_effect.values():
        row['primary_gem_ids'] = sorted(row.get('primary_gem_ids', []))
        row['primary_player_skill_eligible'] = bool(row['primary_gem_ids']) and not row['support'] and not row['hideFromSideBar']
        row['ineligible_reasons'] = ([k for k in ('support', 'hideFromSideBar') if row[k]]
                                     + ([] if row['primary_gem_ids'] else ['no_primary_gem']))
    return sorted(gems, key=lambda r: r['id']), sorted(by_effect.values(), key=lambda r: r['id'])


def join_terms(gems, terms_dir):
    """Attach D01 Chinese names only where the full PoB identity triple matches."""
    by_pair = {(g['gameId'], g['variantId']): g for g in gems}
    files, unjoined = [], []
    for name in TERM_FILES:
        content = (terms_dir / f'{name}.json').read_bytes()
        data = json.loads(content)
        files.append(dict(path=f'{name}.json', version=data['metadata']['version'],
                          sha256=hashlib.sha256(content).hexdigest()))
        for slug, entry in sorted(data['gems'].items()):
            ref = entry.get('pob')
            gem = ref and by_pair.get((ref['gameId'], ref['variantId']))
            if not gem or gem['grantedEffectId'] != ref['grantedEffectId']:
                if ref:
                    unjoined.append(dict(file=f'{name}.json', slug=slug, pob=ref))
                continue
            names = dict(zh_hans=entry['zh_hans'], zh_hant=entry['zh_hant'])
            if gem.setdefault('names', names) != names:
                raise ValueError(f'conflicting term names for gem: {gem["id"]}')
            gem.setdefault('term_refs', []).append(dict(file=f'{name}.json', slug=slug))
    for gem in gems:
        gem.setdefault('names', None)
        gem.setdefault('term_refs', [])
    return dict(files=files, unjoined=unjoined)


def build_index(source, manifest, terms_dir=TERMS):
    def git(*args):
        return subprocess.check_output(['git', '-C', str(source), *args])

    commit = manifest['commit']
    if not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise ValueError('manifest requires a full commit SHA')
    if git('rev-parse', 'HEAD').decode().strip() != commit:
        raise ValueError('local HEAD does not match pinned commit')
    provenance = []

    def read(path):
        content = git('show', f'{commit}:{path}')
        provenance.append(dict(path=path, sha256=hashlib.sha256(content).hexdigest()))
        return content.decode('utf-8')

    data = mask_comments(read(DATA))
    types = re.findall(r'^local skillTypes = \{\n(.*?)^\}', data, re.M | re.S)
    if len(types) != 1 or not re.fullmatch(r'(?:\n|\t"[a-z_]+",\n)+', types[0]):
        raise ValueError('unsupported Data.skillTypes initialization')
    loaded = re.findall(r'"([a-z_]+)"', types[0])
    effects = []
    for name in loaded:
        path = f'src/Data/Skills/{name}.lua'
        effects.extend(parse_effects(read(path), path))
    gems = parse_gems(read(GEMS))
    for path in REVIEWED[1:]:
        read(path)
    declaration_count = len(effects)
    gems, effects = assemble(gems, effects)
    terms = join_terms(gems, terms_dir)
    pairs = Counter(g['gameId'] for g in gems)
    return dict(schema_version=1, source=dict(repository=manifest['repository'], branch=manifest['branch'],
                commit=commit, files=provenance), terms=terms, loaded_skill_modules=loaded,
                summary=dict(gem_count=len(gems), effect_count=len(effects),
                             effect_declaration_count=declaration_count,
                             natural_max_level_mismatch_count=sum(not g['natural_max_level_in_effect_levels'] for g in gems),
                             gem_declaration_count=sum(len(g['declarations']) for g in gems),
                             unresolved_additional_effect_gem_count=sum(bool(g['unresolvedAdditionalGrantedEffectIds']) for g in gems),
                             eligible_primary_gem_count=sum(g['primary_player_skill_eligible'] for g in gems),
                             named_gem_count=sum(g['names'] is not None for g in gems),
                             named_eligible_primary_gem_count=sum(
                                 g['names'] is not None and g['primary_player_skill_eligible'] for g in gems),
                             multiple_variant_game_id_count=sum(n > 1 for n in pairs.values())),
                gems=gems, skills=effects)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    try:
        index = build_index(args.source, json.loads((ROOT / 'sources/pob.json').read_text()))
        args.output.write_text(json.dumps(index, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        parser.exit(1, f'Gem index failed: {error}\n')
    print(json.dumps(index['summary'], sort_keys=True))


if __name__ == '__main__':
    main()
