import json
from pathlib import Path
import tempfile
import unittest

import pob_gem_tooltips as gt
from pob_gem_tooltips import join_lines, zh_template
from pob_localization import localize_line


def popup(name, tags, props, description, sections, quality, hidden=True):
    """A gem popup the way PoE2DB writes it (tags first, hybridHeader sections, hidden stats collapsed)."""
    out = ['<div class="newItemPopup GemPopup item-popup--poe2 ">',
           f'<div class="itemName"><span class="lc">{name}</span></div>',
           '<div class="itemName typeLine"><span class="lc"><a href="Spells">Spell</a></span></div>',
           '<div class="Stats"><div class="property">'
           + ", ".join(f'<a data-keyword="x" href="{slug}" class="KeywordPopups">{text}</a>' for slug, text in tags)
           + "</div>"]
    out += [f'<div class="property">{p}</div>' for p in props]
    out.append(f'<div class="secDescrText">{description}</div>')
    for header, lines in sections:
        if header:
            out.append(f'<div class="hybridHeader gemTabs">{header}</div>')
        out += [f'<div class="explicitMod">{line}</div>' for line in lines]
        if hidden:
            out.append('<div class="explicitMod"><span class="secondary collapse">base is projectile [1]</span></div>')
    out.append('<div class="quality-text"><br /><span class="white">Q:</span></div>')
    out += [f'<div class="qualityMod">{q}</div>' for q in quality]
    out.append('</div></div><div class="itemboximage"></div>')
    return "".join(out)


DASH = '<span class="ndash">—</span>'
US = popup("Fireball", [("Fire_Damage", "Fire"), ("Projectiles", "Projectile")],
           ["Tier: <span>3</span>", f"Cost: <span>(10{DASH}104) Mana</span>"], "Launch a ball of Fire.",
           [("Projectile", [f"Deals <span class='mod-value'>(8{DASH}224)</span> to (12{DASH}336) Fire Damage"]),
            ("Firebolts", ["Fires <span class='mod-value'>12</span> Projectiles", "Spreads 2 and 3 metres"])],
           [f"+(0{DASH}10)% chance to fire 2 additional Projectiles"])
CN = popup("火球", [("Fire_Damage", "火焰"), ("Projectiles", "投射物")],
           ["等阶: 3", f"消耗: (10{DASH}104) 点魔力"], "发射一个火球。",
           [("投射物", [f"造成 (8{DASH}224) - (12{DASH}336) 火焰伤害"]),
            ("火焰弹", ["发射 12 个投射物", "扩散 3 米和 2 米"])],
           [f"+(0{DASH}10)% 的几率发射 2 个额外投射物"])


class Pages:
    def __init__(self, pages):
        self.pages = pages

    def page(self, lang, slug):
        return self.pages.get((lang, slug))


class JoinLinesTest(unittest.TestCase):
    def test_em_dash_range_and_values(self):
        en = ["Deals (7—244) to (11—366) Fire Damage", "75% more damage per Stage"]
        zh = ["造成 (7—244) 到 (11—366) 火焰伤害", "每阶段伤害总增 75%"]
        out = join_lines(["Deals 4267 to 6400 Fire Damage", "75% more damage per Stage"], en, zh)
        self.assertEqual(out[0]["zh_hans"], "造成 # 到 # 火焰伤害")
        self.assertEqual(localize_line("Deals 4267 to 6400 Fire Damage", out[0]["zh_hans"]),
                         "造成 4267 到 6400 火焰伤害")
        self.assertEqual(out[1]["zh_hans"], "每阶段伤害总增 #%")

    def test_plus_sign_kept(self):
        self.assertEqual(zh_template("+10% 几率发射 2 个额外投射物"), "+#% 几率发射 # 个额外投射物")

    def test_key_with_two_translations_or_missing_is_unjoined(self):
        en = ["Deals 1 to 2 Fire Damage", "Deals 3 to 4 Fire Damage"]
        zh = ["造成 1 到 2 火焰伤害", "造成 3 至 4 点火焰伤害"]
        self.assertEqual(join_lines(["Deals 5 to 6 Fire Damage", "Fires 12 Projectiles"], en, zh), [None, None])

    def test_same_translation_twice_joins(self):
        en = ["Deals 1 to 2 Fire Damage", "Deals 3 to 4 Fire Damage"]
        zh = ["造成 1 - 2 火焰伤害", "造成 3 - 4 火焰伤害"]
        self.assertEqual(join_lines(["Deals 5 to 6 Fire Damage"], en, zh)[0]["zh_hans"], "造成 # - # 火焰伤害")

    def test_reordered_values(self):
        out = join_lines(["Spreads 4 and 5 metres"], ["Spreads 2 and 3 metres"], ["扩散 3 米和 2 米"])
        self.assertEqual(out[0], {"key": "spreads # and # metres", "zh_hans": "扩散 # 米和 # 米", "order": [1, 0]})
        self.assertEqual(localize_line("Spreads 4 and 5 metres", out[0]["zh_hans"], out[0]["order"]), "扩散 5 米和 4 米")


