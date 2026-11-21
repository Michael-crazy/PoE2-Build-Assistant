import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest

import poe2db_terms as terms

FIXTURE = Path(__file__).resolve().parent.parent / "tests/fixtures/d01"


def load(side):
    return (FIXTURE / side / "Rings.html").read_text(encoding="utf-8")


class ModTextTests(unittest.TestCase):
    def test_values_become_placeholders_with_ranges(self):
        lines, ranges = terms.parse_mod_text(
            "<span class='mod-value'>+(5<span class=\"ndash\">—</span>8)</span> to "
            "<a data-keyword=\"Strength\" href=\"Strength\">Strength</a>")
        self.assertEqual(lines, ["+# to Strength"])
        self.assertEqual(ranges, [[5.0, 8.0]])

    def test_br_splits_lines_and_fixed_values_count(self):
        lines, ranges = terms.parse_mod_text(
            "<span class='mod-value'>(8<span class=\"ndash\">—</span>12)</span>% increased Mana Regeneration Rate"
            "<br><span class='mod-value'>5</span>% increased Light Radius")
        self.assertEqual(lines, ["#% increased Mana Regeneration Rate", "#% increased Light Radius"])
        self.assertEqual(ranges, [[8.0, 12.0], [5.0, 5.0]])

    def test_number_key_matches_pob_and_poecharm_forms(self):
        key = terms.number_key("+# to maximum Life")
        self.assertEqual(terms.number_key("+(10-19) to maximum Life"), key)
        self.assertEqual(terms.number_key("{0} to maximum Life"), key)


class FixturePairingTests(unittest.TestCase):
    def setUp(self):
        self.us = terms.extract_modsview(load("us"))
        self.cn = terms.extract_modsview(load("cn"))

    def test_mods_pair_by_section_order(self):
        mods, mismatches = terms.pair_mods(self.us, self.cn)
        self.assertEqual(mismatches, [])
        self.assertEqual(mods["IncreasedLife1"]["zh_hans"], ["+# 生命上限"])
        self.assertEqual(mods["IncreasedLife1"]["affix"]["en"], "Hale")
        self.assertEqual(mods["CorruptionChaosResistance1"]["generation_type"], "5")
        self.assertTrue(any(len(m["en"]) == 2 for m in mods.values()))

    def test_essence_pick_one_line_kept_on_essence(self):
        mods, _ = terms.pair_mods(self.us, self.cn)
        strength = mods["Strength2"]
        self.assertEqual(strength["en"], ["+# to Strength"])
        self.assertEqual(strength["essences"][0]["line"]["en"], ["+# to Strength, Dexterity or Intelligence"])
        self.assertIn("essence", mods["IncreasedLife2"]["sections"])

    def test_pick_one_essence_line_never_becomes_main_text(self):
        us, cn = copy.deepcopy(self.us), copy.deepcopy(self.cn)
        for data in (us, cn):
            data["normal"] = [e for e in data["normal"] if terms.mod_id(e) != "Strength2"]
            # The same pick-one line also stands for Dexterity2 on full pages.
            dex = copy.deepcopy(next(e for e in data["essence"] if e["Code"] == "Strength2"))
            data["essence"].append(dict(dex, Code="Dexterity2"))
        mods, _ = terms.pair_mods(us, cn)
        self.assertNotIn("en", mods["Strength2"])
        self.assertEqual(mods["Strength2"]["essences"][0]["line"]["en"], ["+# to Strength, Dexterity or Intelligence"])
        # A later page (attribute sub-page) that shows the mod itself supplies the main text.
        terms.pair_mods(self.us, self.cn, mods=mods)
        self.assertEqual(mods["Strength2"]["en"], ["+# to Strength"])

    def test_disagreeing_level_is_reported_not_paired(self):
        cn = copy.deepcopy(self.cn)
        cn["normal"][0]["Level"] = "99"
        mods, mismatches = terms.pair_mods(self.us, cn)
        bad = terms.mod_id(self.us["normal"][0])
        self.assertEqual([m["id"] for m in mismatches], [bad])
        self.assertIn("Level", mismatches[0]["problems"][0])

    def test_items_pair_by_slug_and_variants(self):
        us_bases, us_uniques = terms.parse_items(load("us"))
        cn_bases, cn_uniques = terms.parse_items(load("cn"))
        bases, base_mm = terms.pair_items(us_bases, cn_bases, "base")
        uniques, unique_mm = terms.pair_items(us_uniques, cn_uniques, "unique")
        self.assertEqual(base_mm + unique_mm, [])
        self.assertEqual(uniques["Blackheart"]["zh_hans"], "幽暗之语")
        self.assertEqual(uniques["Blackheart"]["base"]["en"], "Iron Ring")
        self.assertEqual(len(uniques["Blackheart"]["explicits"]), 4)
        self.assertIn("Two-Stone_Ring#2", bases)
        self.assertNotEqual(bases["Two-Stone_Ring"]["implicits"], bases["Two-Stone_Ring#2"]["implicits"])


