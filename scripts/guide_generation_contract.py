"""Offline pre-generation input checks and identity mapping; never emit a BD."""
from copy import deepcopy

from guide_contract import keys
from guide_confirmation import validate_confirmation


# Context is required explicitly, even where it has no PoB XML equivalent.
REQUIRED_FACTS = ('realm', 'league', 'game_version', 'stage', 'level',
                  'tree_version', 'main_skill_level', 'main_skill_quality')
GROUP_FIELDS = ('enabled', 'set1', 'set2', 'gem_enabled',
                'main_active_skill', 'main_active_skill_calcs')
PENDING_CHECKS = (
    'target_version_mapping', 'gem_identity_and_active_skill_eligibility',
    'gem_level_quality_and_effect_selection', 'passive_allocation_legality',
    'equipment_and_config_semantics', 'fixed_engine_load_and_save',
)


def validate_generation_inputs(guide, confirmation, group, **lookups):
    """Check one ordinary group with one skill, using fresh explicit choices.

    Null group values are missing, not engine defaults. Complete inputs only
    satisfy this limited contract; PENDING_CHECKS still prevent generation.
    No caller-provided validation result or mapping is trusted.
    """
    result = validate_confirmation(guide, confirmation, **lookups)
    keys(group, GROUP_FIELDS, 'group')
    missing = [f'fields.{k}' for k in REQUIRED_FACTS
               if guide['fields'][k]['origin'] == 'missing']
    for key in GROUP_FIELDS:
        value = group[key]
        if value is None:
            missing.append(f'group.{key}')
        elif key in ('main_active_skill', 'main_active_skill_calcs'):
            # A single gem can produce several effects. This narrow contract
            # only requests the first; effect eligibility remains pending.
            if type(value) is not int or value != 1:
                raise ValueError(f'group.{key}: single-group contract requires integer 1')
        elif type(value) is not bool:
            raise ValueError(f'group.{key}: expected boolean or null')
    for key in ('enabled', 'gem_enabled'):
        if group[key] is False:
            raise ValueError(f'group.{key}: main skill must be enabled')
    if group['set1'] is False and group['set2'] is False:
        raise ValueError('group: both weapon sets disabled would be rewritten by PoB')

    selection = result['candidate_selection']['input']['selection']
    for key, value in selection.items():
        if value is None:
            missing.append(f'selection.{key}')
    classes = result['class_ascendancy_candidates']
    owner = selection['class_integer_id']
    asc = selection['ascendancy']
    class_row = next((r['class_identity'] for r in
                      (classes['class_name'] or {}).get('candidates', [])
                      if r['class_identity']['integer_id'] == owner), None)
    asc_row = next((r['ascendancy'] for r in
                    (classes['ascendancy_name'] or {}).get('candidates', [])
                    if asc is not None and r['class_identity']['integer_id'] == owner
                    and r['ascendancy']['id'] == asc['id']), None)
    fields = guide['fields']
    # Typed destination names describe a mapping, not serialized XML.
    mapping = {
        'Build.level': fields['level']['value'],
        'Build.className': class_row['name_en'] if class_row else None,
        'Build.ascendClassName': asc_row['name_en'] if asc_row else None,
        'Build.mainSocketGroup': 1,
        'Skills.activeSkillSet': 1,
        'SkillSet.id': 1,
        'Skill.enabled': group['enabled'],
        'Skill.set1': group['set1'], 'Skill.set2': group['set2'],
        'Skill.mainActiveSkill': group['main_active_skill'],
        'Skill.mainActiveSkillCalcs': group['main_active_skill_calcs'],
        'Gem.skillId': selection['main_skill_id'],
        'Gem.level': fields['main_skill_level']['value'],
        'Gem.quality': fields['main_skill_quality']['value'],
        'Gem.enabled': group['gem_enabled'],
        'Spec.treeVersion': fields['tree_version']['value'],
        'Spec.classInternalId': owner,
        'Spec.ascendancyInternalId': asc_row['internal_id'] if asc_row else None,
        'Spec.nodes': deepcopy(selection['passive_node_ids']),
    }
    result['generation_input_check'] = dict(
        schema_version=1, status='missing_inputs' if missing else 'inputs_complete',
        missing_inputs=sorted(missing), group=deepcopy(group), mapping=mapping,
        pending_checks=list(PENDING_CHECKS))
    return result
