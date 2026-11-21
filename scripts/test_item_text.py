"""Item text conversion against the PoE2DB tables (no PoB needed)."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import item_text
from item_text import match_line, parse_item

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/p05"
ENTRY = Path(__file__).with_name("assistant.py")


def read(path):
    return (FIXTURES / path).read_text(encoding="utf-8")


def ids(result):
    return {line["line"]: line["ids"] for line in result["lines"] if line["ids"]}


class TencentAdvancedTests(unittest.TestCase):
    """Real Tencent client Ctrl+Alt+C copy (Simplified Chinese)."""

    @classmethod
    def setUpClass(cls):
        cls.result = parse_item(read("real/tencent-gloves-advanced.txt"))

    def test_english_text(self):
        self.assertEqual(self.result["language"], "zh_hans")
        self.assertEqual((self.result["item_class"], self.result["base"]), ("Gloves", "Grim Gloves"))
        self.assertEqual(self.result["text"], read("real/tencent-gloves-advanced.en.txt"))

    def test_affix_ids_match_engine(self):
        # Same IDs the pinned PoB engine assigns (checked against a real engine run).
        found = ids(self.result)
        self.assertEqual([found[n] for n in (19, 21, 23, 25, 27, 29)], [
            ["mod:AddedColdDamage6"], ["mod:LocalIncreasedEnergyShieldPercent7_"],
            ["mod:LocalIncreasedEnergyShield6"], ["mod:FireResist7"],
            ["mod:ManaGainedFromEnemyDeath7"], ["mod:EnergyShieldRechargeRate4"]])
        self.assertEqual(found[15], ["socketable:Metadata/Items/SoulCores/RuneSpecial15"])
        self.assertEqual(found[16], ["socketable:Metadata/Items/SoulCores/RuneWardSpecial15"])

    def test_header_uses_affix_name_to_pick_energy_shield_over_armour(self):
        # "坚不可摧的" is both Unassailable (ES%) and Impregnable (Armour%).
        lines = {line["line"]: line for line in self.result["lines"]}
        self.assertEqual(lines[20]["english"], '{ Prefix Modifier "Unassailable" (Tier: 1) }')
        self.assertEqual(lines[22]["english"], '{ Desecrated Prefix Modifier "Pulsing" (Tier: 2) }')

    def test_trailer_and_rare_name(self):
        # "引路石掉落" is a marker on every rarity (P05b), not only after the status line.
        self.assertEqual(self.result["unrecognized"], [])
        self.assertEqual((self.result["lines"][-1]["kind"], self.result["lines"][-1]["status"]),
                         ("marker", "dropped"))
        self.assertTrue(self.result["text"].endswith("--------\nCorrupted\n"))
        # PoB turns non-ASCII into "?", so the Chinese rare name becomes a placeholder.
        name = self.result["lines"][2]
        self.assertEqual((name["status"], name["english"]), ("placeholder", "Unnamed Rare"))

    def test_english_round_trip_keeps_ids(self):
        again = parse_item(self.result["text"])
        self.assertEqual(again["language"], "en")
        self.assertEqual(again["text"], self.result["text"])
        self.assertEqual(ids(again), ids(self.result))


class LanguageTests(unittest.TestCase):
    def test_traditional_plain_copy(self):
        # Synthetic: built from the PoE2DB zh_hant templates (no real sample yet).
        result = parse_item(read("synthetic/zh-hant-ring.txt"))
        self.assertEqual(result["language"], "zh_hant")
        self.assertEqual(result["unrecognized"], [])
        self.assertIn("+28% to Fire Resistance (implicit)\n", result["text"])
        self.assertIn("Adds 12 to 19 Fire damage to Attacks\n", result["text"])
        self.assertIn("Requires: Level 46\n", result["text"])
        self.assertTrue(result["text"].endswith("Corrupted\n"))
        self.assertEqual(ids(result)[10], ["implicit:Ruby_Ring#0"])
        self.assertEqual(ids(result)[13], ["mod:AddedFireDamage5"])

    def test_english_magic_copy(self):
        result = parse_item(read("synthetic/en-magic-ring.txt"))
        self.assertEqual(result["language"], "en")
        self.assertEqual(result["text"], read("synthetic/en-magic-ring.txt"))
        self.assertEqual(ids(result)[11], ["mod:AddedFireDamage1"])
        self.assertEqual(ids(result)[12], ["mod:ColdResist1"])

    def test_simplified_magic_name(self):
        result = parse_item("物品类别: 戒指\n稀有度: 魔法\n冒烟的红玉戒指海豹之\n--------\n"
                            "攻击附加 6 - 11 基础火焰伤害\n冰霜抗性 +8%\n")
        self.assertEqual(result["text"].splitlines()[:3],
                         ["Item Class: Rings", "Rarity: Magic", "Smoking Ruby Ring of the Seal"])
        self.assertEqual(result["unrecognized"], [])

    def test_simplified_unique(self):
        result = parse_item("物品类别: 戒指\n稀有度: 传奇\n幽暗之语\n锻铁戒指\n--------\n"
                            "攻击附加 1 - 4 物理伤害 (implicit)\n--------\n生命每秒再生 2\n"
                            "击中有 10% 的几率威吓敌人 4 秒\n")
        self.assertEqual(result["unique"], "Blackheart")
        self.assertEqual(result["text"].splitlines()[2:4], ["Blackheart", "Iron Ring"])
        self.assertEqual(ids(result)[6], ["implicit:Iron_Ring#0"])
        self.assertIn("10% chance to Intimidate Enemies for 4 seconds on Hit", result["text"])


class TencentUniqueTests(unittest.TestCase):
    """Real Tencent copy of Reverie on the 1.0 Runemastered base, corrupted."""

    @classmethod
    def setUpClass(cls):
        cls.result = parse_item(read("real/tencent-unique-body-armour-advanced.txt"))
        cls.lines = cls.result["text"].splitlines()

    def test_unique_found_despite_new_base(self):
        self.assertEqual((self.result["unique"], self.result["base"]), ("Reverie", "Runemastered Shaman Mantle"))
        self.assertEqual(self.lines[2:4], ["Reverie", "Runemastered Shaman Mantle"])
        self.assertEqual(self.result["unrecognized"], [])

    def test_corruption_bonded_granted_and_unscalable(self):
        index = self.lines.index("{ Corruption Enhancement }")
        self.assertEqual(self.lines[index + 1], "16(10-20)% of Damage taken Recouped as Life")
        self.assertEqual(ids(self.result)[18], ["mod:CorruptionDamageTakenGainedAsLife1"])
        self.assertIn("Bonded: +5% to Quality of all Skills (rune)", self.lines)
        self.assertIn("Grants Skill: Level 19 Rite of Restoration", self.lines)
        self.assertIn("Recovery from your Life Flasks cannot be applied to anything other than you"
                      " — Unscalable Value", self.lines)
        self.assertIn("-10% to Fire Resistance", self.lines)  # negative value on a signed template

    def test_flavour_and_signature_dropped(self):
        flavour = [line for line in self.result["lines"] if line["kind"] == "flavour"]
        self.assertEqual([line["line"] for line in flavour], [40, 41, 42, 43])
        self.assertNotIn("赛尔塔斯", self.result["text"])
        self.assertEqual(self.lines[-3:], ["42(60-40)% less Life Flask Recovery", "--------", "Corrupted"])

    def test_granted_skill_from_gem_table_and_unknown_unique(self):
        result = parse_item("物品类别: 法杖\n稀有度: 稀有\n怒火 灵唤\n某基底\n--------\n获得技能: 等级 18 威能法印\n")
        self.assertIn("Grants Skill: Level 18 Sigil of Power", result["text"])
        self.assertEqual(result["text"].splitlines()[2], "Unnamed Rare")
        unknown = parse_item("物品类别: 护甲\n稀有度: 传奇\n不存在的传奇\n萨满斗篷\n--------\n无法使用生命药剂\n")
        self.assertEqual(unknown["text"].splitlines()[2:4], ["Unknown Unique", "Shaman Mantle"])
        self.assertEqual(unknown["unrecognized"][0]["line"], 3)
        self.assertIn("Cannot use Life Flasks", unknown["text"])


class InternationalTraditionalTests(unittest.TestCase):
    """Real international client (Traditional Chinese) advanced copies."""

    def test_body_armour(self):
        result = parse_item(read("real/intl-zh-hant-body-armour-advanced.txt"))
        self.assertEqual((result["language"], result["base"]), ("zh_hant", "Runeforged Shrouded Mail"))
        self.assertEqual(result["unrecognized"], [])
        lines = result["text"].splitlines()
        self.assertIn("Runic Ward: 118 (augmented)", lines)
        self.assertIn("Requires: Level 70, 67 Str, 67 Dex", lines)
        # "{ 固定詞綴 }" is the implicit header; its line is the base implicit.
        self.assertEqual(lines[lines.index("{ Implicit Modifier }") + 1], "+25(20-25)% to Fire Resistance")
        self.assertEqual(ids(result)[20], ["implicit:Runeforged_Shrouded_Mail#0"])
        self.assertEqual(ids(result)[23], ["mod:LocalIncreasedArmourAndEvasionAndBase5"])
        self.assertTrue(all(i.startswith("socketable:Metadata/Items/SoulCores/RuneLife") for i in ids(result)[17]))

    def test_jewel_description_is_dropped(self):
        result = parse_item(read("real/intl-zh-hant-jewel-advanced.txt"))
        self.assertEqual(result["unrecognized"], [])
        self.assertEqual(result["lines"][-1]["kind"], "description")
        self.assertEqual(result["lines"][-1]["status"], "dropped")
        self.assertTrue(result["text"].endswith("17(10-20)% increased Critical Damage Bonus for Attack Damage\n"))
        self.assertEqual(ids(result)[9], ["mod:JewelCrossbowDamage"])

    def test_redemption_unique(self):
        # Synthetic: written from the crossbow unique table (no original copy).
        result = parse_item(read("synthetic/zh-hant-redemption-advanced.txt"))
        self.assertEqual((result["unique"], result["base"]), ("Redemption", "Trarthan Cannon"))
        self.assertEqual(result["unrecognized"], [])
        lines = result["text"].splitlines()
        self.assertIn("Physical Damage: 336-777 (augmented)", lines)
        self.assertIn("Cannot load or fire Ammunition — Unscalable Value", lines)
        self.assertIn("Hits with this Weapon have no Critical Damage Bonus — Unscalable Value", lines)
        self.assertIn("Gain 1 Explosive Rhythm every 3(2-3) times you use a Grenade Skill", lines)
        self.assertNotIn("敬請期待", result["text"])
        self.assertEqual(result["lines"][-1]["kind"], "flavour")
        self.assertEqual(lines[-1], "Remove all Explosive Rhythm on reaching 10 to gain Explosive Fervour"
                                    " for 10 Seconds")

    def test_simplified_description_and_flavour(self):
        jewel = parse_item("物品类别: 珠宝\n稀有度: 稀有\n某名\n绿玉\n--------\n"
                           "--------\n放置于天赋树的珠宝插槽中以生效。右键点击以移出插槽。\n", "zh_hans")
        self.assertEqual(jewel["lines"][-1]["status"], "dropped")
        unique = parse_item("物品类别: 十字弓\n稀有度: 传奇\n救赎\n特拉珊火炮\n--------\n"
                            "使用该武器击中没有暴击伤害加成 — 无法变动的值\n--------\n敬请期待\n")
        self.assertEqual(unique["unrecognized"], [])
        self.assertEqual(unique["text"].splitlines()[-1],
                         "Hits with this Weapon have no Critical Damage Bonus — Unscalable Value")

    def test_flavour_needs_unique_and_no_numbers(self):
        rare = parse_item("物品类别: 戒指\n稀有度: 稀有\n某名\n红玉戒指\n--------\n冰霜抗性 +8%\n--------\n敬请期待\n")
        self.assertEqual([u["text"] for u in rare["unrecognized"]], ["敬请期待"])


class PriceNoteTests(unittest.TestCase):
    RING = {"en": "Item Class: Rings\nRarity: Rare\nSome Name\nRuby Ring\n--------\n+8% to Cold Resistance\n",
            "zh_hant": "物品種類: 戒指\n稀有度: 稀有\n某名\n紅玉戒指\n--------\n+8% 冰冷抗性\n",
            "zh_hans": "物品类别: 戒指\n稀有度: 稀有\n某名\n红玉戒指\n--------\n冰霜抗性 +8%\n"}
    LABELS = {"en": "Note", "zh_hant": "備註", "zh_hans": "备注"}

    def test_market_spear_price_is_stripped(self):
        result = parse_item(read("real/intl-zh-hant-market-spear.txt"))
        self.assertEqual(result["unrecognized"], [])
        self.assertEqual(result["price"], {"kind": "buyout", "amount": 1, "currency": "transmute",
                                           "currency_name": "蛻變石"})
        self.assertNotIn("~b/o", result["text"])
        self.assertFalse(result["text"].rstrip().endswith("--------"))

    def test_buyout_and_price_in_every_language(self):
        names = {"en": "Divine Orb", "zh_hant": "神聖石", "zh_hans": "神圣石"}
        for lang, ring in self.RING.items():
            for note, kind in (("~b/o", "buyout"), ("~price", "price")):
                with self.subTest(lang=lang, note=note):
                    text = f"{ring}--------\n{self.LABELS[lang]}: {note} 1.5 divine\n"
                    result = parse_item(text)
                    self.assertEqual(result["language"], lang)
                    self.assertEqual(result["price"], {"kind": kind, "amount": 1.5, "currency": "divine",
                                                       "currency_name": names[lang]})
                    self.assertEqual(result["unrecognized"], [])
                    self.assertEqual(result["text"], parse_item(ring)["text"])

    def test_fraction_amount_and_unknown_currency(self):
        result = parse_item(self.RING["zh_hans"] + "--------\n备注: ~price 1/2 exalted\n")
        self.assertEqual(result["price"]["amount"], 0.5)
        unknown = parse_item(self.RING["en"] + "--------\nNote: ~b/o 3 shiny-pebble\n")
        self.assertEqual(unknown["price"], {"kind": "buyout", "amount": 3, "currency": "shiny-pebble",
                                            "currency_name": None})
        self.assertNotIn("shiny-pebble", unknown["text"])
        self.assertIsNone(parse_item(self.RING["en"])["price"])


class MatchTests(unittest.TestCase):
    def test_ranges_pick_tier(self):
        english, found, status, _ = match_line("+44 (42-47) 能量护盾上限", [], "zh_hans", {"class": "Gloves"})
        self.assertEqual((english, found, status),
                         ("+44(42-47) to maximum Energy Shield", ["mod:LocalIncreasedEnergyShield6"], "matched"))

    def test_header_generation_type_picks_suffix(self):
        header = {"gen": "2", "name": "扫荡之"}
        _, found, status, _ = match_line("物品稀有度提高 12%", [], "zh_hans", {"class": "Rings"}, header)
        self.assertEqual((found, status), (["mod:ItemFoundRarityIncrease2"], "matched"))

    def test_literal_number_must_match(self):
        english, _, status, _ = match_line("固有的怒火损失延迟 2 秒开始", [], "zh_hans", {"class": "Helmets"})
        self.assertEqual((english, status), ("Inherent Rage loss starts 2 seconds later", "matched"))

    def test_unknown_and_misfit_lines(self):
        self.assertEqual(match_line("完全虚构的属性 12", [], "zh_hans", {})[2:],
                         ("unrecognized", "无对应模板"))
        self.assertEqual(match_line("+44 (42-47) 能量护盾上限 +3", [], "zh_hans", {})[2], "unrecognized")


class AmbiguityTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        data = Path(self.directory.name)
        mod = {"classes": ["Rings"], "essences": [], "family": [], "generation_type": "1", "level": 1,
               "ranges": [[1, 10]], "zh_hans": ["测试伤害提高 #%"], "zh_hant": ["增加#%測試傷害"]}
        (data / "mods.json").write_text(json.dumps({"mods": {
            "A": {**mod, "en": ["#% increased Test Damage"]},
            "B": {**mod, "en": ["#% more Test Damage"]}}}), encoding="utf-8")
        (data / "rings.json").write_text(json.dumps({"metadata": {"item_class": "Rings"}}), encoding="utf-8")
        item_text._TERMS = item_text.Terms(data)

    def tearDown(self):
        item_text._TERMS = None
        self.directory.cleanup()

    def test_different_english_is_not_guessed(self):
        result = parse_item("物品类别: 戒指\n稀有度: 稀有\n某名\n某基底\n--------\n测试伤害提高 5%\n", "zh_hans")
        line = result["lines"][-1]
        self.assertEqual((line["status"], line["english"], line["ids"]), ("ambiguous", "测试伤害提高 5%", ["mod:A", "mod:B"]))
        self.assertIn("#% increased", line["note"].replace("5%", "#%"))
        self.assertEqual([u["line"] for u in result["unrecognized"]], [1, 4, 6])  # class, base, mod


class TencentSecondRoundTests(unittest.TestCase):
    """P05b: findings 14-18 (real Tencent copies) and the lines U07 could not convert."""

    def test_rare_crossbow_base_header_grenade_cooldown_and_marker(self):
        result = parse_item(read("real/tencent-rare-crossbow-grenade-cooldown.txt"))
        self.assertEqual(result["unrecognized"], [])
        lines = {line["line"]: line for line in result["lines"]}
        # "{ 基底属性 }" heads Trarthan Cannon's own line, matched as its base implicit.
        self.assertEqual(lines[19]["english"], "{ Implicit Modifier }")
        self.assertEqual(lines[20]["english"], "Cannot load or fire Ammunition — Unscalable Value")
        self.assertEqual(lines[20]["ids"], ["implicit:Trarthan_Cannon#0"])
        # The suffix only spawns on the "cannon" base: PoE2DB lists it on the Trarthan_Cannon page.
        self.assertEqual(lines[32]["english"], "33(33-40)% increased Cooldown Recovery Rate for Grenade Skills")
        self.assertEqual(lines[32]["ids"], ["mod:GrenadeSkillCooldownRecovery6"])
        self.assertEqual(lines[31]["english"], '{ Suffix Modifier "of Alacrity" (Tier: 1) }')
        self.assertEqual((lines[34]["kind"], lines[34]["status"]), ("marker", "dropped"))
        self.assertNotIn("引路石", result["text"])

    def test_every_real_sample_is_recognised(self):
        for path in sorted((FIXTURES / "real").glob("*.txt")):
            if not path.name.endswith(".en.txt"):
                with self.subTest(path.name):
                    self.assertEqual(parse_item(path.read_text(encoding="utf-8-sig"))["unrecognized"], [])

    def test_traditional_bonded_singular_implicit_and_leading_level(self):
        # V10 #20: international crossbow, the three lines rebuilt from the user's screenshot.
        result = parse_item(read("synthetic/intl-zh-hant-crossbow-bonded-desecrated.txt"))
        self.assertEqual(result["unrecognized"], [])
        lines = {line["text"]: line for line in result["lines"]}
        bonded = lines["命定: 增加60%完全破甲的效果 (rune)"]
        self.assertEqual(bonded["english"], "Bonded: 60% increased effect of Fully Broken Armour (rune)")
        self.assertTrue(all(i.startswith("socketable:") for i in bonded["ids"]))
        implicit = lines["擲彈技能發射額外一個投射物 (implicit)"]
        self.assertEqual(implicit["english"], "Grenade Skills Fire an additional Projectile (implicit)")
        self.assertEqual(implicit["ids"], ["implicit:Siege_Crossbow#0"])
        level = lines["+5全部投射物技能等級 (desecrated)"]
        self.assertEqual(level["english"], "+5 to Level of all Projectile Skills (desecrated)")
        # The word-order variant only applies to a lone leading number.
        self.assertEqual(match_line("5全部投射物技能等級", [], "zh_hant", {})[2], "matched")
        self.assertEqual(match_line("5全部投射物技能等級3", [], "zh_hant", {})[2], "unrecognized")

    def test_sanctified_status_and_fractured_marker(self):
        # V10 #25: Tencent "圣化物品" (Sanctified) and "分裂之物" (Fractured Item) lines.
        result = parse_item(read("synthetic/tencent-staff-sanctified-fractured.txt"))
        self.assertEqual(result["unrecognized"], [])
        lines = {line["text"]: line for line in result["lines"]}
        self.assertEqual((lines["圣化物品"]["kind"], lines["圣化物品"]["english"]), ("status", "Sanctified"))
        self.assertEqual((lines["分裂之物"]["kind"], lines["分裂之物"]["status"]), ("marker", "dropped"))
        self.assertTrue(result["text"].endswith("--------\nSanctified\n"))
        self.assertNotIn("分裂", result["text"])

    def test_rune_forged_note_is_dropped(self):
        text = "稀有度: 稀有\n仇恨 圣曲\n鸣谐长杖\n--------\n由奥杜尔之热情铸造 (rune)\n所有法术技能等级 +1 (rune)\n"
        result = parse_item(text, "zh_hans")
        self.assertEqual(result["unrecognized"], [])
        note = next(line for line in result["lines"] if line["text"].startswith("由"))
        self.assertEqual((note["kind"], note["status"]), ("marker", "dropped"))
        self.assertIn("+1 to Level of all Spell Skills (rune)\n", result["text"])
        # Only a known rune name makes it a note; anything else stays unrecognised.
        self.assertEqual(len(parse_item(text.replace("奥杜尔之热情", "不存在的符文"), "zh_hans")["unrecognized"]), 1)

    def test_skill_name_slot(self):
        text = "稀有度: 传奇\n信念的棱镜\n宝钻\n--------\n所有烈焰爆破技能等级 +2\n--------\n被腐化\n"
        result = parse_item(text, "zh_hans")
        self.assertEqual(result["unrecognized"], [])
        self.assertEqual(result["unique"], "Prism_of_Belief")
        self.assertIn("+2 to Level of all Flameblast Skills\n", result["text"])
        # A name that is in no PoE2DB gem table is reported, not guessed.
        missing = parse_item(text.replace("烈焰爆破", "不存在的技能"), "zh_hans")["unrecognized"]
        self.assertEqual([line["note"] for line in missing], ["名称不在编年史宝石表/天赋表中：不存在的技能"])

    def test_passive_name_slot_and_joined_lines(self):
        # 无根之源 (From Nothing) is in PoE2DB 1.0; its tw page writes the two lines as one, so it
        # is kept for Simplified and English only. PoB reads the two lines as one.
        text = ("稀有度: 传奇\n无根之源\n宝钻\n--------\n苦痛灵曲范围内的天赋可以在\n"
                "未连结至天赋树的情况下配置\n--------\n被腐化\n")
        result = parse_item(text, "zh_hans")
        self.assertEqual(result["unrecognized"], [])
        self.assertEqual(result["text"].splitlines()[1:5], [
            "From Nothing", "Diamond", "--------",
            "Passives in Radius of Pain Attunement can be Allocated without being connected to your tree"])
        second = result["lines"][-3]
        self.assertEqual((second["kind"], second["status"]), ("joined", "dropped"))

    def test_megalomaniac_allocates_slot(self):
        result = parse_item("稀有度: 传奇\n妄想症\n宝钻\n--------\n配置 焚化\n", "zh_hans")
        self.assertEqual(result["unrecognized"], [])
        self.assertIn("Allocates Immolation\n", result["text"])


class CommandTests(unittest.TestCase):
    def run_cli(self, *args, stdin=None):
        return subprocess.run([sys.executable, "-B", str(ENTRY), "parse-item", *args], input=stdin,
                              capture_output=True, timeout=60)

    def test_file_and_stdin(self):
        path = FIXTURES / "real/tencent-gloves-advanced.txt"
        from_file = self.run_cli(str(path))
        from_stdin = self.run_cli(stdin=path.read_bytes())
        for result in (from_file, from_stdin):
            self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
            output = json.loads(result.stdout.decode("utf-8"))
            self.assertEqual(output["text"], read("real/tencent-gloves-advanced.en.txt"))
            self.assertEqual(output["unrecognized"], [])

    def test_empty_input_fails_without_output(self):
        result = self.run_cli(stdin=b"\n \n")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, b"")
        self.assertIn("装备文本为空", result.stderr.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
