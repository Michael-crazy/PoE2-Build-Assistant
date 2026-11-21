"""Resident trial server: protocol and reload with a fake engine, plus the
real pinned engine when available (Linux default runtime or POB_ENGINE)."""
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from pob_current import locate, remap, settings_entry
from pob_server import LINUX_RUNTIME, TrialServer

ROOT = Path(__file__).resolve().parents[1]
REAL = ROOT / 'tests/fixtures/p02/real'
RING = 'Rarity: Rare\nP02 Ring\nRuby Ring\n+50 to maximum Life'
JEWEL = 'Rarity: Magic\nTest Ruby\nRuby\n--------\n+40 to maximum Life\n10% increased Attack Speed'
# Ranger start to its nearest jewel socket (tree 0_3).
SOCKET_PATH = '50459,13828,1140,15507,48401,61312,21280,28050,63888,35901,60735'
FIREBALL = ('gemId="Metadata/Items/Gem/SkillGemFireball" level="20" nameSpec="Fireball" quality="0" '
            'skillId="FireballPlayer" variantId="Fireball"')
UNEARTH = ('gemId="Metadata/Items/Gem/SkillGemUnearth" level="20" nameSpec="Unearth" quality="0" skillId="UnearthPlayer" '
           'variantId="Unearth" skillMinion="UnearthBoneConstruct" skillMinionCalcs="UnearthBoneConstruct" '
           'skillMinionSkill="1" skillMinionSkillCalcs="1"')


class FakeEngine:
    def __init__(self):
        self.calls = []

    def call(self, request):
        self.calls.append(request)
        if request['cmd'] == 'load':
            if 'broken' in request['build_xml']:
                return {'ok': False, 'error': 'build load failed\ntraceback'}
            return {'ok': True, 'build_name': request['name'], 'baseline': {}}
        slots = [request['slot']] if 'slot' in request else ['Ring 1', 'Ring 2']
        return {'ok': True, 'slots': [{'slot': slot} for slot in slots]}


class TrialServerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.build = self.root / 'a.xml'
        self.build.write_text('<PathOfBuilding2/>', encoding='utf-8')
        self.engine = FakeEngine()

    def tearDown(self):
        self.directory.cleanup()

    def loads(self):
        return [c for c in self.engine.calls if c['cmd'] == 'load']

    def test_evaluate_reloads_only_when_build_file_changes(self):
        server = TrialServer(self.engine, self.build)
        first = server.handle({'cmd': 'evaluate', 'item_text': RING})
        second = server.handle({'cmd': 'evaluate', 'item_text': RING})
        self.assertEqual((first['reloaded'], second['reloaded']), (True, False))
        self.assertEqual([s['slot'] for s in first['slots']], ['Ring 1', 'Ring 2'])
        self.build.write_text('<PathOfBuilding2 changed="1"/>', encoding='utf-8')
        stamp = self.build.stat().st_mtime_ns + 2_000_000_000
        os.utime(self.build, ns=(stamp, stamp))
        third = server.handle({'cmd': 'evaluate', 'item_text': RING, 'slot': 'Ring 2'})
        self.assertTrue(third['reloaded'])
        self.assertEqual(len(self.loads()), 2)
        self.assertEqual(self.engine.calls[-1], {'cmd': 'evaluate', 'item_text': RING, 'slot': 'Ring 2'})
        self.assertEqual(third['build']['path'], str(self.build.resolve()))

    def test_failed_reload_keeps_retrying(self):
        server = TrialServer(self.engine, self.build)
        server.handle({'cmd': 'load', 'build': str(self.build)})
        self.build.write_text('<broken', encoding='utf-8')
        os.utime(self.build, ns=(1, 1))
        with self.assertRaisesRegex(ValueError, '^build load failed$'):
            server.handle({'cmd': 'evaluate', 'item_text': RING})
        with self.assertRaises(ValueError):
            server.handle({'cmd': 'evaluate', 'item_text': RING})
        self.assertEqual(len(self.loads()), 3)

    def test_auto_mode_follows_located_build(self):
        other = self.root / 'b.xml'
        other.write_text('<PathOfBuilding2/>', encoding='utf-8')
        current = {'path': str(self.build), 'source': 'settings'}
        server = TrialServer(self.engine, locator=lambda _: dict(current), live_finder=lambda _: None)
        loaded = server.handle({'cmd': 'load'})
        self.assertEqual((loaded['path'], loaded['source']), (str(self.build.resolve()), 'settings'))
        current.update(path=str(other), source='window')
        result = server.handle({'cmd': 'evaluate', 'item_text': RING})
        self.assertTrue(result['reloaded'])
        self.assertEqual(result['build']['name'], 'b')

    def test_mistranslated_resistance_lines_are_corrected_for_the_engine_only(self):
        # B02: the user's imported cos-Tencent build had these lines; PoB fixes fire at -10%.
        raw = ('<Item>\nFire Resistance is -10%\r\n{crafted}Cold Resistance is +43%\nLightning Resistance is 33%\n'
               '+20% to Chaos Resistance\nChaos Resistance is Zero\n</Item>')
        self.build.write_bytes(raw.encode('utf-8'))
        server = TrialServer(self.engine, self.build)
        result = server.handle({'cmd': 'evaluate', 'item_text': RING})
        self.assertEqual(result['build']['corrected_lines'], 3)
        self.assertEqual(self.loads()[0]['build_xml'],
                         '<Item>\n-10% to Fire Resistance\r\n{crafted}+43% to Cold Resistance\n'
                         '+33% to Lightning Resistance\n+20% to Chaos Resistance\nChaos Resistance is Zero\n</Item>')
        self.assertEqual(self.build.read_bytes().decode('utf-8'), raw)

    def test_serve_json_lines(self):
        server = TrialServer(self.engine, self.build)
        lines = [json.dumps({'id': 1, 'cmd': 'load', 'build': str(self.build)}) + '\n', '\n', 'not json\n', '[1]\n',
                 '{"id": "x", "cmd": "evaluate", "item_text": " "}\n',
                 '{"id": 2, "cmd": "nope"}\n',
                 json.dumps({'id': 3, 'cmd': 'evaluate', 'item_text': RING}) + '\n']
        out = io.StringIO()
        server.serve(lines, out)
        responses = [json.loads(line) for line in out.getvalue().splitlines()]
        self.assertEqual([(r['id'], r['ok']) for r in responses],
                         [(1, True), (None, False), (None, False), ('x', False), (2, False), (3, True)])
        self.assertIn('elapsed_ms', responses[-1])


class LocateTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        (self.root / 'Builds/sub').mkdir(parents=True)
        self.saved = self.root / 'Builds/sub/Saved.xml'
        self.saved.write_text('<PathOfBuilding2/>', encoding='utf-8')
        (self.root / 'Builds/Open.xml').write_text('<PathOfBuilding2/>', encoding='utf-8')
        # PoB folder moved since the path was written.
        (self.root / 'Settings.xml').write_text(
            '<PathOfBuilding2><Mode mode="BUILD"><Arg string="C:/Old Place/PoB/Builds/sub/Saved.xml"/>'
            '<Arg string="Saved"/></Mode><Misc showTitlebarName="true"/></PathOfBuilding2>', encoding='utf-8')

    def tearDown(self):
        self.directory.cleanup()

    def test_settings_path_is_remapped_into_builds_dir(self):
        path, name, builds = settings_entry(self.root)
        self.assertEqual((name, builds), ('Saved', self.root / 'Builds'))
        self.assertEqual(remap(path, builds), self.saved)
        self.assertEqual(locate(self.root, windows=[]),
                         {'path': str(self.saved), 'name': 'Saved', 'source': 'settings'})

    def test_open_window_wins_over_settings(self):
        windows = [('Open (Ranger) - Path of Building (PoE2)', None)]
        self.assertEqual(locate(self.root, windows=windows)['path'], str(self.root / 'Builds/Open.xml'))
        unnamed = [('Path of Building (PoE2)', None)]
        self.assertEqual(locate(self.root, windows=unnamed)['source'], 'settings')

    def test_missing_build_is_an_error(self):
        self.saved.unlink()
        with self.assertRaises(ValueError):
            locate(self.root, windows=[])


def real_engine():
    engine = Path(os.environ.get('POB_ENGINE', '/tmp/poe2-pob-source'))
    if sys.platform != 'win32' and not (LINUX_RUNTIME / 'LuaJIT/src/libluajit.so').exists():
        return None
    # A repository checkout/export, or the release package's PoB/ (R02: scripts next to the runtime).
    return engine if any((engine / name).exists() for name in ('src/HeadlessWrapper.lua', 'HeadlessWrapper.lua')) else None


