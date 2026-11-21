"""Authored slot aggregation evidence; no market or PoB integration."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from build_estimate import aggregate_quotes

FIXTURE = Path(__file__).resolve().parents[1] / 'tests/fixtures/m04/quotes.synthetic.json'


class BuildEstimateTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads(FIXTURE.read_text())

    def calc(self):
        return aggregate_quotes(self.data['slots'], **self.data['context'])

    def test_mixed_currency_missing_slots_and_preservation(self):
        before = deepcopy(self.data)
        result = self.calc()
        self.assertEqual(result['subtotals_by_currency'], {'divine': 2, 'exalted': .3})
        self.assertEqual(result['quoted_slot_count'], 3)
        self.assertEqual(result['matched_slots'], ['Helmet', 'Ring 1', 'Ring 2', 'Boots'])
        self.assertEqual(result['missing_slots'], [
            {'slot': 'Boots', 'reason': 'missing_price'},
            {'slot': 'Gloves', 'reason': 'missing_listing'}])
        for supplied, output in zip(self.data['slots'], result['slots']):
            self.assertEqual(output['listing'], supplied['listing'])
            self.assertEqual(output['matched_affixes'], supplied['matched_affixes'])
        result['slots'][0]['listing']['price']['amount'] = 999
        result['slots'][0]['matched_affixes'].append('changed')
        self.assertEqual(self.data, before)

    def test_all_missing_and_all_quoted(self):
        self.data['slots'] = self.data['slots'][3:]
        result = self.calc()
        self.assertEqual(result['subtotals_by_currency'], {})
        self.assertEqual(result['quoted_slot_count'], 0)
        self.setUp()
        self.data['slots'] = self.data['slots'][:3]
        self.assertEqual(self.calc()['missing_slots'], [])

    def test_context_isolation_and_tencent_contract(self):
        for field, value in [('realm', 'tencent'), ('league', 'Other')]:
            self.setUp()
            self.data['slots'][0]['listing'][field] = value
            with self.assertRaisesRegex(ValueError, 'realm/league'):
                self.calc()
        self.setUp()
        self.data['context']['realm'] = 'tencent'
        for row in self.data['slots']:
            if row['listing']:
                row['listing']['realm'] = 'tencent'
        self.assertEqual(self.calc()['subtotals_by_currency'], {'divine': 2, 'exalted': .3})

    def test_duplicate_and_malformed_slots(self):
        for slots in ([], None, {}, [self.data['slots'][0]] * 2,
                      [{'slot': 'Boots', 'matched_affixes': []}],
                      [{'slot': 'Boots', 'matched_affixes': ['Life'], 'listing': None}],
                      [{'slot': '', 'matched_affixes': [], 'listing': None}],
                      [{'slot': 'Boots', 'matched_affixes': 'Life', 'listing': None}]):
            with self.subTest(slots=slots), self.assertRaises(ValueError):
                aggregate_quotes(slots, **self.data['context'])

    def test_invalid_prices_and_overflow(self):
        for amount in (0, -1, True, '2', None, float('nan'), float('inf')):
            self.data['slots'][0]['listing']['price']['amount'] = amount
            with self.subTest(amount=amount), self.assertRaises(ValueError):
                self.calc()
        self.setUp()
        for row in self.data['slots'][:3]:
            row['listing']['price'] = {'amount': 1e308, 'currency': 'exalted'}
        with self.assertRaisesRegex(ValueError, 'finite range'):
            self.calc()

    def test_cli_success_and_atomic_failure(self):
        entry = Path(__file__).with_name('build_estimate.py')
        def run(path):
            return subprocess.run([sys.executable, '-B', str(entry), str(path)],
                                  capture_output=True, text=True, timeout=5)
        result = run(FIXTURE)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), self.calc())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'invalid.json'
            self.data['slots'][-1]['listing'] = {'id': 'bad'}
            for content in (json.dumps(self.data), '{', 'null'):
                path.write_text(content)
                result = run(path)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, '')
                self.assertNotIn('Traceback', result.stderr)


if __name__ == '__main__':
    unittest.main()
