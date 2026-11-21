"""M01/M02 authored raw responses through explicit slot assembly and assistant."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from build_estimate import aggregate_quotes
from slot_quotes import assemble_file, assemble_quotes
from trade_listing import normalize_listings

ROOT = Path(__file__).resolve().parents[1]


class SlotQuoteTests(unittest.TestCase):
    def manifest(self, realm):
        return ROOT / f'tests/fixtures/m04/{realm}.selections.synthetic.json'

    def data(self, realm='international'):
        path = self.manifest(realm)
        manifest = json.loads(path.read_text())
        raw = json.loads((path.parent / manifest['response_file']).read_text())
        return manifest, raw, normalize_listings(raw, **manifest['context'])

    def test_both_realms_raw_to_assistant_preserves_slots_items_and_prices(self):
        for realm, totals in [('international', {'divine': 1.5, 'exalted': 12}),
                              ('tencent', {'合成神圣石': 1.5, '合成崇高石': 12})]:
            with self.subTest(realm=realm):
                manifest, raw, normalized = self.data(realm)
                contract = assemble_file(self.manifest(realm))
                result = subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/assistant.py'),
                                         'estimate-build', '--from-listings', str(self.manifest(realm))],
                                        capture_output=True, text=True, timeout=5, cwd='/tmp')
                self.assertEqual(result.returncode, 0, result.stderr)
                output = json.loads(result.stdout)
                self.assertEqual(output, aggregate_quotes(contract['slots'], **contract['context']))
                self.assertEqual(output['subtotals_by_currency'], totals)
                self.assertEqual(output['quoted_slot_count'], 2)
                self.assertEqual([r['slot'] for r in output['slots']], ['Ring 1', 'Belt', 'Ring 2', 'Gloves'])
                self.assertEqual(output['missing_slots'], [
                    {'slot': 'Ring 2', 'reason': 'missing_listing'},
                    {'slot': 'Gloves', 'reason': 'missing_listing'}])
                for index in range(2):
                    row = output['slots'][index]
                    self.assertEqual(row['listing'], normalized[index])
                    self.assertEqual(row['listing']['item'], raw['result'][index]['item'])
                    self.assertEqual(row['listing']['price'], raw['result'][index]['listing']['price'])
                    self.assertEqual(row['matched_affixes'], manifest['selections'][index]['matched_affixes'])

    def test_no_match_unpriced_reused_reference_and_copy_isolation(self):
        manifest, raw, normalized = self.data()
        normalized[0]['price'] = None
        selections = manifest['selections']
        selections[2]['listing_id'] = normalized[0]['id']
        before = deepcopy((normalized, selections))
        contract = assemble_quotes(normalized, selections, **manifest['context'])
        output = aggregate_quotes(contract['slots'], **contract['context'])
        self.assertEqual(output['matched_slots'], ['Ring 1', 'Belt', 'Ring 2'])
        self.assertEqual(output['missing_slots'][0], {'slot': 'Ring 1', 'reason': 'missing_price'})
        contract['slots'][0]['listing']['item']['name'] = 'changed'
        contract['slots'][0]['matched_affixes'].append('changed')
        self.assertEqual((normalized, selections), before)
        self.assertNotEqual(contract['slots'][2]['listing']['item']['name'], 'changed')
        for row in selections:
            row['listing_id'], row['matched_affixes'] = None, []
        empty = assemble_quotes([], selections, **manifest['context'])
        self.assertEqual(len(empty['slots']), 4)
        self.assertEqual(aggregate_quotes(empty['slots'], **empty['context'])['subtotals_by_currency'], {})

    def test_context_selection_and_inventory_errors(self):
        for case in ('realm', 'league', 'duplicate_id', 'unknown', 'absent', 'duplicate_slot', 'affixes'):
            manifest, raw, normalized = self.data()
            selections = manifest['selections']
            if case in ('realm', 'league'):
                normalized[-1][case] = 'other'
            elif case == 'duplicate_id':
                normalized.append(normalized[0])
            elif case == 'unknown':
                selections[-1]['listing_id'] = 'not-returned'
            elif case == 'absent':
                del selections[-1]['listing_id']
            elif case == 'duplicate_slot':
                selections[-1]['slot'] = selections[0]['slot']
            else:
                selections[-1]['matched_affixes'] = ['unmatched']
            with self.subTest(case=case), self.assertRaises(ValueError):
                assemble_quotes(normalized, selections, **manifest['context'])

    def test_cli_atomic_failures_including_unselected_raw_error(self):
        manifest, raw, normalized = self.data()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest['response_file'] = 'response.json'
            path = root / 'manifest.json'
            response = root / 'response.json'
            for invalid in ({'error': {'message': 'offline failure'}, 'result': []},
                            {'result': raw['result'] + [dict(raw['result'][0], id='bad', item={'league': 'Other'})]}):
                path.write_text(json.dumps(manifest))
                response.write_text(json.dumps(invalid))
                self.assert_cli_failure(path)
            response.unlink()
            self.assert_cli_failure(path)
            for content in ('null', '{'):
                path.write_text(content)
                self.assert_cli_failure(path)

    def assert_cli_failure(self, path):
        result = subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/assistant.py'),
                                 'estimate-build', '--from-listings', str(path)],
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, '')
        self.assertNotIn('Traceback', result.stderr)


if __name__ == '__main__':
    unittest.main()
