"""Tests for ops/poe2db_keywords.py: buff/state names from cached PoE2DB pages, no fetching."""
import json
from pathlib import Path
import tempfile
import unittest

import poe2db_keywords as kw


def write(root, lang, page, body):
    path = Path(root) / lang / f"{page}.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"<html><title>{page} - x</title>{body}</html>", encoding="utf-8")


def link(href, name):
    return f'<a href="{href}" class="strong fontinSmallCaps">{name}</a>'


class KeywordTests(unittest.TestCase):
    def test_order_and_forms(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "manifest.json").write_text(json.dumps({"pages": []}), encoding="utf-8")
            write(tmp, "us", "Keywords", link("Onslaught", "Onslaught") + link("Maim", "Maim"))
            write(tmp, "cn", "Keywords", link("Onslaught", "猛攻") + link("Maim", "瘫痪"))
            write(tmp, "tw", "Keywords", link("Onslaught", "猛攻"))
            write(tmp, "us", "Adrenaline", "buff")
            write(tmp, "cn", "Adrenaline", "buff")  # title is the page id: no Chinese name
            names = ["Onslaught", "Maim", "Maimed", "Corrosion", "Adrenaline", "Chaotic Might"]
            old = kw.NAMES
            kw.NAMES = names
            try:
                result, fetched = kw.build(Path(tmp), {"corrosion": "腐蚀"}, fetch_pages=False,
                                           i18n={"i18n-zh_CN": {"Chaotic Might": "混沌之力"}, "i18n-zh_TW": {}},
                                           poecharm={})
            finally:
                kw.NAMES = old
        self.assertEqual(fetched, [])
        self.assertEqual(result["names"]["Onslaught"]["zh_hans"], "猛攻")
        self.assertEqual(result["names"]["Maimed"]["zh_hans"], "瘫痪")
        self.assertEqual(result["names"]["Corrosion"]["source"], "poe2db tables")
        missing = {m["name"]: m for m in result["missing"]}
        self.assertEqual(missing["Adrenaline"]["why"], "no Chinese title")
        self.assertEqual(missing["Chaotic Might"]["why"], "not cached")
        self.assertEqual(missing["Chaotic Might"]["zh_CN"], "混沌之力")  # reported, not used
        self.assertNotIn("Chaotic Might", result["names"])


if __name__ == "__main__":
    unittest.main()
