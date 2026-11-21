"""P03 display layer (PoB src/Modules/AssistantTerms.lua) against the Python reference.

Runs only when POB_ENGINE is a PoB tree that has the module (our patch branch); the pinned
upstream engine has none, so the regular suite skips it. ops/rebase_check.py runs the suite
with the branch tree, and ops/check_pob_terms.py does the full headless check on builds.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pob_localization as loc  # noqa: E402
from poe2db_terms import number_key  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
LUAJIT = Path.home() / ".local/state/poe2-assistant/p02-runtime/LuaJIT/src/luajit"
ENGINE = Path(os.environ.get("POB_ENGINE", "/nonexistent"))
MODULE = ENGINE / "src/Modules/AssistantTerms.lua"

LINES = [
    "+7 to Strength", "-4 Physical Damage taken from Attack Hits", "+(5-8) to Strength",
    "(30-60)% increased Melee Damage", "Adds 3 to 5 Physical Damage", "Regenerate 0.2% of maximum Life per second",
    "-10% to Fire Resistance", "2% increased Spell Damage per 10 Strength", "  Gain {0}  Rage  ",
    "(10—20)% increased Armour", "+-5 odd", "Level 20", "+(10-20) to maximum Life",
]
CASES = [
    ("+7 to Strength", "+# 力量", None),
    ("-4 Physical Damage taken from Attack Hits", "攻击击中承受 # 物理伤害", None),
    ("+(5-8) to Strength", "+# 力量", None),
    ("-10% to Fire Resistance", "+#% 火焰抗性", None),
    ("+10% to Fire Resistance", "-#% 火焰抗性", None),
    ("2% increased Spell Damage per 10 Strength", "每 # 点力量会使法术伤害提高 #%", [1, 0]),
    ("Adds 3 to 5 Physical Damage", "附加 # - # 基础物理伤害", None),
    ("Adds 3 to 5 Physical Damage", "附加 # 基础物理伤害", None),
    ("(30-60)% increased Melee Damage", "近战伤害提高 #%", None),
]


@unittest.skipUnless(MODULE.exists() and LUAJIT.exists(), "POB_ENGINE has no AssistantTerms.lua")
class LuaParityTests(unittest.TestCase):
    def lua(self, script):
        prelude = (f"package.path = {json.dumps(str(ENGINE / 'runtime/lua/?.lua'))} .. ';' .. package.path "
                   f"T = dofile({json.dumps(str(MODULE))}) json = require('dkjson')")
        out = subprocess.run([str(LUAJIT), "-e", prelude + " " + script], capture_output=True, text=True,
                             env=dict(os.environ, POE2_ASSISTANT_LOCALE="zh-CN"), check=True)
        return json.loads(out.stdout)

    def test_number_key_matches_python(self):
        got = self.lua(f"local r = {{}} for i, l in ipairs(json.decode({json.dumps(json.dumps(LINES))})) do "
                       "r[i] = T.numberKey(l) end print(json.encode(r))")
        self.assertEqual(got, [number_key(line) for line in LINES])

    def test_fill_matches_python(self):
        cases = [[line, template, order or json.loads("null")] for line, template, order in CASES]
        got = self.lua(f"local r = {{}} for i, c in ipairs(json.decode({json.dumps(json.dumps(cases))}, 1, json.null)) do "
                       "local order = c[3] ~= json.null and c[3] or nil "
                       "r[i] = T.fill(c[1], c[2], order) or c[1] end print(json.encode(r))")
        self.assertEqual(got, [loc.localize_line(line, template, order) for line, template, order in CASES])


class SignTests(unittest.TestCase):
    def test_english_sign_wins_over_template_sign(self):
        self.assertEqual(loc.localize_line("-10% to Fire Resistance", "+#% 火焰抗性"), "-10% 火焰抗性")
        self.assertEqual(loc.localize_line("+10% to Fire Resistance", "-#% 火焰抗性"), "+10% 火焰抗性")
        self.assertEqual(loc.localize_line("10% to Fire Resistance", "+#% 火焰抗性"), "+10% 火焰抗性")


if __name__ == "__main__":
    unittest.main()