class TraditionalChineseTests(unittest.TestCase):
    def test_tw_pairs_alongside_cn(self):
        us, cn, tw = (terms.extract_modsview(load(side)) for side in ("us", "cn", "tw"))
        mods, mismatches = terms.pair_mods(us, cn, tw)
        self.assertEqual(mismatches, [])
        self.assertEqual(mods["IncreasedLife1"]["zh_hant"], ["+#最大生命"])
        self.assertEqual(mods["IncreasedLife1"]["affix"]["zh_hant"], "健壯之")

    def test_disagreeing_tw_range_is_reported(self):
        us, cn, tw = (terms.extract_modsview(load(side)) for side in ("us", "cn", "tw"))
        tw["normal"][0]["str"] = tw["normal"][0]["str"].replace("(", "(1", 1)
        _, mismatches = terms.pair_mods(us, cn, tw)
        self.assertEqual(len(mismatches), 1)
        self.assertTrue(mismatches[0]["problems"][0].startswith("ranges:"))
        self.assertIn("tw=", mismatches[0]["problems"][0])

    def test_tw_items_pair_by_slug(self):
        (us_bases, us_uniques), (cn_bases, cn_uniques), (tw_bases, tw_uniques) = (
            terms.parse_items(load(side)) for side in ("us", "cn", "tw"))
        bases, base_mm = terms.pair_items(us_bases, cn_bases, "base", tw_bases)
        uniques, unique_mm = terms.pair_items(us_uniques, cn_uniques, "unique", tw_uniques)
        self.assertEqual(base_mm + unique_mm, [])
        self.assertEqual(uniques["Blackheart"]["zh_hant"], "幽暗之語")
        self.assertEqual(bases["Two-Stone_Ring#2"]["implicits"][0]["zh_hant"], "+#%火焰與閃電抗性")
        del tw_bases["Two-Stone_Ring#2"]
        _, base_mm = terms.pair_items(us_bases, cn_bases, "base", tw_bases)
        self.assertEqual(base_mm[0]["problems"], ["missing on tw"])


