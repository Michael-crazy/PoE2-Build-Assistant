import contextlib
import io
import json
import shutil
from pathlib import Path
import tempfile
import unittest

import pob_localization as loc

GEMS_LUA = '''return {
\t["Metadata/Items/Gems/SkillGemIceNova"] = {
\t\tname = "Ice Nova",
\t\tbaseTypeName = "Ice Nova",
\t\tgameId = "Metadata/Items/Gem/SkillGemIceNova",
\t\tvariantId = "IceNova",
\t\tgrantedEffectId = "IceNovaPlayer",
\t},
\t["Metadata/Items/Gems/SkillGemDreadBanner"] = {
\t\tname = "Dread Banner",
\t\tgameId = "Metadata/Items/Gem/SkillGemDreadBanner",
\t\tgrantedEffectId = "DreadBannerPlayer",
\t},
}
'''
MOD_ITEM = '''return {
\t["Strength1"] = { type = "Suffix", affix = "of the Brute", "+(5-8) to Strength", statOrder = { 992 }, level = 1 },
\t["Chain1"] = { type = "Suffix", affix = "of Chains", "Attacks Chain an additional time", statOrder = { 5 }, level = 1 },
\t["OldMod1"] = { type = "Prefix", affix = "Old", "(1-2)% increased Old", statOrder = { 6 }, level = 1 },
}
'''
EMPTY_MODS = "return {\n}\n"
BASES = 'itemBases["Stellar Amulet"] = {\n\ttype = "Amulet",\n}\nitemBases["Fishing Rod"] = {\n}\n'
UNIQUES = '''return {
[[
Astramentis
Stellar Amulet
Implicits: 1
{tags:attribute}+(5-7) to all Attributes
{tags:physical,attack}-4 Physical Damage taken from Attack Hits
]],[[
Thunderfist
Leather Gloves
]],
}
'''
TERMS = {
    "skill_gems": {"gems": {
        "Ice_Nova": {"en": "Ice Nova", "zh_hans": "冰霜新星", "zh_hant": "冰霜新星",
                     "pob": {"gameId": "Metadata/Items/Gem/SkillGemIceNova"}},
        "Abyssal_Pact": {"en": "Abyssal Pact", "zh_hans": "深渊契约", "zh_hant": "深淵冥約"}}},
    "amulets": {
        "base_types": {"Stellar_Amulet": {"en": "Stellar Amulet", "zh_hans": "星辉项链", "zh_hant": "恆星項鍊"}},
        "uniques": {"Astramentis": {
            "en": "Astramentis", "zh_hans": "均衡之符", "zh_hant": "均衡之符",
            "implicits": [{"en": "+# to all Attributes", "zh_hans": "+# 全属性", "zh_hant": "+#點全部能力值"}],
            "explicits": [{"en": "# Physical Damage taken from Attack Hits", "zh_hans": "攻击击中承受 # 物理伤害",
                           "zh_hant": "#受到的攻擊擊中物理傷害"}]}}},
    "gloves": {"uniques": {"Thunderfist": {"en": "Thunderfist", "zh_hans": "轰天雷", "zh_hant": "雷拳"}}},
    "rings": {"uniques": {"Thunderfist": {"en": "Thunderfist", "zh_hans": "轰天雷", "zh_hant": "轟天雷"}}},
    "mods": {"mods": {
        "Strength1": {"en": ["+# to Strength"], "zh_hans": ["+# 力量"], "zh_hant": ["+#點力量"],
                      "affix": {"en": "of the Brute", "zh_hans": "野蛮之", "zh_hant": "野蠻之"}},
        "Chain1": {"en": ["Attacks Chain # additional times"], "zh_hans": ["攻击额外连锁 # 次"],
                   "zh_hant": ["攻擊額外連鎖 # 次"]},
        "NewIn10": {"en": ["# new"], "zh_hans": ["# 新"], "zh_hant": ["# 新"]}}},
}

TREE_FIXTURE = Path(__file__).resolve().parent.parent / "tests/fixtures/p03/tree"


class BuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        data = root / "pob" / "src" / "Data"
        (data / "Bases").mkdir(parents=True)
        (data / "Uniques").mkdir()
        (data / "Gems.lua").write_text(GEMS_LUA, encoding="utf-8")
        for name in loc.MOD_FILES:
            (data / f"{name}.lua").write_text(MOD_ITEM if name == "ModItem" else EMPTY_MODS, encoding="utf-8")
        (data / "Bases" / "amulet.lua").write_text(BASES, encoding="utf-8")
        (data / "Uniques" / "amulet.lua").write_text(UNIQUES, encoding="utf-8")
        terms = root / "terms"
        terms.mkdir()
        for name, table in TERMS.items():
            (terms / f"{name}.json").write_text(json.dumps(table, ensure_ascii=False), encoding="utf-8")
        shutil.copytree(TREE_FIXTURE / "pob" / "src", data.parent, dirs_exist_ok=True)
        cls.out = root / "out"
        with contextlib.redirect_stdout(io.StringIO()):
            loc.main(["--terms", str(terms), "--pob", str(root / "pob"), "--pob-commit", "abc1234",
                      "--out", str(cls.out), "--tree", str(TREE_FIXTURE / "poe2db")])

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def read(self, name):
        return json.loads((self.out / f"{name}.json").read_text(encoding="utf-8"))

    def test_gems_keyed_by_pob_key_and_granted_effect(self):
        gems = self.read("gems")
        self.assertEqual(gems["gems"]["Metadata/Items/Gems/SkillGemIceNova"]["zh_hans"], "冰霜新星")
        self.assertEqual(gems["skills"]["IceNovaPlayer"]["zh_hant"], "冰霜新星")
        self.assertNotIn("Metadata/Items/Gems/SkillGemDreadBanner", gems["gems"])

    def test_mod_templates_only_when_pob_template_agrees(self):
        mods = self.read("mods")["mods"]
        self.assertEqual(mods["Strength1"]["lines"], [{"key": "# to strength", "zh_hans": "+# 力量",
                                                       "zh_hant": "+#點力量"}])
        self.assertNotIn("Chain1", mods)
        self.assertEqual(self.read("mods")["lines"]["# to strength"]["zh_hant"], "+#點力量")

    def test_bases_and_uniques_by_english_name(self):
        self.assertEqual(self.read("bases")["bases"]["Stellar Amulet"]["zh_hans"], "星辉项链")
        uniques = self.read("uniques")["uniques"]
        self.assertEqual(uniques["Astramentis"]["lines"]["# to all attributes"]["zh_hans"], "+# 全属性")
        self.assertNotIn("Thunderfist", uniques)

    def test_coverage_counts(self):
        cov = self.read("coverage")
        self.assertEqual(cov["pob_commit"], "abc1234")
        self.assertEqual({k: cov["gems"][k] for k in ("pob_total", "matched", "missing", "ambiguous", "poe2db_only")},
                         {"pob_total": 2, "matched": 1, "missing": 1, "ambiguous": 0, "poe2db_only": 1})
        self.assertEqual({k: cov["mods"][k] for k in ("pob_total", "matched", "missing", "ambiguous", "poe2db_only")},
                         {"pob_total": 3, "matched": 1, "missing": 1, "ambiguous": 1, "poe2db_only": 1})
        self.assertEqual((cov["bases"]["matched"], cov["bases"]["missing_names"]), (1, ["Fishing Rod"]))
        self.assertEqual(cov["uniques"]["ambiguous"], 1)
        self.assertIn("gems", (self.out / "coverage.txt").read_text(encoding="utf-8"))
        self.assertEqual((cov["passives"]["pob_tree_version"], cov["passives"]["matched"]), ("0_5", 7))
        self.assertEqual(self.read("passives")["nodes"]["4"]["zh_hans"], "感电几率")


