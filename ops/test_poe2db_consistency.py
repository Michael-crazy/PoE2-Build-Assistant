"""Tests for ops/poe2db_consistency.py: our tables against POBG's data/zh_cn by English name."""
import json
from pathlib import Path
import tempfile
import unittest

import poe2db_consistency as cc


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".jsonl":
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in data), encoding="utf-8")
    else:
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


class ConsistencyTests(unittest.TestCase):
    def test_compare(self):
        with tempfile.TemporaryDirectory() as tmp:
            terms, pobg = Path(tmp) / "terms", Path(tmp) / "pobg"
            write(terms / "rings.json", {"metadata": {"item_class": "Rings"}, "base_types": {
                "Gold_Ring": {"en": "Gold Ring", "zh_hans": "金光戒指"},
                "Iron_Ring": {"en": "Iron Ring", "zh_hans": "铁戒指"}},
                "uniques": {"Andvarius": {"en": "Andvarius", "zh_hans": "贪欲之记"}}})
            write(terms / "mods.json", {"metadata": {}, "mods": {"Dex1": {
                "en": ["+# to Dexterity"], "zh_hans": ["+# 敏捷"]}}})
            write(terms / "names/keywords.json", {"keywords": {"Onslaught": {"zh_hans": "猛攻"}}})
            write(pobg / "data/items/bases.jsonl", [{"name": "Gold Ring", "name_zh_tw": "金光戒指"},
                                                   {"name": "Iron Ring", "name_zh_tw": "铁戒"}])
            write(pobg / "data/zh_cn/items/bases.jsonl", [{"name": "Gold Ring", "name_zh_tw": "金光 戒指"},
                                                         {"name": "Iron Ring", "name_zh_tw": "铁戒"},
                                                         {"name": "Ruby Ring", "name_zh_tw": "红玉戒指"}])
            write(pobg / "data/zh_cn/items/uniques.jsonl", [{"name": "Andvarius", "name_zh_tw": "贪欲之记"}])
            write(pobg / "data/zh_cn/items/modifiers.jsonl", [{"text": "+(5—8) to Dexterity", "text_zh_tw": "+(5—8) 敏捷"}])
            write(pobg / "data/zh_cn/kg/keywords.jsonl", [{"name_en": "Onslaught", "name_zh_tw": None}])
            result = cc.check(terms, pobg)
            md = cc.markdown(result, "pobg")
        bases = result["bases"]
        self.assertEqual(bases["counts"]["same"], 1)               # whitespace ignored, zh_cn overlay used
        self.assertEqual(bases["differ"], [{"en": "Iron Ring", "ours": ["铁戒指"], "pobg": ["铁戒"]}])
        self.assertEqual(bases["only_pobg"], ["Ruby Ring"])
        self.assertEqual(result["uniques"]["counts"]["same"], 1)
        self.assertEqual(result["mod_lines"]["counts"]["same"], 1)  # values -> '#'
        self.assertEqual(result["keywords"]["counts"]["no_chinese_on_one_side"], 1)
        self.assertIn("Iron Ring：我们 铁戒指；POBG 铁戒", md)

    def test_template(self):
        self.assertEqual(cc.template("+(5—8) to Dexterity"), "+# to Dexterity")
        self.assertEqual(cc.template("(10-20)% increased Damage, 1.5 seconds"), "#% increased Damage, # seconds")


if __name__ == "__main__":
    unittest.main()
