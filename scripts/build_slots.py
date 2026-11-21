"""Build inventory for estimates: static XML extraction or the pinned engine.

The static path is stored equipment extraction and refuses conditional slots;
engine_build uses the engine-effective inventory instead.
"""
import hashlib
from pathlib import Path
import xml.etree.ElementTree as ET

from pob_inventory import inventory as engine_inventory

BASE = ('Weapon 1', 'Weapon 2', 'Helmet', 'Body Armour', 'Gloves', 'Boots',
        'Amulet', 'Ring 1', 'Ring 2', 'Belt', 'Charm 1', 'Charm 2', 'Charm 3',
        'Flask 1', 'Flask 2')
SPECIAL = ('Ring 3', 'Arm 1', 'Arm 2', 'Leg 1', 'Leg 2')
# Worn and priceable. Inactive PoB flask/charm effects are still worn items.
PRICED = ('equipped', 'empty', 'stored_consumable')


def unique(nodes, attribute, label):
    result = {}
    for node in nodes:
        key = node.get(attribute)
        if not key or key in result:
            raise ValueError(f'{label}: missing or duplicate {attribute}')
        result[key] = node
    return result


def parse_root(data):
    try:
        root = ET.fromstring(data)
    except ET.ParseError as error:
        raise ValueError(f'build XML: {error}') from error
    if root.tag != 'PathOfBuilding2':
        raise ValueError('build XML: expected PathOfBuilding2')
    return root


def build_item(definitions, name, item_id):
    if item_id not in definitions:
        raise ValueError(f'{name}: unknown itemId {item_id}')
    raw = (definitions[item_id].text or '').strip()
    if not raw:
        raise ValueError(f'{name}: empty item text')
    return {'id': item_id, 'raw_text': raw}


def engine_build(path, worker, timeout=120):
    """Effective slots from the pinned engine, with raw item text from the XML."""
    result = engine_inventory(path, worker, timeout)
    items = parse_root(Path(path).read_bytes()).find('Items')
    if items is None:
        raise ValueError('build XML: Items required')
    definitions = unique(items.findall('Item'), 'id', 'Item')
    rows = []
    for row in result['inventory']:
        item = None
        if row['state'] in ('equipped', 'stored_consumable'):
            item = build_item(definitions, row['slot'], row['selected_item_id'])
        rows.append({**row, 'build_item': item})
    return {'source': 'engine', 'sha256': result['sha256'], 'engine_commit': result['engine_commit'],
            'item_set_id': result['item_set_id'], 'weapon_set': result['weapon_set'],
            'inventory': rows, 'passive_spec': result.get('passive_spec')}


def extract_build(path):
    data = Path(path).read_bytes()
    root = parse_root(data)
    items, build, skills = root.find('Items'), root.find('Build'), root.find('Skills')
    if items is None or build is None or skills is None:
        raise ValueError('build XML: Items, Build and Skills required')
    sets = unique(items.findall('ItemSet'), 'id', 'ItemSet')
    set_id = items.get('activeItemSet', '1')
    if set_id not in sets:
        raise ValueError('activeItemSet: unknown item set')
    active = sets[set_id]
    skill_sets = unique(skills.findall('SkillSet'), 'id', 'SkillSet')
    skill_set = skill_sets.get(skills.get('activeSkillSet', '1'))
    if skill_set is None:
        raise ValueError('activeSkillSet: unknown skill set')
    groups = skill_set.findall('Skill')
    try:
        main = int(build.get('mainSocketGroup', '1'))
    except ValueError as error:
        raise ValueError('mainSocketGroup: expected integer') from error
    if not 1 <= main <= len(groups):
        raise ValueError('mainSocketGroup: outside stored skill groups; engine required')
    group = groups[main - 1]
    # SkillsTab:GetSocketGroupWeaponSet, pinned engine 601768bd.
    first, second = group.get('set1') != 'false', group.get('set2') != 'false'
    weapon_set = (2 if active.get('useSecondWeaponSet') == 'true' else 1) if first and second else (2 if second else 1)
    definitions = unique(items.findall('Item'), 'id', 'Item')
    stored = unique(active.findall('Slot'), 'name', 'Slot')
    expected = set(BASE + SPECIAL + ('Weapon 1 Swap', 'Weapon 2 Swap'))
    for name, node in stored.items():
        if name not in expected and node.get('itemId', '0') != '0':
            raise ValueError(f'{name}: equipped dynamic slot requires engine inventory')
    for name in SPECIAL:
        if name in stored and stored[name].get('itemId', '0') != '0':
            raise ValueError(f'{name}: conditional slot requires engine inventory')
    for rune in active.findall('RuneSlot'):
        if rune.get('runeName', 'None') != 'None':
            raise ValueError('equipped runes require engine inventory')
    inventory = []
    for name in BASE + ('Weapon 1 Swap', 'Weapon 2 Swap'):
        node = stored.get(name)
        item_id = node.get('itemId', '0') if node is not None else '0'
        if not item_id.isdecimal():
            raise ValueError(f'{name}: invalid itemId')
        item = build_item(definitions, name, item_id) if item_id != '0' else None
        inactive = name.startswith('Weapon ') and (name.endswith(' Swap') != (weapon_set == 2))
        inventory.append({'slot': name, 'state': 'inactive_weapon_set' if inactive else ('equipped' if item else 'empty'),
                          'build_item': item})
    return {'source': 'xml', 'sha256': hashlib.sha256(data).hexdigest(), 'item_set_id': set_id,
            'weapon_set': weapon_set, 'inventory': inventory}


def selections_for_build(build):
    return [{'slot': row['slot'], 'listing_id': None, 'matched_affixes': []}
            for row in build['inventory'] if row['state'] in PRICED]


def bind_selections(build, selections):
    if not isinstance(selections, list):
        raise ValueError('selections: expected array')
    expected = {r['slot']: r for r in build['inventory'] if r['state'] in PRICED}
    seen = set()
    for row in selections:
        if not isinstance(row, dict) or row.get('slot') not in expected or row['slot'] in seen:
            raise ValueError('selections: unknown, inactive or duplicate slot')
        seen.add(row['slot'])
        if expected[row['slot']]['state'] == 'empty' and (row.get('listing_id') is not None or row.get('matched_affixes')):
            raise ValueError(f"{row['slot']}: empty build slot cannot select a listing")
    if seen != set(expected):
        raise ValueError('selections: must explicitly cover every active build slot')
    return expected