class GemTests(unittest.TestCase):

    def test_plain_gemitem_links_are_gems(self):
        # P10: gems without a colour (grenades, crossbow, most newer skills) use class="gemitem".
        page = ('<tr><td><a class="gemitem" data-hover="?s=Data%5CGemEffects%2FIceStrike" href="/us/Ice_Strike">'
                'Ice Strike</a> (5)<div class="gem_tags small"><a data-keyword="Attack" href="Attack" '
                'class="KeywordPopups">Attack</a></div></td></tr>'
                '<tr><td><a class="gem_blue" data-hover="?s=Data%5CGemEffects%2FContagion" href="/us/Contagion">'
                'Contagion</a> (1)<div class="gem_tags small"></div></td></tr>')
        gems = terms.parse_gems(page)
        self.assertEqual(sorted(gems), ["Contagion", "Ice_Strike"])
        self.assertEqual((gems["Ice_Strike"]["name"], gems["Ice_Strike"]["colour"], gems["Ice_Strike"]["gem_effect"]),
                         ("Ice Strike", "", "IceStrike"))
        self.assertEqual(gems["Ice_Strike"]["tags"], [["Attack", "Attack"]])
        self.assertEqual(gems["Contagion"]["colour"], "blue")
    def test_table_and_card_layouts_pair_by_slug(self):
        gems = {side: terms.parse_gems((FIXTURE / side / "Gems.html").read_text(encoding="utf-8"))
                for side in ("us", "cn", "tw")}
        pairs, mismatches = terms.pair_gems(gems["us"], {"zh_hans": gems["cn"], "zh_hant": gems["tw"]})
        self.assertEqual(mismatches, [])
        boon = pairs["Alchemists_Boon"]
        self.assertEqual((boon["zh_hans"], boon["zh_hant"]), ("炼金师的恩典", "煉金師恩惠"))
        self.assertEqual(boon["gem_effect"], "AlchemistsBoon")
        self.assertEqual(boon["tags"][2], {"id": "Aura", "en": "Aura", "zh_hans": "光环", "zh_hant": "光環"})
        # Card layout: tags linked by page name, plus a description in every language.
        citadel = pairs["Ahns_Citadel"]
        self.assertEqual(citadel["tags"][0]["zh_hant"], "輔助")
        self.assertEqual(sorted(citadel["description"]), ["en", "zh_hans", "zh_hant"])
        report = terms.gem_pob_join(pairs, [{"name": "Alchemist's Boon", "variantId": "AlchemistsBoon"}])
        self.assertEqual(report["joined"], 1)
        self.assertEqual(pairs["Alchemists_Boon"]["pob"], {"variantId": "AlchemistsBoon"})

    def test_gem_joins_by_folded_name_or_variant(self):
        gems = {"Oisins_Oath": {"en": "Oisín's Oath"}, "Ricochet_III": {"en": "Ricochet III", "gem_effect": "Rico3"},
                "New_Gem": {"en": "New Gem"}}
        report = terms.gem_pob_join(gems, [{"name": "Oisin's Oath", "variantId": "OisinsOathSupport"},
                                           {"name": "Ricochet", "variantId": "Rico3"}])
        self.assertEqual(report["joined_by"], {"folded_name": 1, "variantId": 1})
        self.assertEqual(gems["Oisins_Oath"]["pob"], {"variantId": "OisinsOathSupport"})
        self.assertEqual([g["slug"] for g in report["missing_in_pob"]], ["New_Gem"])


class SocketableTests(unittest.TestCase):
    def test_rune_lines_without_mod_id_key_by_rune_base(self):
        us, cn = terms.extract_modsview(load("us")), terms.extract_modsview(load("cn"))
        rune = ('<a class="whiteitem SoulCore" data-hover="?s=Data%5CBaseItemTypes%2FMetadata%2FItems%2F'
                'SoulCores%2FRuneFireLesser" href="Lesser_Desert_Rune">{}</a>')
        for data, name, text in ((us, "Lesser Desert Rune", "Adds <span class='mod-value'>4</span> to "
                                  "<span class='mod-value'>6</span> Fire Damage"),
                                 (cn, "低阶沙漠符文", "附加 <span class='mod-value'>4</span> - "
                                  "<span class='mod-value'>6</span> 火焰伤害")):
            data["socketable"] = [{"type": "socketable", "Level": 1, "ModGenerationTypeID": 0,
                                   "ModFamilyList": ["DesertRune"], "Name": rune.format(name), "str": text}]
        socketables = {}
        _, mismatches = terms.pair_mods(us, cn, socketables=socketables)
        self.assertEqual(mismatches, [])
        rune = socketables["Metadata/Items/SoulCores/RuneFireLesser"]
        self.assertEqual(rune["name"]["zh_hans"], "低阶沙漠符文")
        self.assertEqual(rune["lines"][0]["zh_hans"], ["附加 # - # 火焰伤害"])


