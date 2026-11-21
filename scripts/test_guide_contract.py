"""Authored input transport checks; no PoB or MCP acceptance claims."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from guide_contract import validate_guide

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'tests/fixtures/a01'


class GuideContractTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads((FIXTURES / 'prose.json').read_text())

    def test_examples_keep_source_missing_and_inferences(self):
        for filename in ('prose.json', 'structured.json'):
            data = json.loads((FIXTURES / filename).read_text())
            before = deepcopy(data)
            result = validate_guide(data)
            self.assertEqual(result['guide'], before)
            self.assertIn('main_skill_id', result['missing_fields'])
            self.assertIn('tree_version', result['missing_fields'])
            self.assertEqual(result['pob_generation'], 'pending')
            self.assertEqual(result['mcp_acceptance'], 'pending')
            self.assertEqual(result['inferred_fields'], ['equipment_text'] if filename == 'prose.json' else [])
            result['guide']['source']['text'] = 'changed'
            self.assertEqual(data, before)

    def test_reject_lost_fields_and_unknown_version(self):
        for change in (lambda d: d['fields'].pop('league'),
                       lambda d: d['fields'].update(typo={}),
                       lambda d: d.update(schema_version=True),
                       lambda d: d.update(schema_version=2),
                       lambda d: d['source'].update(kind='live_guide')):
            data = deepcopy(self.data)
            change(data)
            with self.assertRaises(ValueError):
                validate_guide(data)

    def test_reject_untraceable_or_unmarked_values(self):
        for field, patch in (
            ('class_name', {'evidence': 'not in source'}),
            ('class_name', {'reason': 'hidden inference'}),
            ('equipment_text', {'reason': None}),
            ('league', {'value': 'invented'}),
            ('league', {'evidence': '战士'}),
            ('league', {'reason': ''}),
            ('level', {'origin': 'unknown'}),
            ('level', {'value': True}),
            ('level', {'value': 101}),
            ('level', {'value': 0}),
            ('class_name', {'value': None}),
        ):
            data = deepcopy(self.data)
            data['fields'][field].update(patch)
            with self.subTest(field=field, patch=patch), self.assertRaises(ValueError):
                validate_guide(data)

    def test_typed_values_and_empty_node_allocation(self):
        for name, values in {'passive_nodes': ([1, 1], [True], [-1], '1,2'),
                             'main_skill_quality': (-1, True),
                             'realm': ('other',)}.items():
            for value in values:
                data = deepcopy(self.data)
                data['fields'][name] = dict(value=value, origin='stated', evidence='战士', reason=None)
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    validate_guide(data)
        self.data['fields']['passive_nodes'] = dict(value=[], origin='stated', evidence='战士', reason=None)
        self.assertNotIn('passive_nodes', validate_guide(self.data)['missing_fields'])

    def test_cli_valid_and_bad_inputs(self):
        entry = ROOT / 'scripts/guide_contract.py'
        def run(path):
            return subprocess.run([sys.executable, '-B', str(entry), str(path)],
                                  capture_output=True, text=True, timeout=5)
        result = run(FIXTURES / 'structured.json')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['guide']['fields']['main_skill_quality']['value'], 0)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'bad.json'
            for content in ('{', '[]', '{"schema_version":1}'):
                path.write_text(content)
                result = run(path)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, '')
                self.assertNotIn('Traceback', result.stderr)
            result = run(path.with_name('missing.json'))
            self.assertEqual(result.returncode, 1)


if __name__ == '__main__':
    unittest.main()
