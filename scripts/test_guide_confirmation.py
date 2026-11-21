"""Authored offline confirmation cases; no client, network or BD generation."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from guide_contract import validate_guide, snapshot_sha256
from guide_confirmation import validate_confirmation
from query_pob_skills import SkillLookup
from query_pob_classes import ClassLookup
from query_pob_nodes import NodeLookup
from test_query_pob_classes import fixture as class_fixture
from test_query_pob_nodes import fixture as node_fixture
from test_guide_node_candidates import guide as node_guide

ROOT = Path(__file__).resolve().parents[1]


class GuideConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.skills = json.loads((ROOT / 'tests/fixtures/a01/skill-query-index.json').read_text())
        self.skills['source'] = class_fixture()['source']
        self.classes, self.nodes = class_fixture(), node_fixture()
        self.data = node_guide(nodes=(7, 8, 9))
        for name, value in [('main_skill_name', 'Shared Name'), ('main_skill_id', 'Unique')]:
            evidence = f'{name}={value}'
            self.data['source']['text'] += '\n' + evidence
            self.data['fields'][name] = dict(value=value, origin='inferred', evidence=evidence,
                                           reason='Authored uncertain extraction.')
        self.refresh()
        self.confirmation = dict(schema_version=1,
            context=deepcopy(self.result['confirmation_context']),
            selection=dict(main_skill_id='Two', class_integer_id=7,
                           ascendancy=dict(class_integer_id=7, id='Alpha'), passive_node_ids=[8, 7]))

    def refresh(self):
        self.lookups = dict(skill_lookup=SkillLookup(self.skills), class_lookup=ClassLookup(self.classes),
                            node_lookup=NodeLookup(self.nodes))
        self.result = validate_guide(self.data, **self.lookups)

    def confirm(self, confirmation=None):
        return validate_confirmation(self.data, self.confirmation if confirmation is None else confirmation,
                                     **self.lookups)

    def test_explicit_choices_preserve_conflicts_inferences_source_and_pending(self):
        before = deepcopy((self.data, self.confirmation, self.skills, self.classes, self.nodes))
        output = self.confirm()
        self.assertEqual(output['candidate_selection'], dict(status='validated', input=self.confirmation))
        self.assertEqual({k: v for k, v in output.items() if k != 'candidate_selection'}, self.result)
        self.assertEqual(output['main_skill_candidates']['name_id_consistency'], 'conflict')
        self.assertEqual(output['inferred_fields'], ['main_skill_id', 'main_skill_name'])
        self.assertEqual(output['guide'], self.data)
        self.assertEqual(output['pob_generation'], 'pending')
        self.assertEqual(output['mcp_acceptance'], 'pending')
        self.assertEqual(output['passive_node_candidates']['confirmation'], 'pending')
        output['candidate_selection']['input']['selection']['passive_node_ids'].clear()
        output['guide']['source']['text'] = 'changed'
        self.assertEqual((self.data, self.confirmation, self.skills, self.classes, self.nodes), before)
        self.assertEqual(self.confirm()['candidate_selection']['input'], self.confirmation)

    def test_partial_union_choices_and_explicit_empty_nodes(self):
        for selection in [dict(main_skill_id='Unique'), dict(main_skill_id='One'),
                          dict(class_integer_id=2, ascendancy=dict(class_integer_id=2, id='Beta')),
                          dict(passive_node_ids=[]), dict(passive_node_ids=[7])]:
            confirmation = deepcopy(self.confirmation)
            confirmation['selection'] = dict.fromkeys(confirmation['selection'])
            confirmation['selection'].update(selection)
            self.assertEqual(self.confirm(confirmation)['candidate_selection']['input'], confirmation)
        # Empty known allocation differs from missing. Both remain unchanged in guide.
        self.data = node_guide(nodes=())
        self.refresh()
        confirmation = dict(schema_version=1, context=self.result['confirmation_context'],
                            selection=dict(main_skill_id=None, class_integer_id=None,
                                           ascendancy=None, passive_node_ids=[]))
        self.assertEqual(self.confirm(confirmation)['guide']['fields']['passive_nodes']['value'], [])
        self.data = node_guide(nodes=None)
        self.refresh()
        confirmation['context'] = self.result['confirmation_context']
        with self.assertRaisesRegex(ValueError, 'no original node candidates'):
            self.confirm(confirmation)

    def test_reject_ids_outside_original_queries_even_if_present_in_index(self):
        cases = [('main_skill_id', 'Hidden'), ('main_skill_id', 'Shared Name'),
                 ('class_integer_id', 1), ('class_integer_id', 9),
                 ('ascendancy', dict(class_integer_id=7, id='Shared')),
                 ('ascendancy', dict(class_integer_id=7, id='Fixture3')),
                 ('ascendancy', dict(class_integer_id=2, id='Beta')),
                 ('passive_node_ids', [9]), ('passive_node_ids', [70]),
                 ('passive_node_ids', [999])]
        for key, value in cases:
            confirmation = deepcopy(self.confirmation)
            confirmation['selection'][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                self.confirm(confirmation)
        confirmation = deepcopy(self.confirmation)
        confirmation['selection']['class_integer_id'] = None
        with self.assertRaisesRegex(ValueError, 'matching selected class'):
            self.confirm(confirmation)

    def test_reject_stale_context_and_changed_guide_even_with_same_ids(self):
        for mutate in [lambda c: c.update(tree_version='new'),
                       lambda c: c.update(snapshot_sha256='0' * 64),
                       lambda c: c['sources']['skills'].update(commit='2' * 40),
                       lambda c: c['sources']['nodes']['files'][0].update(sha256='4' * 64),
                       lambda c: c.update(extra=True)]:
            confirmation = deepcopy(self.confirmation)
            mutate(confirmation['context'])
            with self.assertRaisesRegex(ValueError, 'stale or mismatched'):
                self.confirm(confirmation)
        for mutate in [lambda d: d['source'].update(text=d['source']['text'] + '\nnew note'),
                       lambda d: d['source'].update(id='other-guide'),
                       lambda d: d['fields']['main_skill_name'].update(reason='Revised inference.'),
                       lambda d: d['fields']['tree_version'].update(value='new', evidence='tree_version=')]:
            original = deepcopy(self.data)
            mutate(self.data)
            with self.assertRaisesRegex(ValueError, 'stale or mismatched'):
                self.confirm()
            self.data = original

    def test_reject_changed_candidate_provenance_and_mixed_sources(self):
        self.skills['skills'][0]['declarations'][0]['source_line'] += 1
        self.refresh()
        with self.assertRaisesRegex(ValueError, 'stale or mismatched'):
            self.confirm()
        self.skills['source']['commit'] = '2' * 40
        self.refresh()
        self.confirmation['context'] = self.result['confirmation_context']
        with self.assertRaisesRegex(ValueError, 'same repository, branch and SHA'):
            self.confirm()

    def test_missing_unknown_tree_is_not_confirmable(self):
        for version in (None, 'unknown', 'latest', 'default'):
            self.data = node_guide(version)
            self.refresh()
            confirmation = deepcopy(self.confirmation)
            confirmation['context'] = self.result['confirmation_context']
            with self.subTest(version=version), self.assertRaisesRegex(ValueError, 'indexed tree_version'):
                self.confirm(confirmation)

    def test_strict_confirmation_shape_and_id_types(self):
        mutations = [lambda c: c.update(schema_version=True), lambda c: c.update(schema_version=2),
                     lambda c: c.update(extra=1), lambda c: c.pop('context'),
                     lambda c: c.update(selection=None),
                     lambda c: c.update(selection=dict.fromkeys(c['selection'])),
                     lambda c: c['selection'].pop('ascendancy'),
                     lambda c: c['selection'].update(class_integer_id=True),
                     lambda c: c['selection'].update(class_integer_id='7'),
                     lambda c: c['selection'].update(main_skill_id=7),
                     lambda c: c['selection'].update(ascendancy=dict(class_integer_id=True, id='Alpha')),
                     lambda c: c['selection'].update(ascendancy=dict(class_integer_id=7, internal_id='Alpha'))]
        mutations += [lambda c, v=v: c['selection'].update(passive_node_ids=v)
                      for v in ([True], [7.0], ['7'], [-1], [7, 7], '7')]
        for mutate in mutations:
            confirmation = deepcopy(self.confirmation)
            mutate(confirmation)
            with self.subTest(confirmation=confirmation), self.assertRaises(ValueError):
                self.confirm(confirmation)

    def test_context_is_deterministic_and_binds_complete_original_output(self):
        output = deepcopy(self.result)
        context = output.pop('confirmation_context')
        self.assertEqual(context['snapshot_sha256'], snapshot_sha256(output))
        self.assertEqual(context['tree_version'], 'old')
        self.assertEqual(context['sources']['nodes'], self.nodes['source'])
        self.assertEqual(validate_guide(self.data, **self.lookups), self.result)
        self.assertEqual(snapshot_sha256(dict(a=1, b=2)), snapshot_sha256(dict(b=2, a=1)))
        self.assertNotEqual(snapshot_sha256(1), snapshot_sha256(True))

    def test_pinned_local_indexes_with_explicit_authored_choices(self):
        data = json.loads((ROOT / 'tests/fixtures/a01/class-overlap.json').read_text())
        for name, value in [('main_skill_id', 'FireballPlayer'), ('passive_nodes', [4])]:
            evidence = f'{name}={value}'
            data['source']['text'] += '\n' + evidence
            data['fields'][name] = dict(value=value, origin='stated', evidence=evidence, reason=None)
        result = validate_guide(data)
        confirmation = dict(schema_version=1, context=result['confirmation_context'],
                            selection=dict(main_skill_id='FireballPlayer', class_integer_id=6,
                                           ascendancy=dict(class_integer_id=6, id='Titan'),
                                           passive_node_ids=[4]))
        output = validate_confirmation(data, confirmation)
        self.assertEqual(output['candidate_selection']['input'], confirmation)
        self.assertEqual(output['guide'], data)
        self.assertEqual(output['pob_generation'], 'pending')


if __name__ == '__main__':
    unittest.main()
