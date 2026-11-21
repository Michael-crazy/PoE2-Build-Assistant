"""Authored candidate fixtures; no game, network, translation or BD generation."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from query_pob_skills import SkillLookup

ROOT = Path(__file__).resolve().parents[1]


class SkillQueryTests(unittest.TestCase):
    def setUp(self):
        self.index = json.loads((ROOT / 'tests/fixtures/a01/skill-query-index.json').read_text())
        self.lookup = SkillLookup(self.index)

    def test_shared_name_keeps_all_ids_and_provenance(self):
        result = self.lookup.query('name', 'Shared Name')
        self.assertEqual(result['status'], 'ambiguous')
        self.assertEqual(result['candidate_count'], 2)
        self.assertEqual([r['id'] for r in result['candidates']], ['One', 'Two'])
        self.assertEqual(result['source'], self.index['source'])
        self.assertEqual(result['candidates'][0]['declarations'][0]['source_line'], 1)
        result['candidates'][0]['name_en'] = 'mutated'
        self.assertEqual(self.lookup.query('id', 'One')['candidates'][0]['name_en'], 'Shared Name')

    def test_id_and_name_are_explicit_namespaces(self):
        for by, expected in (('id', 'One'), ('name', 'Unique')):
            result = self.lookup.query(by, 'One')
            self.assertEqual(result['status'], 'single_candidate')
            self.assertEqual(result['candidates'][0]['id'], expected)

    def test_empty_name_reachable_only_by_id_and_unknown_is_explicit(self):
        hidden = self.lookup.query('id', 'Hidden')
        self.assertEqual(hidden['status'], 'single_candidate')
        self.assertEqual(hidden['candidates'][0]['name_en'], '')
        for by in ('name', 'id'):
            for value in ('', '   ', '\t'):
                result = self.lookup.query(by, value)
                self.assertEqual((result['status'], result['candidates']), ('empty_query', []))
            for value in ('Unknown', 'shared name', ' Shared Name ', '中文技能'):
                result = self.lookup.query(by, value)
                self.assertEqual((result['status'], result['candidate_count']), ('not_found', 0))

    def test_reject_inconsistent_index_and_invalid_query(self):
        for modify in (lambda i: i.update(schema_version=True),
                       lambda i: i['source'].update(commit='invalid'),
                       lambda i: i['skills'].append(deepcopy(i['skills'][0])),
                       lambda i: i['skills'][0].update(name_en=None),
                       lambda i: i['skills'][0].update(declarations=[])):
            index = deepcopy(self.index)
            modify(index)
            with self.assertRaises(ValueError):
                SkillLookup(index)
        with self.assertRaisesRegex(ValueError, 'pinned manifest'):
            SkillLookup(self.index, dict(self.index['source'], commit='2' * 40))
        for by, value in (('auto', 'One'), ('name', None)):
            with self.assertRaises(ValueError):
                self.lookup.query(by, value)

    def test_cli_local_index_and_failures(self):
        def run(*args):
            return subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/query_pob_skills.py'),
                                   *args], capture_output=True, text=True, timeout=5)
        result = run('--by', 'name', '')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'], 'empty_query')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'index.json'
            for content in ('{', '[]', json.dumps(self.index)):
                path.write_text(content)
                result = run('--index', str(path), '--by', 'name', 'Shared Name')
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, '')
                self.assertNotIn('Traceback', result.stderr)
            result = run('--index', str(path.with_name('missing')), '--by', 'id', 'One')
            self.assertEqual(result.returncode, 1)


if __name__ == '__main__':
    unittest.main()