class PassiveTreeTests(unittest.TestCase):
    """Fixture: 14 nodes cut from PoB 601768b tree.lua 0_5 and the PoE2DB tree 4.5 cache; node 52 removed
    from the PoE2DB side, node 70000 is PoE2DB-only. Option hosts 59 (overlay only), 722 (attributes),
    1143 (Druid) and 2516 (Abyssal Lich) are PoB-only; PoE2DB 51690/20303 (Life Regeneration, two zh
    names) and 38776 (Dexterity) supply option text."""

    @classmethod
    def setUpClass(cls):
        nodes, ascendancies = loc.load_pob_tree(TREE_FIXTURE / "pob", loc.pob_tree_version(TREE_FIXTURE / "pob"))
        cls.table, cls.report = loc.build_passives(nodes, ascendancies, loc.load_poe2db_tree(TREE_FIXTURE / "poe2db"))
        cls.nodes = cls.table["nodes"]

    def test_names_and_lines_by_skill_id(self):
        node = self.nodes["18684"]
        self.assertEqual((node["kind"], node["zh_hans"], node["zh_hant"]), ("keystone", "火之化身", "火之化身"))
        self.assertEqual(node["lines"][0], {"key": "#% of damage converted to fire damage",
                                            "zh_hans": "#% 的伤害转化为火焰伤害", "zh_hant": "#%的傷害轉換成火焰傷害"})
        self.assertEqual(self.nodes["240"]["kind"], "mastery")
        self.assertEqual(self.nodes["2491"]["zh_hans"], "珠宝插槽")

    def test_reordered_values_carry_order(self):
        line = self.nodes["3281"]["lines"][0]
        self.assertEqual(line["order"], {"zh_hans": [1, 0], "zh_hant": [1, 0]})
        self.assertEqual(loc.localize_line("2% increased Spell Damage per 10 Strength", line["zh_hans"],
                                           line["order"]["zh_hans"]), "每 10 点力量会使法术伤害提高 2%")
        self.assertNotIn("zh_hant", self.nodes["516"]["lines"][0].get("order", {}))

    def test_version_differences_stay_english(self):
        self.assertNotIn("zh_hans", self.nodes["9994"])             # renamed in PoE2DB
        self.assertEqual(self.nodes["11335"]["lines"][0]["zh_hans"], "赋予 # 天赋点数")  # "Point" vs "Points"
        self.assertEqual(self.nodes["14226"]["lines"], [None, None])  # wrapped stat, zh moves the number
        self.assertNotIn("52", self.nodes)

    def test_coverage(self):
        r = self.report
        self.assertEqual((r["pob_total"], r["matched"], r["poe2db_only"]), (14, 7, 4))
        self.assertEqual(r["reasons"], {"name_differs": 1, "not_in_poe2db": 5, "zh_numbers_differ": 1})
        self.assertEqual(self.table["ascendancies"]["Invoker"], {"zh_hans": "祈求者", "zh_hant": "祈靈者"})

    def test_node_options_by_name_and_line(self):
        options = self.table["node_options"]
        self.assertEqual(options["hosts"], {"722": {"1": "26297", "2": "14927", "3": "57022"},
                                            "1143": {"Druid": "57726"}, "2516": {"Abyssal Lich": "11705"}})
        dex = options["options"]["14927"]
        self.assertEqual((dex["zh_hans"], dex["lines"][0]["zh_hans"]), ("敏捷", "# 敏捷"))
        regen = options["options"]["57726"]  # PoE2DB names differ; the line comes from a 0.5% node
        self.assertNotIn("zh_hans", regen)
        self.assertEqual(loc.localize_line("Regenerate 0.2% of maximum Life per second", regen["lines"][0]["zh_hans"]),
                         "生命每秒再生 0.2%")
        self.assertEqual(options["options"]["11705"]["lines"], [None])

    def test_node_option_coverage_lists_unjoined(self):
        o = self.report["options"]
        self.assertEqual({k: o[k] for k in ("hosts", "option_slots", "overlay_only", "pob_total", "matched",
                                            "lines_total", "lines_matched")},
                         {"hosts": 4, "option_slots": 5, "overlay_only": 1, "pob_total": 5, "matched": 1,
                          "lines_total": 5, "lines_matched": 2})
        self.assertEqual(o["unjoined"]["57726"], {"en": "Life Regeneration", "problems": ["name_ambiguous"], "lines": []})
        self.assertEqual(o["unjoined"]["11705"]["problems"], ["name_not_in_poe2db", "lines_unjoined"])


