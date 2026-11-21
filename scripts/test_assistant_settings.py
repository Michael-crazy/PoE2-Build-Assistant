"""U03: the "In-game assistant" group in PoB's Options popup reads the
assistant's config.json and writes the changed entries to
pob-settings-request.json (needs POB_ENGINE = our PoB branch with U03)."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

from pob_server import LINUX_RUNTIME
from test_pob_server import real_engine

ROOT = Path(__file__).resolve().parents[1]

CONFIG = {
    'overlayKey': 'Shift + Space', 'realm': 'pc-tencent', 'language': 'cmn-Hant', 'followGame': False,
    'fontSize': 19, 'hideOverlayOnBlur': False, 'overlayBackgroundClose': True, 'restoreClipboard': False,
    'widgets': [
        {'wmType': 'price-check', 'hotkey': 'D', 'hotkeyHold': 'Ctrl'},
        {'wmType': 'assistant-eval', 'hotkey': 'Ctrl + Shift + D'},
    ],
}
CORE = ['evaluateKey', 'followGame', 'fontSize', 'hideOverlayOnBlur', 'language', 'overlayBackgroundClose',
        'overlayKey', 'priceCheckKey', 'realm', 'restoreClipboard']
# Added later (M08a, U06, M08b, M09a); an assistant config written before them lacks the keys.
VALUE = {'valueCurrency': 'divine', 'tencentExaltedPerDivine': 0, 'tencentChaosPerDivine': 0,
         'tencentDivinePerMirror': 0}
WEB = {'webPreview': True, 'webPreviewPort': 37428}  # M09a
NEWER = {'evaluateClipboardKey': 'Ctrl + Shift + V', 'watchClipboard': True, 'addToPobKey': 'Ctrl + Shift + A',
         **VALUE, **WEB}
ALL = sorted(CORE + list(NEWER))


def settings_engine():
    engine = real_engine()
    luajit = LINUX_RUNTIME / 'LuaJIT/src/luajit'
    if engine and (engine / 'src/Modules/AssistantSettings.lua').exists() and luajit.exists():
        return engine
    return None


@unittest.skipUnless(settings_engine(), 'POB_ENGINE is not our PoB branch with U03, or luajit missing')
class AssistantOptionsTests(unittest.TestCase):

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.data = Path(self.directory.name) / 'apt-data'
        self.data.mkdir()
        self.request = self.data / 'pob-settings-request.json'
        self.pob = None

    def tearDown(self):
        if self.pob:
            self.pob.stdin.close()
            self.pob.wait(timeout=30)
            self.pob.stdout.close()
        self.directory.cleanup()

    def write_config(self, config):
        (self.data / 'config.json').write_text(json.dumps(config), encoding='utf-8')

    def write_status(self, age=0, rejected=None, port=None):
        status = {'protocol': 'assistant-status/1', 'pid': 4321, 'time': time.time() - age, 'version': '0.16.3',
                  'applied': {'seq': 1, 'rejected': rejected or {}}}
        if port is not None:
            status['port'] = port
        (self.data / 'assistant-status.json').write_text(json.dumps(status), encoding='utf-8')

    def start(self):
        runtime = LINUX_RUNTIME
        env = dict(os.environ, LUA_PATH='../runtime/lua/?.lua;../runtime/lua/?/init.lua;;',
                   LUA_CPATH=f'{runtime}/?.so;;', POE2_ASSISTANT_DATA_DIR=self.directory.name,
                   POE2_ASSISTANT_LOCALE='zh-CN')
        self.pob = subprocess.Popen([str(runtime / 'LuaJIT/src/luajit'), str(ROOT / 'scripts/assistant_settings_driver.lua')],
                                    cwd=settings_engine() / 'src', env=env, stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding='utf-8')

    def cmd(self, line):
        if not self.pob:
            self.start()
        self.pob.stdin.write(line + '\n')
        self.pob.stdin.flush()
        return json.loads(self.pob.stdout.readline())

    def saved_request(self):
        request = json.loads(self.request.read_text(encoding='utf-8'))
        self.assertEqual(request['protocol'], 'pob-settings/1')
        self.assertIsInstance(request['seq'], int)
        return request['set']

    def test_shows_the_assistant_config(self):
        self.write_config(CONFIG)
        opened = self.cmd('open')
        self.assertEqual(opened['shown'], ALL)  # keys missing from this config show their defaults (B04)
        self.assertEqual(opened['values'], {
            'evaluateKey': 'Ctrl + Shift + D', 'priceCheckKey': 'Ctrl + D', 'overlayKey': 'Shift + Space',
            'followGame': False, 'realm': 'pc-tencent', 'language': 'cmn-Hant', 'fontSize': 19,
            'hideOverlayOnBlur': False, 'overlayBackgroundClose': True, 'restoreClipboard': False, **NEWER})

    def test_version_36_config_shows_newer_settings_with_defaults(self):
        # B04: the user's config.json was last written by a version-36 assistant
        # (before M08a and U06), so the newer keys are missing from the file.
        config = json.loads(json.dumps(CONFIG))
        config['configVersion'] = 36
        config['widgets'][1]['hotkey'] = 'Alt + R'
        self.write_config(config)
        opened = self.cmd('open')
        self.assertEqual(opened['shown'], ALL)
        self.assertEqual({key: opened['values'][key] for key in NEWER}, NEWER)
        self.assertEqual(opened['values']['evaluateKey'], 'Alt + R')
        # The assistant writes its upgraded config back with the same defaults:
        # nothing changes in the open popup and nothing is sent.
        upgraded = json.loads(json.dumps(config))
        upgraded['configVersion'] = 39
        upgraded['widgets'][1].update(clipboardHotkey='Ctrl + Shift + V', watchClipboard=True,
                                      addToPobHotkey='Ctrl + Shift + A', **VALUE)
        self.write_config(upgraded)
        time.sleep(1.1)
        self.cmd('status')
        self.assertEqual(self.cmd('values')['values'], opened['values'])
        # Changing them goes through the usual request; untouched defaults are not sent.
        self.write_config(config)
        self.assertEqual(self.cmd('press evaluateClipboardKey v ctrl alt')['hotkey'], 'Ctrl + Alt + V')
        self.cmd('set watchClipboard false')
        self.assertEqual(self.cmd('save'), {'open': False})
        self.assertEqual(self.saved_request(), {
            'widget:assistant-eval.clipboardHotkey': 'Ctrl + Alt + V', 'widget:assistant-eval.watchClipboard': False})
        # Clearing a missing hotkey sends null.
        self.request.unlink()
        self.cmd('open')
        self.assertIsNone(self.cmd('press addToPobKey BACK')['hotkey'])
        self.cmd('save')
        self.assertEqual(self.saved_request(), {'widget:assistant-eval.addToPobHotkey': None})

    def test_settings_the_assistant_adds_appear(self):
        config = json.loads(json.dumps(CONFIG))
        config['widgets'][1]['watchClipboard'] = True  # names from M08a
        config['widgets'][1]['clipboardHotkey'] = None
        self.write_config(config)
        opened = self.cmd('open')
        self.assertIn('watchClipboard', opened['shown'])
        self.assertIn('evaluateClipboardKey', opened['shown'])
        config['widgets'][1]['addToPobHotkey'] = 'Ctrl + Alt + A'  # U06
        self.write_config(config)
        self.assertEqual(self.cmd('open')['values']['addToPobKey'], 'Ctrl + Alt + A')
        self.assertEqual((opened['values']['watchClipboard'], opened['values']['evaluateClipboardKey']), (True, None))

    def test_value_for_money_settings(self):
        # M08b: base currency and the Tencent rates typed by hand (0 = not set, shown empty).
        config = json.loads(json.dumps(CONFIG))
        config['widgets'][1].update(VALUE, tencentExaltedPerDivine=400)
        self.write_config(config)
        opened = self.cmd('open')
        self.assertEqual({key: opened['values'][key] for key in VALUE}, {**VALUE, 'tencentExaltedPerDivine': 400})
        self.cmd('set valueCurrency "exalted"')
        self.cmd('set tencentChaosPerDivine "35.5"')
        self.cmd('set tencentExaltedPerDivine ""')  # cleared = not set
        self.assertEqual(self.cmd('set tencentDivinePerMirror "0"')['values']['tencentDivinePerMirror'], 0)  # unchanged
        self.cmd('save')
        self.assertEqual(self.saved_request(), {
            'widget:assistant-eval.valueCurrency': 'exalted', 'widget:assistant-eval.tencentChaosPerDivine': 35.5,
            'widget:assistant-eval.tencentExaltedPerDivine': 0})

    def test_web_preview_settings(self):
        # M09a: the trade-site extension's switch and port, shown with defaults until the assistant writes them.
        self.write_config(CONFIG)
        opened = self.cmd('open')
        self.assertEqual({key: opened['values'][key] for key in WEB}, WEB)
        self.cmd('set webPreview false')
        self.cmd('set webPreviewPort "40000"')
        self.cmd('save')
        self.assertEqual(self.saved_request(), {'widget:assistant-eval.webPreview': False,
                                                'widget:assistant-eval.webPreviewPort': 40000})

    def test_defaults_before_the_assistant_ever_ran(self):
        opened = self.cmd('open')
        self.assertEqual(opened['shown'], ALL)  # every setting has a default
        self.assertEqual(opened['values']['addToPobKey'], 'Ctrl + Shift + A')
        self.assertEqual((opened['values']['evaluateKey'], opened['values']['realm'], opened['values']['followGame']),
                         ('Ctrl + Shift + D', 'pc-ggg', True))
        self.cmd('set followGame false')
        self.cmd('save')
        self.assertEqual(self.saved_request(), {'followGame': False})

    def test_save_writes_only_changed_entries(self):
        self.write_config(CONFIG)
        self.cmd('open')
        self.assertEqual(self.cmd('press evaluateKey e ctrl alt')['hotkey'], 'Ctrl + Alt + E')
        self.assertEqual(self.cmd('press priceCheckKey q alt')['hotkey'], 'Alt + Q')
        self.cmd('set realm "pc-ggg"')
        self.cmd('set hideOverlayOnBlur true')
        self.cmd('set fontSize 19')  # unchanged
        self.assertEqual(self.cmd('save'), {'open': False})
        self.assertEqual(self.saved_request(), {
            'widget:assistant-eval.hotkey': 'Ctrl + Alt + E', 'widget:price-check.hotkey': 'Q',
            'widget:price-check.hotkeyHold': 'Alt', 'realm': 'pc-ggg', 'hideOverlayOnBlur': True})

    def test_cancel_and_unchanged_save_write_nothing(self):
        self.write_config(CONFIG)
        self.cmd('open')
        self.cmd('set realm "pc-ggg"')
        self.cmd('cancel')
        self.cmd('open')
        self.cmd('save')
        self.assertFalse(self.request.exists())

    def test_hotkey_capture(self):
        self.write_config(CONFIG)
        self.cmd('open')
        # Shift is not allowed for the price check hold key; capture goes on.
        self.assertEqual(self.cmd('press priceCheckKey q shift alt'),
                         {'capturing': True, 'keepsFocus': True, 'hotkey': 'Ctrl + D'})
        self.assertEqual(self.cmd('press evaluateKey F12 ctrl')['capturing'], True)  # F12 is the assistant's
        self.assertEqual(self.cmd('press evaluateKey ESCAPE')['hotkey'], 'Ctrl + Shift + D')
        self.assertEqual(self.cmd('press evaluateKey SPACE shift')['hotkey'], 'Shift + Space')
        self.assertEqual(self.cmd('press overlayKey BACK')['hotkey'], 'Shift + Space')  # required
        self.assertIsNone(self.cmd('press evaluateKey BACK')['hotkey'])
        self.cmd('save')
        self.assertEqual(self.saved_request(), {'widget:assistant-eval.hotkey': None})

    def test_merges_into_a_request_not_yet_applied(self):
        self.write_config(CONFIG)
        self.request.write_text(json.dumps({'protocol': 'pob-settings/1', 'seq': 1, 'set': {'realm': 'pc-ggg'}}))
        self.cmd('open')
        self.cmd('set fontSize 14')
        self.cmd('save')
        self.assertEqual(self.saved_request(), {'realm': 'pc-ggg', 'fontSize': 14})

    def test_status(self):
        self.write_config(CONFIG)
        self.cmd('open')
        self.assertEqual(self.cmd('status')['text'], '^8未运行')
        self.write_status()
        time.sleep(1.1)  # the status file is read once a second
        self.assertEqual(self.cmd('status')['text'], '^2已连接（进程 4321）')
        self.request.write_text('{}')
        time.sleep(1.1)
        self.assertEqual(self.cmd('status')['text'], '^xFFD700已连接，正在应用修改…')
        self.request.unlink()
        self.write_status(rejected={'widget:price-check.hotkeyHold': 'invalid value'})
        time.sleep(1.1)
        self.assertEqual(self.cmd('status')['text'], '^1助手未接受：查价快捷键')
        self.write_status(age=30)
        time.sleep(1.1)
        self.assertEqual(self.cmd('status')['text'], '^8未运行')

    def test_open_market_button(self):
        """M09b: "打开市集" asks the running assistant over its local bridge to open its trade window."""
        self.write_config(CONFIG)
        self.cmd('open')
        self.assertEqual(self.cmd('market {}'), {'url': None, 'header': None,
                                                 'message': '^1助手未运行：请先启动游戏内助手。'})
        self.write_status(port=41812)
        reply = self.cmd('market {"state": "opened", "realm": "pc-tencent"}')
        self.assertEqual(reply['url'], 'http://127.0.0.1:41812/pob-trade/market')
        self.assertIn('X-PoB-Trade: 1', reply['header'].splitlines())
        self.assertEqual(reply['message'], '^7已在助手里打开国服市集窗口。')
        self.assertEqual(self.cmd('market {"state": "opened", "realm": "pc-ggg"}')['message'],
                         '^7已在助手里打开国际服市集窗口。')
        self.assertTrue(self.cmd('market ')['message'].startswith('^1没能打开市集窗口：'))

    def test_follows_changes_made_in_the_assistant(self):
        self.write_config(CONFIG)
        self.cmd('open')
        self.cmd('set language "en"')  # changed in PoB: kept
        changed = json.loads(json.dumps(CONFIG))
        changed['widgets'][1]['hotkey'] = 'Alt + E'
        changed['language'] = 'ru'
        self.write_config(changed)
        time.sleep(1.1)
        self.cmd('status')  # a frame: the config is re-read once a second
        values = self.cmd('values')['values']
        self.assertEqual((values['evaluateKey'], values['language']), ('Alt + E', 'en'))
        self.cmd('save')
        self.assertEqual(self.saved_request(), {'language': 'en'})


if __name__ == '__main__':
    unittest.main()
