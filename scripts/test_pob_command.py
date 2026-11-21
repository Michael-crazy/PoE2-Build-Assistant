"""U06 command channel: the assistant adds an item to the build open in PoB.
Fake PoB threads cover sequence numbers, stale results, a PoB that is gone,
has no build open, dies or does not answer; a headless PoB from our branch
(POB_ENGINE = the branch tree) covers the real add."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
import unittest

from assistant_backend import Backend, BackendError, parse_params, pob_item_text
import pob_command
import pob_live
from pob_server import LINUX_RUNTIME
from test_pob_live import live_engine, snapshot
from test_pob_server import REAL

ROOT = Path(__file__).resolve().parents[1]
ARMOUR = (ROOT / 'tests/fixtures/p05/real/intl-zh-hant-body-armour-advanced.txt').read_text(encoding='utf-8-sig')
RARE_NAME = '末日的 救贖者'
PID = os.getpid()  # a running process for the fake PoB


def running(pid):
    return 0.0


class FakePoB(threading.Thread):
    """Answers each command file the way AssistantCommands.lua does."""

    def __init__(self, directory, pid=PID, status='added'):
        super().__init__(daemon=True)
        self.request = directory / f'{pid}.json'
        self.answer = directory / f'{pid}.result.json'
        self.status, self.seen, self.stopped = status, [], threading.Event()

    def run(self):
        while not self.stopped.is_set():
            if self.request.exists():
                command = json.loads(self.request.read_text(encoding='utf-8'))
                self.request.unlink()
                self.seen.append(command)
                temp = self.answer.with_name('answer.tmp')
                temp.write_text(json.dumps({'protocol': 'pob-command/1', 'seq': command['seq'],
                                            'status': self.status, 'itemId': 7}), encoding='utf-8')
                os.replace(temp, self.answer)
            time.sleep(0.01)


class ChannelTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.user = Path(self.directory.name)
        self.live = self.user / pob_live.LIVE_DIR
        self.live.mkdir(parents=True)
        self.commands = self.user / pob_command.COMMAND_DIR
        self.pob = None

    def tearDown(self):
        if self.pob:
            self.pob.stopped.set()
            self.pob.join()
        self.directory.cleanup()

    def publish(self, **meta):
        (self.live / f'{PID}.xml').write_text(snapshot(PID, 1, **meta), encoding='utf-8')

    def start_pob(self, **options):
        self.commands.mkdir(exist_ok=True)
        self.pob = FakePoB(self.commands, **options)
        self.pob.start()

    def send(self, **options):
        target = pob_command.find_pob(self.user, started=running)
        return pob_command.send(target, {'command': 'add-item', 'item_text': 'x'}, started=running, **options)

    def test_sequence_numbers_grow_and_the_result_is_read_back(self):
        self.publish()
        self.start_pob()
        self.assertEqual(self.send()['seq'], 1)
        self.assertEqual(self.send()['seq'], 2)
        self.assertEqual([c['seq'] for c in self.pob.seen], [1, 2])
        self.assertEqual(self.pob.seen[0]['protocol'], 'pob-command/1')
        self.assertEqual([p.name for p in self.commands.iterdir()], [f'{PID}.result.json'])  # command taken

    def test_a_result_left_from_an_earlier_command_is_not_taken(self):
        self.publish()
        self.commands.mkdir()
        (self.commands / f'{PID}.result.json').write_text('{"seq": 5, "status": "exists"}', encoding='utf-8')
        self.start_pob()
        result = self.send()
        self.assertEqual((result['seq'], result['status']), (6, 'added'))

    def test_pob_not_running_or_without_a_build(self):
        with self.assertRaises(pob_command.CommandError) as caught:
            self.send()
        self.assertEqual((caught.exception.code, str(caught.exception)), ('pob-not-running', 'PoB 未运行，无法加入'))
        self.publish(closed=True)
        with self.assertRaises(pob_command.CommandError) as caught:
            self.send()
        self.assertEqual(caught.exception.code, 'pob-no-build')

    def test_dead_pob_snapshot_counts_as_not_running(self):
        self.publish()
        with self.assertRaises(pob_command.CommandError) as caught:
            pob_command.find_pob(self.user, started=lambda pid: None)
        self.assertEqual(caught.exception.code, 'pob-not-running')
        self.assertEqual(list(self.live.iterdir()), [])  # the stale snapshot is removed

    def test_pob_exiting_while_waiting_withdraws_the_command(self):
        self.publish()
        target = pob_command.find_pob(self.user, started=running)
        alive = iter([0.0, 0.0, None])
        with self.assertRaises(pob_command.CommandError) as caught:
            pob_command.send(target, {'command': 'add-item'}, started=lambda pid: next(alive))
        self.assertEqual(caught.exception.code, 'pob-not-running')
        self.assertFalse((self.commands / f'{PID}.json').exists())

    def test_pob_not_answering_withdraws_the_command(self):
        self.publish()
        with self.assertRaises(pob_command.CommandError) as caught:
            self.send(timeout=0.2)
        self.assertEqual(caught.exception.code, 'pob-timeout')
        self.assertFalse((self.commands / f'{PID}.json').exists())

    def backend_add(self, status):
        self.publish()
        self.start_pob(status=status)
        # The fake PoB's pid is this test process, which really runs.
        return Backend(None, pob_user_dir=self.user).add_to_pob({'item_text': ARMOUR, 'game': {'language': 'cmn-Hant'}})

    def test_backend_sends_english_text_with_the_chinese_rare_name(self):
        result = self.backend_add('added')
        self.assertEqual((result['status'], result['message']), ('added', f'已加入 PoB：{RARE_NAME}'))
        text = self.pob.seen[0]['item_text']
        self.assertEqual(text.split('\n')[:4], ['Item Class: Body Armours', 'Rarity: Rare', RARE_NAME,
                                                'Runeforged Shrouded Mail'])
        self.assertNotIn('Unnamed Rare', text)

    def test_backend_reports_an_item_already_in_the_list(self):
        self.assertEqual(self.backend_add('exists')['message'], f'已存在：{RARE_NAME}')

    def test_backend_refuses_items_that_cannot_be_equipped(self):
        with self.assertRaises(BackendError) as caught:
            Backend(None).add_to_pob({'item_text': 'Item Class: Stackable Currency\nRarity: Currency\nOrb of Nothing'})
        self.assertEqual(caught.exception.code, 'not-equippable')

    def test_placeholder_is_only_replaced_for_rare_names(self):
        ring = parse_params({'item_text': 'Rarity: Rare\nP02 Ring\nRuby Ring\n+50 to maximum Life'})
        self.assertEqual(pob_item_text(ring), ring['text'])


@unittest.skipUnless(live_engine() and (live_engine() / 'src/Modules/AssistantCommands.lua').exists(),
                     'POB_ENGINE is not our PoB branch with U06, or luajit missing')
class RealAddTests(unittest.TestCase):
    """A headless PoB from our branch takes the command the real application would."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.user = Path(self.directory.name)
        self.build = self.user / 'Builds/Saved.xml'
        self.build.parent.mkdir()
        shutil.copyfile(REAL / 'build.xml', self.build)
        self.before = self.build.read_bytes()
        self.live = self.user / pob_live.LIVE_DIR
        self.commands = self.user / pob_command.COMMAND_DIR
        self.live.mkdir(parents=True)
        self.commands.mkdir()
        env = dict(os.environ, LUA_PATH='../runtime/lua/?.lua;../runtime/lua/?/init.lua;;',
                   LUA_CPATH=f'{LINUX_RUNTIME}/?.so;;')
        self.pob = subprocess.Popen([str(LINUX_RUNTIME / 'LuaJIT/src/luajit'), str(ROOT / 'scripts/pob_command_driver.lua'),
                                     str(self.live) + '/', str(self.commands) + '/', str(self.build)],
                                    cwd=live_engine() / 'src', env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL, text=True, encoding='utf-8')
        self.assertEqual(self.pob.stdout.readline(), '@@ready\n')
        self.backend = Backend(None, pob_user_dir=self.user)

    def tearDown(self):
        self.pob.kill()
        self.pob.wait()
        self.pob.stdin.close()
        self.pob.stdout.close()
        self.directory.cleanup()

    def command(self, line):
        self.pob.stdin.write(line + '\n')
        self.pob.stdin.flush()
        reply = self.pob.stdout.readline()
        if reply != '@@done\n':
            self.assertEqual(self.pob.stdout.readline(), '@@done\n')
            return json.loads(reply)
        return None

    def add(self):
        """Run add-to-pob while the headless PoB keeps running frames."""
        outcome = {}

        def call():
            try:
                outcome['result'] = self.backend.add_to_pob({'item_text': ARMOUR, 'game': {'language': 'cmn-Hant'}})
            except BackendError as error:
                outcome['error'] = error
        thread = threading.Thread(target=call)
        thread.start()
        while thread.is_alive():
            self.command('frame')
            time.sleep(0.05)
        if 'error' in outcome:
            raise outcome['error']
        return outcome['result']

    def test_add_lists_the_item_unequipped_unsaved_and_selected(self):
        before = self.command('items')
        self.assertFalse(before['itemsModified'])
        result = self.add()
        self.assertEqual((result['status'], result['message']), ('added', f'已加入 PoB：{RARE_NAME}'))
        self.command('frame')  # the build counts unsaved edits at the start of a frame
        after = self.command('items')
        self.assertEqual(len(after['items']), len(before['items']) + 1)
        added = after['items'][-1]
        self.assertEqual((added['id'], added['title'], added['baseName'], added['equipped']),
                         (result['item_id'], RARE_NAME, 'Runeforged Shrouded Mail', False))
        self.assertIn('Runic Ward: 118', added['raw'])  # P05's English text
        self.assertEqual([i['equipped'] for i in after['items'][:-1]], [i['equipped'] for i in before['items']])
        self.assertTrue(after['itemsModified'])
        self.assertTrue(after['unsaved'])
        self.assertEqual(after['selected'], added['id'])
        # The same item again: reported, not added twice.
        again = self.add()
        self.assertEqual((again['status'], again['message'], again['item_id']), ('exists', f'已存在：{RARE_NAME}', added['id']))
        self.assertEqual(len(self.command('items')['items']), len(after['items']))
        self.assertEqual(self.build.read_bytes(), self.before)
        self.assertEqual(sorted(p.name for p in self.commands.iterdir()), [f'{self.pob.pid}.result.json'])

    def test_closed_build_and_exited_pob(self):
        self.command('close')
        with self.assertRaises(BackendError) as caught:
            self.add()
        self.assertEqual(caught.exception.code, 'pob-no-build')
        self.pob.kill()
        self.pob.wait()
        with self.assertRaises(BackendError) as caught:
            self.backend.add_to_pob({'item_text': ARMOUR})
        self.assertEqual((caught.exception.code, str(caught.exception)), ('pob-not-running', 'PoB 未运行，无法加入'))


if __name__ == '__main__':
    unittest.main()