class PageTest(unittest.TestCase):
    def test_parse_popup(self):
        (p,) = gt.parse_popups(US)
        self.assertEqual(p["name"], "Fireball")
        self.assertEqual(p["tags"], [("Fire_Damage", "Fire"), ("Projectiles", "Projectile")])
        self.assertEqual(p["properties"], ["Tier: 3", "Cost: (10—104) Mana"])
        self.assertEqual(p["description"], "Launch a ball of Fire.")
        self.assertEqual([s["header"] for s in p["sections"]], ["Projectile", "Firebolts"])
        self.assertEqual(p["sections"][0]["lines"], ["Deals (8—224) to (12—336) Fire Damage"])  # hidden stat skipped
        self.assertEqual(p["quality"], ["+(0—10)% chance to fire 2 additional Projectiles"])

    def test_pair_and_traditional_left_out(self):
        pairs, problems = gt.pair_popups(gt.parse_popups(US)[0], gt.parse_popups(CN)[0])
        self.assertEqual(problems, [])
        self.assertEqual(pairs["tags"], [("Fire", "火焰"), ("Projectile", "投射物")])
        self.assertEqual(pairs["headers"], [("Projectile", "投射物"), ("Firebolts", "火焰弹")])
        traditional = CN.replace("投射物", "投射物").replace("火焰弹", "火焰彈")
        pairs, problems = gt.pair_popups(gt.parse_popups(US)[0], gt.parse_popups(traditional)[0],
                                         lambda text: text.replace("彈", "弹"))
        self.assertNotIn(("Firebolts", "火焰彈"), pairs["headers"])
        self.assertTrue(any(p.startswith("traditional") for p in problems))

    def test_level_table_and_number_compare(self):
        page = ('<div id="LevelEffect"></div><table><thead><tr><th>等级</th><th>魔力</th><th><span class="explicitMod">'
                '造成 <span>8</span> - <span>12</span> 火焰伤害</span></th></tr></thead><tbody>'
                '<tr><td>20</td><td>104</td><td>224, 336</td></tr></tbody></table>')
        headers, rows = gt.level_table(page)
        self.assertEqual(headers[2], "造成 8 - 12 火焰伤害")
        self.assertEqual(rows, [["20", "104", "224, 336"]])
        self.assertEqual(gt.compare_numbers([224, 336], [224, 336]), "same")
        self.assertEqual(gt.compare_numbers([8.5, 1.4], [1.4]), "same")
        self.assertEqual(gt.compare_numbers([6.4], [6.5]), "rounding")
        self.assertEqual(gt.compare_numbers([570, 856], [744, 1116]), "value")


class BuildTest(unittest.TestCase):
    def test_class_table_tags(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "skill_gems.json").write_text(json.dumps({"gems": {"Spark": {"en": "Spark", "tags": [
                {"id": "Lightning", "en": "Lightning", "zh_hans": "闪电"},
                {"id": "AoESkill", "en": "AoE", "zh_hans": "效果区域"}]}}}), encoding="utf-8")
            Path(tmp, "support_gems.json").write_text(json.dumps({"gems": {"X": {"en": "X", "tags": [
                {"id": "Lightning", "en": "Lightning", "zh_hans": "闪电"}]}}}), encoding="utf-8")
            self.assertEqual(sorted(gt.class_tags(tmp)),
                             [("AoE", "效果区域"), ("Lightning", "闪电"), ("Lightning", "闪电")])

    def test_build_and_value_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            terms = Path(tmp)
            (terms / "skill_gems.json").write_text(json.dumps({"gems": {"Fireball": {
                "en": "Fireball", "pob": {"gameId": "Metadata/Items/Gem/SkillGemFireball"}}}}), encoding="utf-8")
            table_page = ('<div id="LevelEffect"></div><table><thead><tr><th>等级</th><th>造成 8 - 12 火焰伤害</th>'
                          '</tr></thead><tbody><tr><td>20</td><td>224, 336</td></tr></tbody></table>')
            fetcher = Pages({("us", "Fireball"): US, ("cn", "Fireball"): CN + table_page})
            dump = {"Metadata/Items/Gems/SkillGemFireball": {
                "name": "Fireball", "gameId": "Metadata/Items/Gem/SkillGemFireball", "effects": [{
                    "id": "FireballPlayer", "name": "Fireball", "description": "Launch a ball of Fire.",
                    "quality": ["10% chance to fire 2 additional Projectiles"],
                    "statSets": [{"label": "Projectile", "lines": {
                        "1": ["Deals 8 to 12 Fire Damage", "Unknown line 5"],
                        "20": ["Deals 224 to 336 Fire Damage"]}}]}]}}
            table, report = gt.build(dump, terms, fetcher)
            effect = table["effects"]["FireballPlayer"]
            self.assertEqual(effect["lines"]["deals # to # fire damage"], {"zh_hans": "造成 # - # 火焰伤害"})
            self.assertEqual(effect["quality"]["#% chance to fire # additional projectiles"]["zh_hans"],
                             "+#% 的几率发射 # 个额外投射物")
            self.assertEqual(effect["description"]["zh_hans"], "发射一个火球。")
            self.assertEqual(report["unjoined"], {"FireballPlayer": ["Unknown line 5"]})
            self.assertEqual(table["labels"], {"Tier": "等阶", "Cost": "消耗"})
            self.assertEqual(table["values"], {"# mana": {"zh_hans": "# 点魔力"}})
            self.assertEqual(table["statset_labels"], {"Projectile": "投射物", "Firebolts": "火焰弹"})
            self.assertEqual(table["tags"]["Fire"], "火焰")
            check = gt.check_values([("Metadata/Items/Gem/SkillGemFireball", "FireballPlayer", 20)], dump, table, fetcher)
            self.assertEqual((check["compared_values"], check["differences"]), (2, []))


if __name__ == "__main__":
    unittest.main()
