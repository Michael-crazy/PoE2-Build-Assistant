"""Authored guide candidate integration; no resolution or generation claims."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import tempfile

from guide_contract import validate_guide
from query_pob_skills import SkillLookup

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'tests/fixtures/a01'


class GuideSkillCandidateTests(unittest.TestCase):
    def test_authored_cases_preserve_input_and_pending(self):
        lookup = SkillLookup(json.loads((FIXTURES / 'skill-query-index.json').read_text()))
        expected = {
            'ambiguous': ('ambiguous', None, 'not_comparable'),
            'conflict': ('single_candidate', 'single_candidate', 'conflict'),
            'overlap': ('ambiguous', 'single_candidate', 'overlap'),
            'id-only': (None, 'single_candidate', 'not_comparable'),
            'unknown': ('not_found', 'not_found', 'not_comparable'),
            'missing': (None, None, 'not_comparable'),
            'single': ('single_candidate', None, 'not_comparable'),
        }
        for case in json.loads((FIXTURES / 'skill-guides.synthetic.json').read_text()):
            with self.subTest(case=case['case']):
                data = case['guide']
                before = deepcopy(data)
                result = validate_guide(data, skill_lookup=lookup)
                candidates = result['main_skill_candidates']
                self.assertEqual(tuple(candidates[k]['status'] if candidates[k] else None
                                       for k in ('name', 'id')) +
                                 (candidates['name_id_consistency'],), expected[case['case']])
                if case['case'] == 'conflict':
                    self.assertEqual([r['id'] for r in candidates['name']['candidates']], ['Unique'])
                    self.assertEqual([r['id'] for r in candidates['id']['candidates']], ['One'])
                if case['case'] == 'ambiguous':
                    self.assertEqual([r['id'] for r in candidates['name']['candidates']], ['One', 'Two'])
                self.assertNotIn('selected', candidates)
                self.assertEqual(result['guide'], before)
                self.assertEqual(candidates['confirmation'], 'pending')
                self.assertEqual(result['pob_generation'], 'pending')
                self.assertEqual(result['mcp_acceptance'], 'pending')
                for by, field in [('name', 'main_skill_name'), ('id', 'main_skill_id')]:
                    fact = data['fields'][field]
                    self.assertEqual(field in result['missing_fields'], fact['origin'] == 'missing')
                    if candidates[by]:
                        self.assertEqual(candidates[by]['query'], dict(by=by, value=fact['value']))
                        self.assertEqual(candidates[by]['source'], lookup.source)
                        candidates[by]['candidates'].clear()
                self.assertEqual(data, before)
                if candidates['name'] and candidates['name']['candidate_count']:
                    self.assertTrue(lookup.query('name', data['fields']['main_skill_name']['value'])['candidates'])
                self.assertEqual(validate_guide(data, skill_lookup=lookup)['main_skill_candidates']['confirmation'], 'pending')

    def test_pinned_index_english_fixtures(self):
        for name, status, consistency in [('english-ambiguous', 'ambiguous', 'not_comparable'),
                                           ('english-conflict', 'single_candidate', 'conflict')]:
            data = json.loads((FIXTURES / (name + '.json')).read_text())
            result = validate_guide(data)
            self.assertEqual(result['main_skill_candidates']['name']['status'], status)
            self.assertEqual(result['main_skill_candidates']['name_id_consistency'], consistency)

    def test_inferred_fields_not_promoted(self):
        data = json.loads((FIXTURES / 'english-conflict.json').read_text())
        data['fields']['main_skill_id'].update(origin='inferred', reason='Authored uncertain extraction.')
        result = validate_guide(data)
        self.assertIn('main_skill_id', result['inferred_fields'])
        self.assertEqual(result['guide'], data)
        self.assertEqual(result['main_skill_candidates']['confirmation'], 'pending')

    def test_index_failure_does_not_return_success(self):
        data = json.loads((FIXTURES / 'english-conflict.json').read_text())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'sources').mkdir()
            with patch('guide_contract.ROOT', root):
                with self.assertRaises(OSError):
                    validate_guide(data)
                for filename in ('pob-skills.en.json', 'pob.json'):
                    (root / 'sources' / filename).write_text((ROOT / 'sources' / filename).read_text())
                manifest = json.loads((root / 'sources/pob.json').read_text())
                manifest['commit'] = '0' * 40
                (root / 'sources/pob.json').write_text(json.dumps(manifest))
                with self.assertRaisesRegex(ValueError, 'pinned manifest'):
                    validate_guide(data)


if __name__ == '__main__':
    unittest.main()
