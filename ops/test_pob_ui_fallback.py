"""Tests for ops/pob_ui_fallback.py (P10b) and, when a PoB tree and LuaJIT are at hand, the runtime lookup.

The runtime test needs POB_ENGINE=<PoB tree with src/Modules/AssistantUiText.lua> (as rebase_check sets
it) and the P02 LuaJIT runtime; it is skipped otherwise.
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import pob_ui_fallback as gen

LUAJIT = Path.home() / ".local/state/poe2-assistant/p02-runtime/LuaJIT/src/luajit"


def entry(en, zh, status="ok", source="poecharm"):
    return {"en": en, "key": " ".join(gen.COLOUR.sub("", gen.SPEC.sub("{#}", en).replace("%%", "%")).split())
            if gen.placeholders(en) else gen.normalize(en), "zh": zh, "status": status, "source": source}


class TemplateTests(unittest.TestCase):
    def test_pattern_escapes_and_captures(self):
        self.assertEqual(gen.lua_pattern("= %.1f ^8per second"), "^= (.-) %^8per second$")
        self.assertEqual(gen.lua_pattern("%d%% over %d seconds"), "^(.-)%% over (.-) seconds$")

    def test_replacement_orders(self):
        self.assertEqual(gen.replacement("武器组 {1} 还有 {0} 点", 2), "武器组 %2 还有 %1 点")
        self.assertEqual(gen.replacement("保留: ^7%s%% 精魂", 1), "保留: ^7%1%% 精魂")
        self.assertEqual(gen.replacement("{0}%，持续 {1} 秒", 2), "%1%%，持续 %2 秒")
        self.assertIsNone(gen.replacement("只有 {0}", 2))

    def test_recolour(self):
        self.assertEqual(gen.recolour("= %.1f ^8per second", "= {0} 每秒"), "= {0} ^8每秒")
        self.assertEqual(gen.recolour("^x7F7F7FEnergy Shield: %s%d", "能量护盾: %s%d"), "^x7F7F7F能量护盾: %s%d")
        self.assertEqual(gen.recolour("^7Text", "^7文字"), "^7文字")

    def test_percent_in_plain_text_is_not_a_value(self):
        self.assertEqual(gen.placeholders("Unnerved enemies take 10% increased Spell Damage."), [])

    def test_too_little_fixed_text(self):
        rules, why = gen.template_rules("%d ^x7F7F7F(%.1fs)", "%d (%.1f 秒)")
        self.assertIsNone(rules)


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.fallback = {"entries": [
            entry("Delete All", "删除全部"),
            entry("Wrath", "雷霆", status="likely_ui"),
            entry("Anywhere", "任意位置", status="likely_ui"),
            entry("Your unreserved Spirit is negative", "你未保留的靈魂為負值", status="manual", source="i18n-zh_TW"),
            entry("Corrupted", "已污染", status="manual"),
            entry("= %.2f ^8casts per second", "= {0} 每秒施放"),
            entry("Bad %d and %d values", "只有 {0}"),
        ]}
        self.overrides = {"english": ["Wrath"], "zh": {"Your unreserved Spirit is negative": "你未保留的精魂为负值",
                                                       "Rune Slot": "符文栏"},
                          "formats": [["Requires Level %s", "需求等级 {0}"]],
                          "plainPatterns": [["^Jewel #(%d+)$", "珠宝 #%1"]]}

    def test_selection(self):
        tables, stats = gen.build(self.fallback, self.overrides)
        exact = tables["exact"]
        self.assertEqual(exact["Delete All"], "删除全部")
        self.assertEqual(exact["Anywhere"], "任意位置")
        self.assertNotIn("Wrath", exact)
        self.assertNotIn("Corrupted", exact)  # manual without a reviewed text stays English
        self.assertEqual(exact["Your unreserved Spirit is negative"], "你未保留的精魂为负值")
        self.assertEqual(exact["Rune Slot"], "符文栏")
        self.assertIn(("^= (.-) %^8casts per second$", "= %1 ^8每秒施放"), tables["formats"])
        self.assertIn(("^Requires Level (.-)$", "需求等级 %1"), tables["formats"])
        self.assertEqual(tables["plainFormats"][0], ("^Jewel #(%d+)$", "珠宝 #%1"))
        self.assertEqual(stats["kept_english"]["likely_ui"], 1)
        self.assertEqual(stats["kept_english"]["manual"], 1)
        self.assertEqual(len(stats["rejected"]), 1)

    def test_traditional_converted_and_manual_checked_against_poe2db(self):
        fallback = {"entries": [
            dict(entry("Your unreserved Spirit is negative now", "你未保留的精魂為負值", status="manual",
                       source="i18n-zh_TW"), review=[{"term": "spirit", "poe2db": "精魂"}]),
            dict(entry("Each stack applies more Evasion Rating to enemies", "每層使敵人閃避提高", status="manual",
                       source="i18n-zh_TW"), review=[{"term": "evasion rating", "poe2db": "闪避值"}]),
            dict(entry("Cobalt Jewel", "钴蓝珠宝", status="manual"), review=[{"term": "cobalt", "poe2db": "钴蓝的"}]),
            dict(entry("Eye of Winter:", "凜冬之眼:", status="manual", source="i18n-zh_TW"),
                 review=[{"term": "eye of winter", "poe2db": "凛冬之眼"}]),
            entry("Delete Folder", "刪除資料夾", source="i18n-zh_TW"),
        ]}
        t2s = {"你未保留的精魂為負值": "你未保留的精魂为负值", "每層使敵人閃避提高": "每层使敌人闪避提高",
               "凜冬之眼:": "凛冬之眼:", "刪除資料夾": "删除文件夹"}
        tables, stats = gen.build(fallback, {}, to_simplified=lambda text: t2s.get(text, text))
        exact = tables["exact"]
        self.assertEqual(exact["Your unreserved Spirit is negative now"], "你未保留的精魂为负值")
        self.assertNotIn("Each stack applies more Evasion Rating to enemies", exact)  # 闪避值 not in the text
        self.assertNotIn("Cobalt Jewel", exact)  # only a word of the name is a PoE2DB term
        self.assertEqual(exact["Eye of Winter:"], "凛冬之眼:")
        self.assertEqual(exact["Delete Folder"], "删除文件夹")
        self.assertEqual(stats["used_by_status"]["manual_auto"], 2)

    def test_untranslated_sources_dropped_and_names_filled(self):
        fallback = {"entries": [
            entry("This multiplies the Damage of a given skill in pvp", "This multiplies the 伤害 of a given skill in pvp"),
            entry("Onslaught is active", "猛攻生效中"),
            entry("Do you have Chaotic Might now?", "你现在有 Chaotic Might 吗？"),
            entry("Average", "平均"),
        ]}
        keywords = {"names": {"Chaotic Might": {"zh_hans": "混沌之力"}, "Rage": {"zh_hans": "怒火"}}}
        overrides = {"zh": {"Enable Chaotic Might": "启用 Chaotic Might 增益"}}
        tables, stats = gen.build(fallback, overrides, keywords=keywords)
        exact = tables["exact"]
        self.assertNotIn("This multiplies the Damage of a given skill in pvp", exact)
        self.assertEqual(stats["kept_english"]["untranslated"], 1)
        self.assertEqual(exact["Do you have Chaotic Might now?"], "你现在有 混沌之力 吗？")
        self.assertEqual(exact["Enable Chaotic Might"], "启用 混沌之力 增益")
        self.assertEqual(exact["Average"], "平均")  # "Rage" inside a word is not a name

    def test_reviewed_names_only_where_poe2db_has_none(self):
        fallback = {"entries": [entry("Do you have Adrenaline and Onslaught now?", "你现在有 Adrenaline 和 Onslaught 吗？")]}
        keywords = {"names": {"Onslaught": {"zh_hans": "猛攻"}}}
        overrides = {"names": {"Adrenaline": {"zh": "肾上腺素", "source": "i18n-zh_CN"},
                               "Onslaught": {"zh": "冲锋", "source": "test"}}}
        tables, _ = gen.build(fallback, overrides, keywords=keywords)
        self.assertEqual(tables["exact"]["Do you have Adrenaline and Onslaught now?"], "你现在有 肾上腺素 和 猛攻 吗？")

    def test_item_class_names(self):
        classes = {"pob": {"Bow": {"en": "Bows", "zh_hans": "弓类"}, "Helmet": {"en": "Helmets", "zh_hans": "头盔"}}}
        tables, _ = gen.build({"entries": []}, {"subTypes": {"Armour": "护甲", "Evasion": "闪避"}}, classes)
        exact = tables["exact"]
        self.assertEqual(exact["Bow"], "弓类")
        self.assertEqual(exact["Bows"], "弓类")
        self.assertEqual(exact["Helmet: Armour/Evasion"], "头盔：护甲/闪避")
        self.assertNotIn("Bow: Armour", exact)

    def test_lua_module_round_trip(self):
        tables, stats = gen.build(self.fallback, self.overrides)
        text = gen.lua_module(tables, stats)
        self.assertIn('["Delete All"] = "删除全部",', text)
        self.assertIn('{ "^Requires Level (.-)$", "需求等级 %1" },', text)
        self.assertEqual(gen.lua_string('a"b\\c\nd'), '"a\\"b\\\\c\\nd"')


@unittest.skipUnless(os.environ.get("POB_ENGINE") and LUAJIT.exists(), "needs POB_ENGINE and the P02 LuaJIT runtime")
class RuntimeTests(unittest.TestCase):
    """AssistantUiText.draw with a generated table: exact, template, colour, multi-line, blank lines."""

    def test_draw(self):
        pob = Path(os.environ["POB_ENGINE"])
        fallback = {"entries": [entry("Delete All", "删除全部"), entry("= %.2f ^8casts per second", "= {0} 每秒施放"),
                                entry("Minion:", "召唤生物：")]}
        overrides = {"formats": [["^x7F7F7FEnergy Shield: %s%d", "能量护盾：{0}{1}"]],
                     "plainPatterns": [["^You do not meet the Strength requirement of (.+)$", "未满足 %1 的力量需求"]]}
        tables, stats = gen.build(fallback, overrides)
        with tempfile.TemporaryDirectory() as tmp:
            mods = Path(tmp) / "Modules"
            mods.mkdir()
            shutil.copy(pob / "src/Modules/AssistantUiText.lua", mods)
            (mods / "AssistantUiFallback.lua").write_text(gen.lua_module(tables, stats), encoding="utf-8")
            (mods / "AssistantConfigText.lua").write_text("return { label = function(t) return t end }\n")
            (mods / "AssistantTerms.lua").write_text(
                "return { baseName = function(t) return t == 'Amber Amulet' and '琥珀项链' or t end }\n")
            script = r'''
function LoadModule(name) return dofile(name .. ".lua") end
local ui = LoadModule("Modules/AssistantUiText")
local cases = {
  { "Delete All", "删除全部" },
  { "^7Delete All", "^7删除全部" },
  { "= 1.25 ^8casts per second", "= 1.25 ^8每秒施放" },
  { "^x7F7F7FEnergy Shield: ^x8888FF120", "^x7F7F7F能量护盾：^x8888FF120" },
  { "You do not meet the Strength requirement of Iron Ring", "未满足 Iron Ring 的力量需求" },
  { "\n^7Minion:", "\n^7召唤生物：" },
  { "Amber Amulet", "琥珀项链" },
  { "Line one\nDelete All", "Line one\n删除全部" },
  { "Something else", "Something else" },
}
for _, c in ipairs(cases) do
  local got = ui.draw(c[1])
  assert(got == c[2], ("%q -> %q, want %q"):format(c[1], got, c[2]))
end
print("ok")
'''
            result = subprocess.run([str(LUAJIT), "-e", script], cwd=tmp, capture_output=True, text=True,
                                    env=dict(os.environ, POE2_ASSISTANT_LOCALE="zh-CN"))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("ok", result.stdout)


if __name__ == "__main__":
    unittest.main()