class LooseLineTests(unittest.TestCase):
    """P10: PoB number words, PoE2DB plurals and bullets."""

    def test_loose_key(self):
        self.assertEqual(loc.loose_key("Grenade Skills Fire an additional Projectile"),
                         loc.loose_key("Grenade Skills Fire 1 additional Projectiles"))
        self.assertEqual(loc.loose_key("1 Helmet socket"), loc.loose_key("\u2022 1 Helmet socket"))
        self.assertEqual(loc.loose_key("+1 Charm Slot"), "# charm slot")

    def test_word_number_line_gets_literal_zh(self):
        self.assertEqual(loc._loose_template("Grenade Skills Fire an additional Projectile",
                                             "Grenade Skills Fire 1 additional Projectiles", "榴弹技能发射 1 个额外投射物"),
                         ("榴弹技能发射 1 个额外投射物", None))
        self.assertEqual(loc._loose_template("1 Helmet socket", "\u2022 1 Helmet socket", "\u2022 1 个头盔插槽"),
                         ("# 个头盔插槽", None))
        # a number word that is not the PoE2DB number, or zh numbers that are not the en numbers, stay unjoined
        self.assertIsNone(loc._loose_template("Skills fire two additional Projectiles", "Skills fire 1 additional Projectiles",
                                              "技能额外发射 1 个投射物"))
        self.assertIsNone(loc._loose_template("Skills fire an additional Projectile", "Skills fire 1 additional Projectiles",
                                              "技能额外发射 2 个投射物"))

    def test_number_words_stay_literal(self):
        en = "15% increased Melee Damage if you've dealt a Projectile Attack Hit in the past eight seconds"
        template, order = loc._zh_template(en, "若你在过去 8 秒内造成过投射物攻击击中，近战伤害提高 15%")
        self.assertEqual((template, order), ("若你在过去 8 秒内造成过投射物攻击击中，近战伤害提高 #%", None))
        self.assertEqual(loc.localize_line(en.replace("15%", "30%"), template), "若你在过去 8 秒内造成过投射物攻击击中，近战伤害提高 30%")
        self.assertIsNone(loc._zh_template("Every five Rage grants 2% increased Damage", "每 6 点怒火使伤害提高 2%"))

    def test_class_names_join_by_ascendancy_ids(self):
        db = {lang: {"classes": [{"name": name, "ascendancies": [{"id": "Warrior1"}, {"id": "Warrior2"}]}]}
              for lang, name in (("en", "Warrior"), ("zh_hans", "战士"), ("zh_hant", "戰士"))}
        table, report = loc.build_classes({"Warrior": ["Warrior1"], "Witch": ["Witch1"]}, db)
        self.assertEqual(table, {"Warrior": {"zh_hans": "战士", "zh_hant": "戰士"}})
        self.assertEqual(report, {"pob_total": 2, "matched": 1, "unjoined": ["Witch"]})


class LocalizeLineTests(unittest.TestCase):
    def test_values_fill_template_and_keep_meaningful_signs(self):
        self.assertEqual(loc.localize_line("+7 to Strength", "+# 力量"), "+7 力量")
        self.assertEqual(loc.localize_line("-4 Physical Damage taken from Attack Hits", "攻击击中承受 # 物理伤害"),
                         "攻击击中承受 -4 物理伤害")
        self.assertEqual(loc.localize_line("+(5-8) to Strength", "+# 力量"), "+(5-8) 力量")

    def test_value_count_mismatch_keeps_english(self):
        self.assertEqual(loc.localize_line("Attacks Chain an additional time", "攻击额外连锁 # 次"),
                         "Attacks Chain an additional time")


if __name__ == "__main__":
    unittest.main()
