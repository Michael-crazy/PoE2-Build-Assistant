"""Authored offline guide fixtures; candidates are never confirmations or builds."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from guide_contract import FIELDS, validate_guide
from query_pob_classes import ClassLookup
from test_query_pob_classes import fixture

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'tests/fixtures/a01'


def authored_guide(version='old', class_name='Shared Class', ascendancy='Shared'):
    values = dict(tree_version=version, class_name=class_name, ascendancy_name=ascendancy)
    fields = {name: dict(value=None, origin='missing', evidence=None,
                         reason='Not provided in this authored fixture.') for name in FIELDS}
    lines = ['Authored offline guide; not a client or live guide sample.']
    for name, value in values.items():
        if value is not None:
            evidence = f'{name}={value}'
            lines.append(evidence)
            fields[name] = dict(value=value, origin='stated', evidence=evidence, reason=None)
    return dict(schema_version=1, source=dict(id='authored:class-guide', kind='authored_structured',
                title='Authored class guide', text='\n'.join(lines)), fields=fields)


class GuideClassCandidateTests(unittest.TestCase):
    def setUp(self):
        index = fixture()
        for version in index['tree_versions']:
            other = deepcopy(version['classes'][0])
            other.update(name_en='Other Class', integer_id=42, source_index=42)
            other['ascendancies'] = [dict(other['ascendancies'][0], name_en='Other Ascendancy')]
            version['classes'].append(other)
        self.lookup = ClassLookup(index)

    def validate(self, guide):
        return validate_guide(guide, class_lookup=self.lookup)

    def test_ambiguity_and_ownership_overlap_do_not_select_or_filter(self):
        result = self.validate(authored_guide())['class_ascendancy_candidates']
        self.assertEqual(result['status'], 'ready')
        self.assertEqual(result['class_ascendancy_consistency'], 'overlap')
        self.assertEqual(result['class_name']['status'], 'ambiguous')
        self.assertEqual(result['ascendancy_name']['status'], 'ambiguous')
        self.assertEqual([r['class_identity']['integer_id'] for r in result['class_name']['candidates']], [7, 2])
        self.assertEqual([r['ascendancy']['id'] for r in result['ascendancy_name']['candidates']], ['Alpha', 'Beta'])
        partial = self.validate(authored_guide(ascendancy='Alpha'))['class_ascendancy_candidates']
        self.assertEqual(partial['class_name']['candidate_count'], 2)
        self.assertEqual(partial['ascendancy_name']['candidate_count'], 1)
        self.assertEqual(partial['class_ascendancy_consistency'], 'overlap')
        self.assertNotIn('selected', result)

    def test_conflict_keeps_both_independent_queries(self):
        result = self.validate(authored_guide(ascendancy='Other Ascendancy'))['class_ascendancy_candidates']
        self.assertEqual(result['class_ascendancy_consistency'], 'conflict')
        self.assertEqual(result['class_name']['candidate_count'], 2)
        self.assertEqual(result['ascendancy_name']['candidates'][0]['class_identity']['integer_id'], 42)
        self.assertIsNone(result['ascendancy_name']['query']['class_integer_id'])

    def test_missing_unknown_tree_versions_do_not_query_or_guess(self):
        for version, status in [(None, 'missing_tree_version'), ('unknown', 'unknown_tree_version'),
                                ('latest', 'unknown_tree_version'), ('default', 'unknown_tree_version')]:
            data = authored_guide(version)
            with self.subTest(version=version), patch.object(self.lookup, 'query', side_effect=AssertionError('queried')):
                result = self.validate(data)
                candidates = result['class_ascendancy_candidates']
                self.assertEqual(candidates['status'], status)
                self.assertEqual(candidates['tree_version'], version)
                self.assertIsNone(candidates['class_name'])
                self.assertIsNone(candidates['ascendancy_name'])
                self.assertEqual(candidates['class_ascendancy_consistency'], 'not_comparable')
                self.assertEqual('tree_version' in result['missing_fields'], version is None)
                self.assertEqual(result['guide'], data)

    def test_versions_are_isolated_and_names_are_exact(self):
        for version, count in [('old', 2), ('new', 1)]:
            result = self.validate(authored_guide(version))['class_ascendancy_candidates']
            self.assertEqual(result['ascendancy_name']['candidate_count'], count)
            self.assertEqual(result['class_name']['query']['tree_version'], version)
            self.assertEqual(result['ascendancy_name']['tree_version']['tree_version'], version)
        for name in ('shared class', ' Shared Class ', '7', '中文职业'):
            result = self.validate(authored_guide(class_name=name))['class_ascendancy_candidates']
            self.assertEqual(result['class_name']['status'], 'not_found')
            self.assertEqual(result['class_ascendancy_consistency'], 'not_comparable')

    def test_missing_and_unknown_names_keep_pending_and_original_fields(self):
        for class_name, asc in [(None, 'Shared'), ('Shared Class', None), (None, None),
                                ('Unknown', 'Unknown'), ('Other Class', 'Other Ascendancy')]:
            data = authored_guide(class_name=class_name, ascendancy=asc)
            before = deepcopy(data)
            result = self.validate(data)
            candidates = result['class_ascendancy_candidates']
            self.assertEqual(result['guide'], before)
            self.assertEqual(data, before)
            self.assertEqual(candidates['confirmation'], 'pending')
            self.assertEqual(result['pob_generation'], 'pending')
            self.assertEqual(result['mcp_acceptance'], 'pending')
            for field, value in [('class_name', class_name), ('ascendancy_name', asc)]:
                self.assertEqual(field in result['missing_fields'], value is None)
                if value is None:
                    self.assertIsNone(candidates[field])
                else:
                    self.assertEqual(candidates[field]['query']['value'], value)
            if class_name == 'Other Class':
                self.assertEqual(candidates['class_name']['status'], 'single_candidate')
                self.assertEqual(candidates['class_ascendancy_consistency'], 'overlap')

    def test_inference_and_provenance_survive_and_copies_are_independent(self):
        data = authored_guide()
        for field in ('tree_version', 'class_name', 'ascendancy_name'):
            data['fields'][field].update(origin='inferred', reason='Authored uncertain extraction.')
        result = self.validate(data)
        self.assertEqual(result['guide'], data)
        self.assertEqual(result['inferred_fields'], ['ascendancy_name', 'class_name', 'tree_version'])
        candidates = result['class_ascendancy_candidates']
        self.assertEqual(candidates['source'], self.lookup.source)
        self.assertEqual(candidates['ascendancy_name']['candidates'][0]['ascendancy']['declaration']['source_line'], 11)
        candidates['source']['commit'] = 'mutated'
        candidates['class_name']['candidates'].clear()
        result['guide']['fields']['class_name']['value'] = 'mutated'
        again = self.validate(data)['class_ascendancy_candidates']
        self.assertEqual(again['class_name']['candidate_count'], 2)
        self.assertEqual(again['source'], fixture()['source'])
        self.assertEqual(again['confirmation'], 'pending')

    def test_pinned_authored_guide_cli(self):
        for name, consistency in [('class-overlap', 'overlap'), ('class-conflict', 'conflict'),
                                   ('class-unknown-tree', 'not_comparable')]:
            path = FIXTURES / (name + '.json')
            result = subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/guide_contract.py'), str(path)],
                                    capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(path.read_text())
            output = json.loads(result.stdout)
            self.assertEqual(output, validate_guide(data))
            self.assertEqual(output['guide'], data)
            self.assertEqual(output['class_ascendancy_candidates']['class_ascendancy_consistency'], consistency)

    def test_class_index_failures_are_errors_even_with_missing_tree(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'sources').mkdir()
            for filename in ('pob-skills.en.json', 'pob.json'):
                (root / 'sources' / filename).write_text((ROOT / 'sources' / filename).read_text())
            with patch('guide_contract.ROOT', root):
                with self.assertRaises(OSError):
                    validate_guide(authored_guide(None))
                path = root / 'sources/pob-classes.en.json'
                for content, error in [('{', 'Expecting'), ('{}', 'schema_version'),
                                        (json.dumps(fixture()), 'pinned manifest')]:
                    path.write_text(content)
                    with self.subTest(content=content), self.assertRaisesRegex(ValueError, error):
                        validate_guide(authored_guide())


if __name__ == '__main__':
    unittest.main()
