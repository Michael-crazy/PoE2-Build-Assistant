"""Authored two-version guides; offline ID candidates never generate builds."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from guide_contract import validate_guide
from query_pob_nodes import NodeLookup
from test_query_pob_nodes import fixture
from test_guide_class_candidates import authored_guide

ROOT = Path(__file__).resolve().parents[1]


def guide(version='old', nodes=(7, 8, 9)):
    data = authored_guide(version)
    if nodes is not None:
        evidence = f'passive_nodes={list(nodes)}'
        data['source']['text'] += '\n' + evidence
        data['fields']['passive_nodes'] = dict(value=list(nodes), origin='stated',
                                              evidence=evidence, reason=None)
    return data


class GuideNodeCandidateTests(unittest.TestCase):
    def setUp(self):
        self.index = fixture()
        self.lookup = NodeLookup(self.index)

    def validate(self, data):
        return validate_guide(data, node_lookup=self.lookup)

    def test_versions_ids_and_order(self):
        for version, statuses, name in [('old', ['single_candidate', 'single_candidate', 'not_found'], 'Shared Name'),
                                         ('new', ['single_candidate', 'not_found', 'single_candidate'], 'Changed Name')]:
            output = self.validate(guide(version))['passive_node_candidates']
            self.assertEqual(output['status'], 'ready')
            self.assertEqual([row['status'] for row in output['nodes']], statuses)
            self.assertEqual([row['query']['value'] for row in output['nodes']], [7, 8, 9])
            self.assertEqual(output['nodes'][0]['candidates'][0]['name_en'], name)
            self.assertEqual(output['nodes'][statuses.index('not_found')]['candidates'], [])
        output = self.validate(guide('old', (70,)))['passive_node_candidates']
        self.assertEqual(output['nodes'][0]['status'], 'not_found')

    def test_missing_unknown_versions_do_not_query(self):
        for version, status in [(None, 'missing_tree_version'), ('unknown', 'unknown_tree_version'),
                                ('latest', 'unknown_tree_version'), ('default', 'unknown_tree_version')]:
            data = guide(version)
            with self.subTest(version=version), patch.object(self.lookup, 'query', side_effect=AssertionError('queried')):
                output = self.validate(data)
                result = output['passive_node_candidates']
                self.assertEqual(result['status'], status)
                self.assertEqual(result['tree_version'], version)
                self.assertIsNone(result['nodes'])
                self.assertEqual(result['source'], self.index['source'])
                self.assertEqual(output['guide'], data)

    def test_missing_vs_explicit_empty_and_inference_provenance(self):
        for nodes, status, rows in [(None, 'missing_passive_nodes', None), ((), 'ready', [])]:
            output = self.validate(guide(nodes=nodes))
            self.assertEqual(output['passive_node_candidates']['status'], status)
            self.assertEqual(output['passive_node_candidates']['nodes'], rows)
            self.assertEqual('passive_nodes' in output['missing_fields'], nodes is None)
        data = guide()
        for field in ('passive_nodes', 'tree_version'):
            data['fields'][field].update(origin='inferred', reason='Authored uncertain extraction.')
        before = deepcopy(data)
        output = self.validate(data)
        result = output['passive_node_candidates']
        self.assertEqual(output['guide'], before)
        self.assertEqual(output['inferred_fields'], ['passive_nodes', 'tree_version'])
        self.assertEqual(result['source'], self.index['source'])
        self.assertEqual(result['nodes'][0], self.lookup.query('old', 7))
        self.assertEqual(result['nodes'][2], self.lookup.query('old', 9))
        self.assertEqual(result['confirmation'], 'pending')
        self.assertEqual(output['pob_generation'], 'pending')
        self.assertEqual(output['mcp_acceptance'], 'pending')
        self.assertNotIn('selected', result)
        result['source']['files'].clear()
        result['nodes'][0]['candidates'][0]['declaration']['source_line'] = 99
        output['guide']['fields']['passive_nodes']['value'].clear()
        self.assertEqual(data, before)
        self.assertEqual(self.validate(data)['passive_node_candidates']['nodes'][0], self.lookup.query('old', 7))
        self.assertEqual(self.lookup.source, self.index['source'])

    def test_index_failures_are_errors_even_without_nodes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'sources').mkdir()
            for name in ('pob.json', 'pob-skills.en.json', 'pob-classes.en.json'):
                (root / 'sources' / name).write_bytes((ROOT / 'sources' / name).read_bytes())
            with patch('guide_contract.ROOT', root):
                with self.assertRaises(OSError):
                    validate_guide(guide(None, None))
                for content, error in [('{', 'Expecting'), ('{}', 'schema_version'),
                                       (json.dumps(fixture()), 'pinned manifest')]:
                    (root / 'sources/pob-nodes.en.json').write_text(content)
                    with self.subTest(content=content), self.assertRaisesRegex(ValueError, error):
                        validate_guide(guide(None, None))

    def test_pinned_guide_cli(self):
        for version in ('0_1', '0_5'):
            data = guide(version, (4, 999999))
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'guide.json'
                path.write_text(json.dumps(data))
                run = subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/guide_contract.py'), str(path)],
                                     capture_output=True, text=True, timeout=5)
            self.assertEqual(run.returncode, 0, run.stderr)
            output = json.loads(run.stdout)
            self.assertEqual(output, validate_guide(data))
            self.assertEqual(output['passive_node_candidates']['nodes'][1]['status'], 'not_found')


if __name__ == '__main__':
    unittest.main()
