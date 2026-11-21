"""B03: PoB's resistance-line correction (src/Modules/AssistantBuildFixes.lua) against the
trial engine's rule (pob_server.correct_build). Both must give the same text and count.

Runs only when POB_ENGINE is a PoB tree that has the module (our patch branch); the pinned
upstream engine has none, so the regular suite skips it. ops/rebase_check.py runs the suite
with the branch tree.
"""
import os
from pathlib import Path
import subprocess
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pob_server import correct_build  # noqa: E402

LUAJIT = Path.home() / '.local/state/poe2-assistant/p02-runtime/LuaJIT/src/luajit'
ENGINE = Path(os.environ.get('POB_ENGINE', '/nonexistent'))
MODULE = ENGINE / 'src/Modules/AssistantBuildFixes.lua'

DRIVER = ('local fixes = dofile(os.getenv("B03_MODULE")) local text = io.read("*a") '
          'local out, count = fixes.correctResistLines(text) io.write(count, "\\n", out)')

# The eight lines in a real Tencent-imported build, as saved on Windows.
B02_LINES = [
    'Fire Resistance is +43%', 'Cold Resistance is +43%', 'Lightning Resistance is +33%',
    'Lightning Resistance is +32%', 'Lightning Resistance is +24%', 'Fire Resistance is -10%',
    'Fire Resistance is +39%', 'Cold Resistance is +40%',
]
B02_TEXT = '<Item id="1">\r\nRarity: RARE\r\n' + ''.join(f'{line}\r\n' for line in B02_LINES) + '</Item>\r\n'

EDGE_LINES = [
    'Lightning Resistance is 33%', '{crafted}Cold Resistance is +43%', '\t\t{tags:x}{range:0.5}Chaos Resistance is -7%',
    'Fire Resistance is +5%  \t', '  Fire Resistance is +5%', 'Chaos Resistance is Zero', '+20% to Chaos Resistance',
    'Fire Resistance is +5', 'Fire Resistance is +5% more', 'Physical Resistance is +5%', 'fire Resistance is +5%',
    'XFire Resistance is +5%', '{crafted} Fire Resistance is +5%', '{unclosed Fire Resistance is +5%',
    'Fire Resistance is ++5%', 'Fire Resistance is +05%', 'Fire  Resistance is +5%', '{a}{b}Lightning Resistance is 0%',
    'Fire Resistance is +5%\r', '', '\r', '   ', 'Cold Resistance is +1%\x0b', 'Fire Resistance is +５%',
    '　Fire Resistance is +5%', '\xa0Fire Resistance is +5%', 'Maximum Fire Resistance is +5%',
]


def run_lua(text):
    done = subprocess.run([str(LUAJIT), '-e', DRIVER], env={**os.environ, 'B03_MODULE': str(MODULE)}, input=text.encode('utf-8'),
                          capture_output=True, check=True)
    count, _, out = done.stdout.decode('utf-8').partition('\n')
    return out, int(count)


@unittest.skipUnless(MODULE.exists() and LUAJIT.exists(), 'POB_ENGINE has no AssistantBuildFixes.lua, or luajit missing')
class ResistFixParityTests(unittest.TestCase):
    def test_b02_sample_lines_match_the_trial_engine(self):
        expected = correct_build(B02_TEXT)
        self.assertEqual(expected[1], 8)
        self.assertIn('-10% to Fire Resistance\r\n', expected[0])
        self.assertEqual(run_lua(B02_TEXT), expected)

    def test_each_edge_line_matches(self):
        for line in EDGE_LINES:
            for end in ('\n', '\r\n', ''):
                text = f'a\n{line}{end}b' if end else f'a\n{line}'
                with self.subTest(line=line, end=end):
                    self.assertEqual(run_lua(text), correct_build(text))

    def test_all_edge_lines_together_match(self):
        text = '\n'.join(B02_LINES + EDGE_LINES) + '\n\n\n'
        lua = run_lua(text)
        self.assertEqual(lua, correct_build(text))
        self.assertGreater(lua[1], 8)


if __name__ == '__main__':
    unittest.main()