@unittest.skipUnless(real_engine(), 'pinned PoB engine or LuaJIT runtime unavailable')
class RealEngineTests(unittest.TestCase):
    """One server process for the class; matches the frozen one-shot trial."""

    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.build = Path(cls.directory.name) / 'build.xml'
        shutil.copyfile(REAL / 'build.xml', cls.build)
        cls.process = subprocess.Popen(
            [sys.executable, '-B', str(ROOT / 'scripts/pob_server.py'), '--engine', str(real_engine()),
             '--build', str(cls.build)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding='utf-8')
        cls.ready = json.loads(cls.process.stdout.readline())

    @classmethod
    def tearDownClass(cls):
        cls.process.stdin.close()
        cls.process.wait(timeout=30)
        cls.process.stdout.close()
        cls.directory.cleanup()

    def ask(self, **request):
        self.process.stdin.write(json.dumps(request) + '\n')
        self.process.stdin.flush()
        return json.loads(self.process.stdout.readline())

    def test_matches_one_shot_trial(self):
        self.assertEqual(self.ready['event'], 'ready', self.ready)
        expected = json.loads((REAL / 'expected.json').read_text(encoding='utf-8'))
        for name in ('wand', 'bow'):
            case = expected['cases'][name]
            result = self.ask(cmd='evaluate', item_text=(REAL / case['item']).read_text(encoding='utf-8'))
            self.assertTrue(result['ok'], result)
            [row] = result['slots']
            self.assertEqual(row['slot'], case['slot'])
            for key in ('CombinedDPS', 'Life', 'EnergyShield'):
                self.assertEqual(result['baseline'][key], expected['baseline'][key])
                self.assertEqual(row['metrics'][key], case['replacement'][key])
            self.assertEqual(row['displaced'], [] if name == 'wand' else
                             [{'slot': 'Weapon 2', 'name': 'P02 Focus, Hallowed Focus', 'title': 'P02 Focus',
                               'base': 'Hallowed Focus', 'rarity': 'RARE'}])
            self.assertEqual(result['skill'], {'dps_source': 'player', 'main_skill': 'Fireball', 'minion_skill': None})
            self.assertEqual(row['metrics']['DPS'], row['metrics']['CombinedDPS'])
        rejected = self.ask(cmd='evaluate', slot='Weapon 1 Swap', item_text=(REAL / 'bow.txt').read_text())
        self.assertFalse(rejected['ok'])

    def test_minion_main_skill_reports_minion_dps(self):
        minion = Path(self.directory.name) / 'minion.xml'
        text = (REAL / 'build.xml').read_text(encoding='utf-8')
        self.assertIn(FIREBALL, text)
        minion.write_text(text.replace(FIREBALL, UNEARTH), encoding='utf-8')
        try:
            loaded = self.ask(cmd='load', build=str(minion))
            self.assertTrue(loaded['ok'], loaded)
            skill = loaded['skill']
            self.assertEqual((skill['dps_source'], skill['main_skill']), ('minion', 'Unearth'), skill)
            self.assertIsInstance(skill['minion_skill'], str)
            result = self.ask(cmd='evaluate', item_text=RING)
            self.assertGreater(result['baseline']['DPS'], 0)
            self.assertNotEqual(result['baseline']['DPS'], result['baseline']['CombinedDPS'])
            self.assertIn('DPS', result['slots'][0]['delta'])
        finally:
            self.assertTrue(self.ask(cmd='load', build=str(self.build))['ok'])

    def test_jewel_goes_only_to_allocated_sockets(self):
        # B01: headless PoB never refreshed socket visibility, so jewels were
        # trialled in unallocated sockets that CalcSetup ignores (all zero).
        self.assertFalse(self.ask(cmd='evaluate', item_text=JEWEL)['ok'])
        socketed = Path(self.directory.name) / 'socket.xml'
        text = (REAL / 'build.xml').read_text(encoding='utf-8')
        self.assertIn('nodes="50459"', text)
        socketed.write_text(text.replace('nodes="50459"', f'nodes="{SOCKET_PATH}"'), encoding='utf-8')
        try:
            self.assertTrue(self.ask(cmd='load', build=str(socketed))['ok'])
            result = self.ask(cmd='evaluate', item_text=JEWEL)
            [row] = result['slots']
            self.assertEqual((row['slot'], row['replaced']), ('Jewel 60735', None))
            self.assertEqual(row['delta']['Life'], 42)
        finally:
            self.assertTrue(self.ask(cmd='load', build=str(self.build))['ok'])

    def test_ring_goes_to_both_active_ring_slots(self):
        result = self.ask(cmd='evaluate', item_text=RING)
        self.assertEqual([row['slot'] for row in result['slots']], ['Ring 1', 'Ring 2'])
        for row in result['slots']:
            self.assertIsNone(row['replaced'])
            self.assertGreater(row['delta']['Life'], 0)
            self.assertEqual(set(row['metrics']['attributes']), {'Str', 'Dex', 'Int'})
        self.assertFalse(self.ask(cmd='evaluate', slot='Ring 3', item_text=RING)['ok'])

    def test_reload_after_build_edit(self):
        self.assertFalse(self.ask(cmd='evaluate', item_text=RING)['reloaded'])
        text = self.build.read_text(encoding='utf-8')
        self.build.write_text(text.replace('+100 to maximum Energy Shield', '+120 to maximum Energy Shield', 1)
                              if '+100 to maximum Energy Shield' in text else text + '\n', encoding='utf-8')
        stamp = self.build.stat().st_mtime_ns + 2_000_000_000
        os.utime(self.build, ns=(stamp, stamp))
        result = self.ask(cmd='evaluate', item_text=RING)
        self.assertTrue(result['reloaded'], result)
        self.assertFalse(self.ask(cmd='evaluate', item_text=RING)['reloaded'])


if __name__ == '__main__':
    unittest.main()
