"""Synthetic arithmetic and context isolation; no live rates or engine claims."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from upgrade_value import calculate_upgrade

FIXTURE = Path(__file__).resolve().parents[1] / 'tests/fixtures/m06/candidates.synthetic.json'


class UpgradeValueTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads(FIXTURE.read_text())

    def calc(self, index=0, **overrides):
        row = self.data['candidates'][index]
        return calculate_upgrade(row['listing'], row['trial'],
                                 **{**self.data['context'], 'rates': self.data['rates'], **overrides})

    def test_conversion_and_comparison_and_no_mutation(self):
        before = deepcopy(self.data)
        first, second = self.calc(), self.calc(1)
        self.assertEqual(first['normalized_price'], 200)
        self.assertEqual(first['rate_used'], 100)
        self.assertEqual(first['gain_per_currency'], 1)
        baseline = self.data['candidates'][0]['trial']['baseline']['CombinedDPS']
        self.assertAlmostEqual(first['gain_percent'], 200 / baseline * 100)
        self.assertAlmostEqual(first['gain_percent_per_currency'], 100 / baseline)
        self.assertEqual(second['normalized_price'], 50)
        self.assertEqual(second['gain_per_currency'], 2)
        self.assertEqual(second['rate_used'], 1)
        self.assertEqual(first['price'], self.data['candidates'][0]['listing']['price'])
        first['trial']['baseline']['Life'] = 999
        self.assertEqual(self.data, before)

    def test_survival_negative_and_zero_gain(self):
        self.assertEqual(self.calc(metric='Life')['gain_per_currency'], .1)
        self.assertEqual(self.calc(1, metric='Life')['gain_per_currency'], -.2)
        self.assertEqual(self.calc(metric='Armour')['gain_per_currency'], 0)
        # Absolute gain is defined even for a zero baseline; no percentage division.
        self.data['candidates'][0]['trial']['replacement']['Armour'] = 20
        self.assertEqual(self.calc(metric='Armour')['gain_per_currency'], .1)
        self.assertIsNone(self.calc(metric='Armour')['gain_percent_per_currency'])

    def test_missing_prices_and_rates_preserve_trials(self):
        for index, rates, status in [(2, None, 'missing_price'), (0, None, 'missing_rate'),
                                     (0, {**self.data['rates'], 'units': {}}, 'missing_rate')]:
            result = self.calc(index, rates=rates)
            self.assertEqual(result['status'], status)
            self.assertIsNone(result['gain_per_currency'])
            self.assertIsNone(result['normalized_price'])
            self.assertEqual(result['trial'], self.data['candidates'][index]['trial'])
            self.assertGreater(result['delta']['CombinedDPS'], 0)
        self.assertEqual(self.calc(1, rates=None)['status'], 'ok')

    def test_rate_scope_and_listing_scope(self):
        for field, value, status in [('realm', 'tencent', 'rate_context_mismatch'),
                                     ('league', 'Other', 'rate_context_mismatch'),
                                     ('currency', 'chaos', 'rate_currency_mismatch')]:
            with self.subTest(field=field):
                self.assertEqual(self.calc(rates={**self.data['rates'], field: value})['status'], status)
        for context in ({'realm': 'tencent'}, {'league': 'Other'}):
            with self.assertRaisesRegex(ValueError, 'listing realm/league'):
                self.calc(**context)
        self.data['context']['realm'] = 'tencent'
        self.data['rates']['realm'] = 'tencent'
        self.data['candidates'][0]['listing']['realm'] = 'tencent'
        self.assertEqual(self.calc()['gain_per_currency'], 1)

    def test_invalid_numbers_and_metric(self):
        for value in (0, -1, True, '2', None, float('nan'), float('inf')):
            with self.subTest(value=value):
                self.data['rates']['units']['divine'] = value
                with self.assertRaises(ValueError):
                    self.calc()
                self.data['candidates'][1]['listing']['price']['amount'] = value
                with self.assertRaises(ValueError):
                    self.calc(1)
        self.setUp()
        with self.assertRaises(ValueError):
            self.calc(metric='survival')
        for value in (-1, True, None, float('nan'), float('inf')):
            self.data['candidates'][0]['trial']['baseline']['Life'] = value
            with self.assertRaises(ValueError):
                self.calc()

    def test_cli_success_and_failure(self):
        entry = Path(__file__).with_name('upgrade_value.py')
        def run(path):
            return subprocess.run([sys.executable, '-B', str(entry), str(path)],
                                  capture_output=True, text=True, timeout=5)
        result = run(FIXTURE)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([row['gain_per_currency'] for row in json.loads(result.stdout)], [1, 2, None])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'bad.json'
            path.write_text('{')
            result = run(path)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, '')
        self.assertNotIn('Traceback', result.stderr)


if __name__ == '__main__':
    unittest.main()
