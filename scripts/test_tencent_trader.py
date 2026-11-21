"""M04: PoB's Trader on the Tencent site, headless (needs POB_ENGINE = our PoB branch with
src/Modules/AssistantTencentTrade.lua). scripts/tencent_trader_driver.lua answers PoB's requests
from a queue; the fetch answer is the U07 real (anonymised) equipment turned into English by
scripts/tencent_trade.py, i.e. what the assistant hands PoB.
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from urllib.parse import quote

from pob_server import LINUX_RUNTIME
from test_pob_server import real_engine
from test_tencent_trade import fetch_entries
import tencent_trade

ROOT = Path(__file__).resolve().parents[1]
LEAGUE = quote('奥杜尔秘符')
BRIDGE = 'http://127.0.0.1:41812/pob-trade/'


def trader_engine():
    engine = real_engine()
    if engine and (engine / 'src/Modules/AssistantTencentTrade.lua').exists() \
            and (LINUX_RUNTIME / 'LuaJIT/src/luajit').exists():
        return engine
    return None


@unittest.skipUnless(trader_engine(), 'POB_ENGINE is not our PoB branch with M04, or luajit missing')
class TencentTraderTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        root = Path(cls.directory.name)
        data = root / 'apt-data'
        data.mkdir()
        config = {'realm': 'pc-tencent', 'widgets': [
            {'wmType': 'assistant-eval', 'tencentExaltedPerDivine': 50, 'tencentChaosPerDivine': 30,
             'tencentDivinePerMirror': 0}]}
        (data / 'config.json').write_text(json.dumps(config), encoding='utf-8')
        (data / 'assistant-status.json').write_text(json.dumps(
            {'protocol': 'assistant-status/1', 'pid': 4321, 'time': time.time() + 600, 'port': 41812}),
            encoding='utf-8')
        cls.translated = tencent_trade.translate_items(fetch_entries())
        fetch = root / 'fetch.json'
        fetch.write_text(json.dumps({'result': cls.translated['result']}, ensure_ascii=False), encoding='utf-8')
        env = dict(os.environ, LUA_PATH='../runtime/lua/?.lua;../runtime/lua/?/init.lua;;',
                   LUA_CPATH=f'{LINUX_RUNTIME}/?.so;;', POE2_ASSISTANT_DATA_DIR=str(root),
                   POE2_ASSISTANT_LOCALE='zh-CN', M04_FETCH=str(fetch))
        run = subprocess.run([str(LINUX_RUNTIME / 'LuaJIT/src/luajit'), str(ROOT / 'scripts/tencent_trader_driver.lua')],
                             cwd=trader_engine() / 'src', env=env, capture_output=True, text=True,
                             encoding='utf-8', timeout=300)
        if run.returncode != 0 or not run.stdout.strip():
            raise AssertionError(run.stderr[-3000:])
        cls.out = json.loads(run.stdout.strip().splitlines()[-1])

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def test_search_and_fetch_go_through_the_assistant(self):
        calls = self.out['tencent']['calls']
        self.assertEqual(calls[0]['url'], f'{BRIDGE}search/{LEAGUE}')
        self.assertIn('X-PoB-Trade: 1', calls[0]['header'])
        self.assertNotIn('Authorization', calls[0]['header'])
        self.assertTrue(calls[1]['url'].startswith(f"{BRIDGE}fetch/hash0,hash1,"), calls[1]["url"])
        self.assertTrue(calls[1]['url'].endswith('?query=Q1'))
        self.assertIn('X-PoB-Trade: 1', calls[1]['header'])
        self.assertTrue(all('pathofexile' not in c['url'] for c in calls))

    def test_tencent_items_parse_in_pob(self):
        items = self.out['tencent']['items']
        self.assertIsNone(self.out['tencent'].get('err'))
        self.assertEqual(len(items), len(self.translated['result']))
        for item in items:
            self.assertTrue(item.get('base'), item['text'])
            self.assertEqual((item['amount'], item['currency'], item['trader']), (3, 'divine', 'seller'))
            self.assertEqual(item['weight'], '172.5')
        staff = items[0]
        self.assertEqual(staff['rarity'], 'RARE')
        self.assertGreaterEqual(staff['mods'], 5)

    def test_international_is_unchanged(self):
        calls = self.out['international']['calls']
        self.assertEqual(calls[0]['url'], 'https://www.pathofexile.com/api/trade2/search/poe2/Standard')
        self.assertIn('Authorization: Bearer test-token', calls[0]['header'])
        self.assertEqual(calls[1]['url'], 'https://www.pathofexile.com/api/trade2/fetch/x1?query=Q2')

    def test_login_message_reaches_the_trader(self):
        self.assertEqual(self.out['login']['err'], '国服市集未登录或登录已过期')

    def test_pasted_tencent_link(self):
        link = self.out['link']
        self.assertTrue(link['link'].startswith(f'https://poe.game.qq.com/trade2/search/poe2/{LEAGUE}/'))
        self.assertEqual(link['calls'][0]['url'], f'{BRIDGE}search/{LEAGUE}')

    def test_leagues(self):
        leagues = self.out['leagues']
        self.assertEqual(leagues['leagues'], ['奥杜尔秘符', '周年庆巅峰挑战（专家）'])
        self.assertEqual(leagues['calls'][0]['url'], f'{BRIDGE}leagues')

    def test_trader_rates_and_total(self):
        trader = self.out['trader']
        self.assertEqual(trader['realmIndex'], 2)  # assistant set to the Tencent server
        self.assertFalse(trader['canSearchInternational'])
        self.assertTrue(trader['canSearchTencent'])
        self.assertAlmostEqual(trader['exalted'], 2.0)
        self.assertAlmostEqual(trader['chaos'], 1.0)
        self.assertIsNone(trader['annul'])
        self.assertIn('(≈ 3.0 divine)', trader['total'])
        self.assertNotIn('≈', trader['totalWithoutRate'])

    def test_assistant_not_running(self):
        self.assertEqual(self.out['stopped'], {'err': '国服市集需要游戏内助手：请先启动助手。', 'calls': 0})


if __name__ == '__main__':
    unittest.main()
