"""M04: language steps around PoB's Trader on the Tencent trade site (scripts/tencent_trade.py).

The fetch test wraps the U07 real (anonymised) equipment items, which use the same official
item layout as the Tencent trade site's fetch answer, into fetch entries.
"""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tencent_trade as t  # noqa: E402
from assistant_backend import Backend  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
REAL = ROOT / 'tests/fixtures/u07/share.real-anon.json'


def fetch_entries():
    items = json.loads(REAL.read_text(encoding='utf-8'))['equipments']['equipments']
    entries = []
    for number, item in enumerate(items):
        item = copy.deepcopy(item)
        item['pseudoMods'] = [{'description': '[Sum|总和]: 172.5'}]
        entries.append({'id': f'hash{number}', 'item': item,
                        'listing': {'price': {'type': '~price', 'amount': 3, 'currency': 'divine'},
                                    'account': {'name': 'seller'}, 'whisper': '@卖家 你好'}})
    return entries


class TranslateItemsTests(unittest.TestCase):
    def test_items_become_english_and_keep_listing(self):
        entries = fetch_entries()
        answer = t.translate_items(entries)
        result = answer['result']
        self.assertGreaterEqual(len(result), len(entries) - 1)
        staff = next(e for e in result if e['id'] == 'hash0')
        self.assertEqual(staff['listing'], entries[0]['listing'])
        item = staff['item']
        self.assertEqual(item['rarity'], 'Rare')
        self.assertTrue(item['baseType'].isascii(), item['baseType'])
        self.assertIn('Quality', [p['name'] for p in item['properties']])
        self.assertTrue(all(isinstance(m, (str, dict)) for m in item['explicitMods']))
        self.assertIn('increased Fire Damage', json.dumps(item['explicitMods']))
        self.assertEqual(item['pseudoMods'], ['Sum: 172.5'])
        self.assertEqual(answer['report']['items'], len(result))

    def test_unknown_base_is_left_out(self):
        entries = fetch_entries()[:1]
        entries[0]['item']['baseType'] = entries[0]['item']['typeLine'] = '不存在的基底'
        answer = t.translate_items(entries)
        self.assertEqual(answer['result'], [])
        self.assertEqual(len(answer['report']['items_skipped']), 1)


class TranslateQueryTests(unittest.TestCase):
    def test_unique_and_base_names(self):
        body = {'query': {'name': 'Megalomaniac', 'type': 'Diamond', 'stats': []}, 'sort': {'price': 'asc'}}
        body, names, missing = t.translate_query(body)
        self.assertEqual(missing, [])
        self.assertEqual([en for en, _ in names], ['Megalomaniac', 'Diamond'])
        self.assertFalse(body['query']['name'].isascii())
        self.assertFalse(body['query']['type'].isascii())

    def test_option_form_and_missing(self):
        body = {'query': {'type': {'option': 'No Such Base'}}}
        body, names, missing = t.translate_query(body)
        self.assertEqual((names, missing), ([], ['No Such Base']))
        self.assertEqual(body['query']['type'], {'option': 'No Such Base'})

    def test_query_without_names_is_unchanged(self):
        body = {'query': {'stats': [{'type': 'weight', 'filters': []}]}}
        self.assertEqual(t.translate_query(copy.deepcopy(body)), (body, [], []))


class BackendMethodTests(unittest.TestCase):
    def setUp(self):
        self.backend = Backend.__new__(Backend)

    def test_methods_are_served(self):
        reply = self.backend.handle({'protocol': 'assistant-shell/1', 'method': 'translate-trade-items',
                                     'params': {'result': fetch_entries()[:2]}})
        self.assertIn('result', reply)
        self.assertEqual(len(reply['result']['result']), 2)
        reply = self.backend.handle({'protocol': 'assistant-shell/1', 'method': 'translate-trade-query',
                                     'params': {'body': {'query': {'name': 'Megalomaniac'}}}})
        self.assertEqual(reply['result']['names'][0][0], 'Megalomaniac')

    def test_bad_requests(self):
        for method, params in (('translate-trade-items', {}), ('translate-trade-query', {'body': 1})):
            reply = self.backend.handle({'protocol': 'assistant-shell/1', 'method': method, 'params': params})
            self.assertEqual(reply['error']['code'], 'bad-request')


if __name__ == '__main__':
    unittest.main()
