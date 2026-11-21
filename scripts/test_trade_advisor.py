"""M05: build-driven search conditions and value sorting in PoB's Trader, headless (needs
POB_ENGINE = our PoB branch with src/Modules/AssistantTradeAdvisor.lua). The build is the P02
fixture (level 1, nothing equipped); candidates are the U07 real (anonymised) equipment turned
into the assistant's English fetch answer (scripts/tencent_trade.py), filtered to gloves by PoB.
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from pob_server import LINUX_RUNTIME
from test_pob_server import real_engine
from test_tencent_trade import fetch_entries
import tencent_trade

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / 'tests/fixtures/p02/build.xml'


def advisor_engine():
    engine = real_engine()
    if engine and (engine / 'src/Modules/AssistantTradeAdvisor.lua').exists() \
            and (LINUX_RUNTIME / 'LuaJIT/src/luajit').exists():
        return engine
    return None


@unittest.skipUnless(advisor_engine(), 'POB_ENGINE is not our PoB branch with M05, or luajit missing')
class TradeAdvisorTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as directory:
            fetch = Path(directory) / 'fetch.json'
            answer = tencent_trade.translate_items(fetch_entries())
            fetch.write_text(json.dumps({'result': answer['result']}, ensure_ascii=False), encoding='utf-8')
            env = dict(os.environ, LUA_PATH='../runtime/lua/?.lua;../runtime/lua/?/init.lua;;',
                       LUA_CPATH=f'{LINUX_RUNTIME}/?.so;;', POE2_ASSISTANT_DATA_DIR=directory,
                       POE2_ASSISTANT_LOCALE='zh-CN', M05_BUILD=str(BUILD), M05_FETCH=str(fetch))
            run = subprocess.run([str(LINUX_RUNTIME / 'LuaJIT/src/luajit'), str(ROOT / 'scripts/trade_advisor_driver.lua')],
                                 cwd=advisor_engine() / 'src', env=env, capture_output=True, text=True,
                                 encoding='utf-8', timeout=300)
        if run.returncode != 0 or not run.stdout.strip():
            raise AssertionError(run.stderr[-3000:])
        cls.out = json.loads(run.stdout.strip().splitlines()[-1])

    def test_gap_filters_follow_the_engine(self):
        gaps = {g['tradeId']: g['value'] for g in self.out['gaps']}
        self.assertGreater(self.out['base']['fire'], 40)  # level 1, nothing equipped: far below cap
        for elem in ('fire', 'cold', 'lightning'):
            self.assertEqual(gaps[f'pseudo.pseudo_total_{elem}_resistance'], 40)
        self.assertNotIn('pseudo.pseudo_total_chaos_resistance', gaps)
        merged = {m['tradeId']: m['value'] for m in self.out['merged']}
        self.assertEqual(merged['pseudo.pseudo_total_fire_resistance'], 10)  # the user's own filter wins
        self.assertEqual(len(self.out['merged']), len(self.out['gaps']))

    def test_candidates_are_tried_and_sorted(self):
        self.assertGreaterEqual(self.out['candidates'], 1)
        for key in ('DPS', 'EHP', 'DPSPerDivine', 'EHPPerDivine'):
            sorted_rows = self.out['sorted'][key]
            self.assertIsNone(sorted_rows.get('err'), key)
            keys = [row['key'] for row in sorted_rows['rows']]
            self.assertEqual(keys, sorted(keys, reverse=True), key)
            self.assertEqual(len(keys), self.out['candidates'])
        for row in self.out['sorted']['EHPPerDivine']['rows']:
            ehp = row['ehp']
            value = ehp['percent'] if ehp.get('percent') is not None else ehp['absolute']
            self.assertAlmostEqual(row['key'], value / max(row['divines'], 0.01), places=6)
            self.assertIn('每神圣石', row['text'])
        # same item at 1 divine, 600 exalted (2) and 5 chaos (0.25): cheapest first per Divine
        self.assertEqual([r['divines'] for r in self.out['sorted']['DPSPerDivine']['rows']], [0.25, 1, 2])
        # equal DPS gain (same item): the cheaper first
        self.assertEqual([r['divines'] for r in self.out['sorted']['DPS']['rows']], [0.25, 1, 2])
        best = self.out['sorted']['EHP']['rows'][0]
        self.assertGreater(best['ehp']['after'], best['ehp']['before'])

    def test_missing_rate_falls_back(self):
        self.assertEqual(self.out['missingRate'], 'MissingConversionRates')

    def test_budget(self):
        self.assertAlmostEqual(self.out['remainingOther'], 8.0)  # 10 - 600 exalted at 300 per divine
        self.assertIn('预算剩余 5.0 神圣石', self.out['total'])


if __name__ == '__main__':
    unittest.main()
