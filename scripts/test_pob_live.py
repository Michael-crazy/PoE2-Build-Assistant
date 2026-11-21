"""U02 bridge: live snapshots of the build open in PoB, their freshness and the
fallback to the build file; plus a headless PoB from our branch publishing an
unsaved edit to the real trial engine (needs POB_ENGINE = the branch tree)."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

import pob_live
from pob_server import LINUX_RUNTIME, TrialServer
from test_pob_server import FakeEngine, REAL, RING, real_engine

ROOT = Path(__file__).resolve().parents[1]


def snapshot(pid, seq, xml='<PathOfBuilding2/>', complete=True, **meta):
    header = {'protocol': 'pob-live/1', 'pid': pid, 'seq': seq, 'revision': 3, 'unsaved': True,
              'path': None, 'name': 'Live', **meta}
    text = f'<!--poe2-assistant-live {json.dumps(header, ensure_ascii=False)}-->\n'
    if not meta.get('closed'):
        text += xml + (f'\n<!--poe2-assistant-live-end {seq}-->\n' if complete else '')
    return text


class LiveFileTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.user = Path(self.directory.name)
        self.live = self.user / pob_live.LIVE_DIR
        self.live.mkdir(parents=True)

    def tearDown(self):
        self.directory.cleanup()

    def write(self, pid, text, age=0):
        path = self.live / f'{pid}.xml'
        path.write_text(text, encoding='utf-8', newline='')
        stamp = time.time() - age
        os.utime(path, (stamp, stamp))
        return path

    def test_read_complete_closed_partial_and_foreign(self):
        path = self.write(7, snapshot(7, 4, '<PathOfBuilding2>\r\n中文\r\n</PathOfBuilding2>', path='C:/b/x.xml'))
        read = pob_live.read_snapshot(path)
        self.assertEqual((read['seq'], read['path'], read['xml']),
                         (4, 'C:/b/x.xml', '<PathOfBuilding2>\r\n中文\r\n</PathOfBuilding2>'))
        self.write(7, snapshot(7, 5, closed=True))
        self.assertIsNone(pob_live.read_snapshot(path)['xml'])
        self.write(7, snapshot(7, 6, complete=False))
        with self.assertRaisesRegex(ValueError, '正在写入'):
            pob_live.read_snapshot(path, attempts=2)
        self.write(7, snapshot(7, 6).replace('-end 6', '-end 5'))  # end line of an older write
        with self.assertRaises(ValueError):
            pob_live.read_snapshot(path, attempts=1)
        self.write(7, '<PathOfBuilding2/>')
        self.assertIsNone(pob_live.read_snapshot(path))

    def test_find_needs_a_running_process_started_before_the_write(self):
        now = time.time()
        running = {11: now - 3600, 12: now - 3600, 13: now}
        self.write(11, snapshot(11, 1), age=60)
        self.write(12, snapshot(12, 9), age=5)
        self.write(13, snapshot(13, 1), age=60)  # pid 13 reused by a process started after the write
        self.write(14, snapshot(14, 1), age=1)  # PoB gone without closing the build
        self.write(15, snapshot(15, 1, closed=True))
        (self.live / 'notes.xml').write_text('x', encoding='utf-8')
        running[15] = now - 3600
        found = pob_live.find([self.user], started=running.get)
        self.assertEqual((found['pid'], found['seq'], found['file']), (12, 9, self.live / '12.xml'))
        self.assertFalse((self.live / '14.xml').exists())
        self.assertTrue((self.live / '13.xml').exists())
        self.assertIsNone(pob_live.find([self.user], started=lambda pid: None))
        self.assertIsNone(pob_live.find([self.user / 'missing'], started=running.get))

    def test_this_process_counts_as_running(self):
        started = pob_live.process_started(os.getpid())
        self.assertIsNotNone(started)
        self.assertLessEqual(started, time.time() + pob_live.START_SLACK)
        self.write(os.getpid(), snapshot(os.getpid(), 1))
        self.assertEqual(pob_live.find([self.user])['pid'], os.getpid())

    def test_live_dirs_from_windows_and_explicit_dir(self):
        portable = self.user / 'PoB'
        (portable / 'src' / pob_live.LIVE_DIR).mkdir(parents=True)
        windows = [('A (Ranger) - Path of Building (PoE2)', portable / 'runtime' / 'Path of Building.exe'),
                   ('Path of Building (PoE2)', None)]
        self.assertEqual(pob_live.live_dirs(self.user, windows), [self.user, portable / 'src'])
        self.assertEqual(pob_live.live_dirs(self.user / 'none', []), [])


class TrialServerLiveTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        self.file = root / 'Saved.xml'
        self.file.write_text('<PathOfBuilding2 file="1"/>', encoding='utf-8')
        self.live = root / '42.xml'
        self.current = None
        self.engine = FakeEngine()
        self.server = TrialServer(self.engine, locator=lambda _: {'path': str(self.file), 'source': 'settings'},
                                  live_finder=lambda _: self.current)

    def tearDown(self):
        self.directory.cleanup()

    def publish(self, seq, xml='<PathOfBuilding2 live="1"/>', **meta):
        self.live.write_text(snapshot(42, seq, xml, **meta), encoding='utf-8')
        self.current = {'file': self.live, 'pid': 42, 'seq': seq, 'mtime_ns': 0}

    def loads(self):
        return [call['build_xml'] for call in self.engine.calls if call['cmd'] == 'load']

    def evaluate(self):
        return self.server.handle({'cmd': 'evaluate', 'item_text': RING})

    def test_live_snapshot_wins_and_reloads_per_sequence(self):
        self.publish(1, path=str(self.file), unsaved=False)
        first = self.evaluate()
        self.assertEqual(first['build'], {'path': str(self.file.resolve()), 'name': 'Live', 'source': 'live',
                                          'unsaved': False, 'corrected_lines': 0})
        self.assertFalse(self.evaluate()['reloaded'])
        self.publish(2, '<PathOfBuilding2 edited="1">\nFire Resistance is -10%\n</PathOfBuilding2>')
        second = self.evaluate()
        self.assertTrue(second['reloaded'])
        self.assertEqual((second['build']['unsaved'], second['build']['path'], second['build']['corrected_lines']),
                         (True, None, 1))
        self.assertEqual(self.loads(), ['<PathOfBuilding2 live="1"/>',
                                        '<PathOfBuilding2 edited="1">\n-10% to Fire Resistance\n</PathOfBuilding2>'])

    def test_falls_back_to_the_file_when_pob_is_gone_or_closed_the_build(self):
        self.publish(1)
        self.evaluate()
        self.current = None  # PoB exited or closed the build
        result = self.evaluate()
        self.assertEqual((result['reloaded'], result['build']['source']), (True, 'settings'))
        self.assertEqual(self.loads()[-1], '<PathOfBuilding2 file="1"/>')
        self.publish(2, closed=True)  # closed between the scan and the read
        with self.assertRaisesRegex(ValueError, '关闭'):
            self.evaluate()
        self.publish(3)
        self.assertEqual(self.evaluate()['build']['source'], 'live')

    def test_newer_write_after_the_scan_is_not_loaded_twice(self):
        self.publish(1)
        self.current = dict(self.current)
        self.live.write_text(snapshot(42, 2, '<PathOfBuilding2 v="2"/>'), encoding='utf-8')
        self.evaluate()  # scanned seq 1, read seq 2
        self.current['seq'] = 2
        self.assertFalse(self.evaluate()['reloaded'])
        self.assertEqual(self.loads(), ['<PathOfBuilding2 v="2"/>'])

    def test_explicit_build_ignores_live(self):
        self.publish(1)
        server = TrialServer(self.engine, self.file, live_finder=lambda _: self.fail('live consulted'))
        self.assertEqual(server.handle({'cmd': 'evaluate', 'item_text': RING})['build']['source'], 'explicit')


def live_engine():
    """The branch tree (POB_ENGINE) with the U02 hook and the Linux luajit binary."""
    engine = real_engine()
    luajit = LINUX_RUNTIME / 'LuaJIT/src/luajit'
    if engine and (engine / 'src/Modules/AssistantLiveBuild.lua').exists() and luajit.exists():
        return engine
    return None


@unittest.skipUnless(live_engine(), 'POB_ENGINE is not our PoB branch with U02, or luajit missing')
class RealLiveBuildTests(unittest.TestCase):
    """A headless PoB edits the build without saving; the trial server follows it."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.user = Path(self.directory.name)
        self.build = self.user / 'Builds/Saved.xml'
        self.build.parent.mkdir()
        shutil.copyfile(REAL / 'build.xml', self.build)
        (self.user / 'Settings.xml').write_text(
            f'<PathOfBuilding2><Mode mode="BUILD"><Arg string="{self.build}"/><Arg string="Saved"/></Mode>'
            '</PathOfBuilding2>', encoding='utf-8')
        self.live = self.user / pob_live.LIVE_DIR
        self.live.mkdir(parents=True)
        self.wand = (REAL / 'wand.txt').read_text(encoding='utf-8')
        self.before = self.build.read_bytes()
        self.server = subprocess.Popen(
            [sys.executable, '-B', str(ROOT / 'scripts/pob_server.py'), '--engine', str(live_engine()),
             '--pob-user-dir', str(self.user)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding='utf-8')
        self.ready = json.loads(self.server.stdout.readline())
        self.pob = None

    def tearDown(self):
        self.stop_pob()
        self.server.stdin.close()
        self.server.wait(timeout=30)
        self.server.stdout.close()
        self.directory.cleanup()

    def stop_pob(self):
        if self.pob:
            self.pob.kill()
            self.pob.wait()
            self.pob.stdin.close()
            self.pob.stdout.close()
            self.pob = None

    def start_pob(self):
        engine = live_engine()
        runtime = LINUX_RUNTIME
        env = dict(os.environ, LUA_PATH='../runtime/lua/?.lua;../runtime/lua/?/init.lua;;',
                   LUA_CPATH=f'{runtime}/?.so;;')
        self.pob = subprocess.Popen([str(runtime / 'LuaJIT/src/luajit'), str(ROOT / 'scripts/pob_live_driver.lua'),
                                     str(self.live) + '/', str(self.build)],
                                    cwd=engine / 'src', env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL, text=True, encoding='utf-8')
        self.assertEqual(self.pob.stdout.readline(), '@@ready\n')

    def pob_command(self, line):
        self.pob.stdin.write(line + '\n')
        self.pob.stdin.flush()
        self.assertEqual(self.pob.stdout.readline(), '@@done\n')

    def evaluate(self):
        self.server.stdin.write(json.dumps({'cmd': 'evaluate', 'item_text': self.wand}) + '\n')
        self.server.stdin.flush()
        result = json.loads(self.server.stdout.readline())
        self.assertTrue(result['ok'], result)
        return result

    def test_unsaved_edit_changes_the_evaluation_and_closing_falls_back(self):
        self.assertEqual(self.ready['build']['source'], 'settings', self.ready)
        saved = self.evaluate()
        self.start_pob()
        same = self.evaluate()  # PoB's own serialisation of the unchanged build
        # Loaded from XML text, the headless build has no file, so PoB counts it unsaved.
        self.assertEqual((same['reloaded'], same['build']['source'], same['build']['path']), (True, 'live', None))
        self.assertEqual((same['baseline'], same['slots']), (saved['baseline'], saved['slots']))
        self.pob_command('level 90')
        edited = self.evaluate()
        self.assertEqual((edited['reloaded'], edited['build']['unsaved']), (True, True))
        self.assertGreater(edited['baseline']['Life'], saved['baseline']['Life'])
        self.assertFalse(self.evaluate()['reloaded'])
        self.pob_command('close')
        closed = self.evaluate()
        self.assertEqual((closed['build']['source'], closed['baseline']), ('settings', saved['baseline']))
        self.assertEqual(self.build.read_bytes(), self.before)

    def test_pob_exit_falls_back_to_the_file(self):
        saved = self.evaluate()
        self.start_pob()
        self.pob_command('level 90')
        self.assertEqual(self.evaluate()['build']['source'], 'live')
        self.stop_pob()
        after = self.evaluate()
        self.assertEqual((after['build']['source'], after['baseline']), ('settings', saved['baseline']))
        self.assertEqual(list(self.live.glob('*.xml')), [])


if __name__ == '__main__':
    unittest.main()
