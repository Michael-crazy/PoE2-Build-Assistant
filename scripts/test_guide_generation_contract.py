"""Authored offline pre-generation cases; no XML, Lua execution or network."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from guide_contract import validate_guide
from guide_generation_contract import validate_generation_inputs, REQUIRED_FACTS, GROUP_FIELDS
from query_pob_skills import SkillLookup
from query_pob_classes import ClassLookup
from query_pob_nodes import NodeLookup
from test_query_pob_classes import fixture as class_fixture
from test_query_pob_nodes import fixture as node_fixture
from test_guide_node_candidates import guide as node_guide

ROOT = Path(__file__).resolve().parents[1]


class GenerationInputTests(unittest.TestCase):
    def setUp(self):
        skills = json.loads((ROOT / 'tests/fixtures/a01/skill-query-index.json').read_text())
        skills['source'] = class_fixture()['source']
        self.lookups = dict(skill_lookup=SkillLookup(skills),
                            class_lookup=ClassLookup(class_fixture()),
                            node_lookup=NodeLookup(node_fixture()))
        self.guide = node_guide(nodes=())
        for key, value in dict(realm='international', league='AUTHORED-TEST',
                game_version='authored-version', stage='authored-stage', level=20,
                main_skill_name='Shared Name', main_skill_level=1,
                main_skill_quality=0).items():
            evidence = f'{key}={value}'
            self.guide['source']['text'] += '\n' + evidence
            self.guide['fields'][key] = dict(value=value, origin='stated',
                                            evidence=evidence, reason=None)
        self.group = dict(enabled=True, set1=True, set2=False, gem_enabled=True,
                          main_active_skill=1, main_active_skill_calcs=1)
        self.refresh()

    def refresh(self):
        self.confirmation = dict(schema_version=1,
            context=validate_guide(self.guide, **self.lookups)['confirmation_context'],
            selection=dict(main_skill_id='Two', class_integer_id=7,
                           ascendancy=dict(class_integer_id=7, id='Alpha'), passive_node_ids=[]))

    def check(self):
        return validate_generation_inputs(self.guide, self.confirmation, self.group, **self.lookups)

    def test_complete_maps_distinct_id_namespaces_without_generation(self):
        before = deepcopy((self.guide, self.confirmation, self.group))
        result = self.check()
        check = result['generation_input_check']
        self.assertEqual(check['status'], 'inputs_complete')
        self.assertEqual(check['missing_inputs'], [])
        mapping = check['mapping']
        self.assertEqual(mapping['Spec.classInternalId'], 7)  # source_index is 1
        self.assertEqual(mapping['Spec.ascendancyInternalId'], 'Fixture3')  # id is Alpha
        self.assertEqual(mapping['Gem.skillId'], 'Two')
        self.assertEqual(mapping['Gem.quality'], 0)
        self.assertEqual(mapping['Spec.nodes'], [])
        self.assertNotIn('Gem.gemId', mapping)
        self.assertNotIn('Build.targetVersion', mapping)
        self.assertEqual(result['pob_generation'], 'pending')
        self.assertEqual(result['mcp_acceptance'], 'pending')
        self.assertIn('fixed_engine_load_and_save', check['pending_checks'])
        baseline = validate_guide(self.guide, **self.lookups)
        self.assertEqual({k: v for k, v in result.items()
                          if k not in ('generation_input_check', 'candidate_selection')}, baseline)
        check['mapping']['Spec.nodes'].append(7)
        check['group']['set1'] = False
        self.assertEqual((self.guide, self.confirmation, self.group), before)

    def test_every_required_fact_and_group_value_stays_missing(self):
        for key in REQUIRED_FACTS:
            if key == 'tree_version':
                continue  # confirmation rejects unknown tree before preflight
            original = deepcopy(self.guide)
            self.guide['fields'][key] = dict(value=None, origin='missing',
                                             evidence=None, reason='Authored omission')
            self.refresh()
            self.assertIn(f'fields.{key}', self.check()['generation_input_check']['missing_inputs'])
            self.guide = original
        self.refresh()
        for key in GROUP_FIELDS:
            value = self.group[key]
            self.group[key] = None
            self.assertIn(f'group.{key}', self.check()['generation_input_check']['missing_inputs'])
            self.group[key] = value

    def test_partial_confirmation_is_not_complete_and_empty_nodes_are_explicit(self):
        for key in self.confirmation['selection']:
            saved = deepcopy(self.confirmation)
            self.confirmation['selection'][key] = None
            if key == 'class_integer_id':
                self.confirmation['selection']['ascendancy'] = None
            check = self.check()['generation_input_check']
            self.assertEqual(check['status'], 'missing_inputs')
            self.assertIn(f'selection.{key}', check['missing_inputs'])
            self.confirmation = saved

    def test_reject_rewritten_disabled_or_non_single_group_options(self):
        for key, value in [('enabled', False), ('gem_enabled', False), ('set1', 1),
                           ('main_active_skill', True), ('main_active_skill', 2),
                           ('main_active_skill_calcs', '1')]:
            original = deepcopy(self.group)
            self.group[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                self.check()
            self.group = original
        self.group['set1'] = False
        with self.assertRaisesRegex(ValueError, 'both weapon sets'):
            self.check()
        self.group['set1'] = True
        self.group['gemId'] = 'untrusted'
        with self.assertRaisesRegex(ValueError, 'expected keys'):
            self.check()

    def test_stale_and_outside_candidate_selections_are_revalidated(self):
        self.guide['source']['text'] += '\nChanged authored note'
        with self.assertRaisesRegex(ValueError, 'stale or mismatched'):
            self.check()
        self.refresh()
        self.confirmation['selection']['main_skill_id'] = 'Hidden'
        with self.assertRaisesRegex(ValueError, 'original candidates'):
            self.check()

    def test_local_pinned_indexes_map_authored_warrior_titan(self):
        self.guide = json.loads((ROOT / 'tests/fixtures/a01/confirmation-guide.json').read_text())
        result = validate_guide(self.guide)
        confirmation = dict(schema_version=1, context=result['confirmation_context'],
            selection=dict(main_skill_id='FireballPlayer', class_integer_id=6,
                           ascendancy=dict(class_integer_id=6, id='Titan'), passive_node_ids=[4]))
        output = validate_generation_inputs(self.guide, confirmation, self.group)
        mapping = output['generation_input_check']['mapping']
        self.assertEqual(mapping['Spec.classInternalId'], 6)
        self.assertEqual(mapping['Spec.ascendancyInternalId'], 'Warrior1')
        self.assertEqual(mapping['Spec.nodes'], [4])
        self.assertEqual(output['guide']['fields']['passive_nodes']['value'], [4, 999999])
        self.assertEqual(output['guide']['fields']['main_skill_id']['origin'], 'inferred')
        self.assertEqual(output['generation_input_check']['status'], 'missing_inputs')


if __name__ == '__main__':
    unittest.main()