class BuildTests(unittest.TestCase):
    def test_main_writes_table_and_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            cache = tmp / "cache"
            shutil.copytree(FIXTURE, cache)
            (cache / "manifest.json").write_text(json.dumps({
                "site_version": "test", "license_note": "CC BY-NC-SA 3.0",
                "pages": [{"url": "https://poe2db.tw/us/Rings", "file": "us/Rings.html", "fetched": "t"}]}))
            charm = cache / "poecharm" / "zh-rCN"
            charm.mkdir(parents=True)
            (charm / "statDescriptions.csv").write_text('"{0} to maximum Life","{0} 最大生命"\n', encoding="utf-8")
            (charm / "Items_Accessories.txt.csv").write_text('"Two-Stone Ring",双玉戒指\n', encoding="utf-8")
            pob = tmp / "pob" / "src" / "Data"
            pob.mkdir(parents=True)
            (pob / "ModItem.lua").write_text(
                'return {\n\t["IncreasedLife1"] = { type = "Prefix", affix = "Hale", "+(10-19) to maximum Life", '
                'statOrder = { 887 }, level = 1, group = "IncreasedLife", weightKey = { "ring", "default", }, '
                'weightVal = { 1, 0 }, modTags = { }, },\n'
                '\t["RingOnlyInPoB"] = { type = "Suffix", affix = "x", "+(1-2) to Nothing", statOrder = { 1 }, '
                'level = 1, group = "X", weightKey = { "ring", }, weightVal = { 1 }, modTags = { }, },\n}\n',
                encoding="utf-8")
            out, evidence = tmp / "out", tmp / "evidence"
            terms.main(["--cache", str(cache), "--pob", str(tmp / "pob"), "--out", str(out),
                        "--evidence", str(evidence), "Rings"])
            table = json.loads((out / "rings.json").read_text(encoding="utf-8"))
            self.assertEqual(table["metadata"]["version"], "poe2db-1.0")
            self.assertEqual(table["metadata"]["sources"][0]["url"], "https://poe2db.tw/us/Rings")
            self.assertIn("CC BY-NC-SA 3.0", table["metadata"]["license"])
            self.assertEqual(table["mods"]["IncreasedLife1"]["pob_file"], "ModItem.lua")
            join = json.loads((evidence / "rings-pob-join.json").read_text(encoding="utf-8"))
            self.assertEqual(join["missing_on_page"], ["RingOnlyInPoB"])
            self.assertIn("Strength2", [m["id"] for m in join["missing_in_pob"]])
            check = json.loads((evidence / "rings-poecharm-check.json").read_text(encoding="utf-8"))
            self.assertEqual(check["mod_lines"]["differ"][0]["poecharm"], ["{0} 最大生命"])
            self.assertEqual(check["names"]["agree"], 1)



class P05bTableTests(unittest.TestCase):
    def test_unique_kept_when_only_traditional_breaks_lines_differently(self):
        # From Nothing (PoE2DB 1.0): us and cn have two lines, the tw page writes them as one.
        us = {"From_Nothing": {"name": "From Nothing", "base": "Diamond", "implicits": [],
                               "explicits": ["Passives in Radius of Passive Skill can be Allocated",
                                             "without being connected to your tree"]}}
        cn = {"From_Nothing": {"name": "无根之源", "base": "宝钻", "implicits": [],
                               "explicits": ["Passive Skill范围内的天赋可以在", "未连结至天赋树的情况下配置"]}}
        tw = {"From_Nothing": {"name": "從無到有", "base": "鑽石", "implicits": [],
                               "explicits": ["範圍Passive Skill內的天賦可以在沒有連結你的天賦樹下被配置"]}}
        pairs, mismatches = terms.pair_items(us, cn, "unique", tw)
        self.assertEqual(pairs["From_Nothing"]["explicits"][1],
                         {"en": "without being connected to your tree", "zh_hans": "未连结至天赋树的情况下配置"})
        self.assertEqual(pairs["From_Nothing"]["zh_hant"], "從無到有")
        self.assertEqual(mismatches[0]["kept_without"], ["zh_hant"])
        # When the Simplified side disagrees the item is still left out.
        cn["From_Nothing"]["explicits"] = cn["From_Nothing"]["explicits"][:1]
        pairs, mismatches = terms.pair_items(us, cn, "unique", tw)
        self.assertEqual((pairs, "kept_without" in mismatches[0]), ({}, False))

    def test_cannon_base_page_feeds_crossbow_mods(self):
        self.assertIn("Trarthan_Cannon", terms.SUBPAGES["Crossbows"])

if __name__ == "__main__":
    unittest.main()
