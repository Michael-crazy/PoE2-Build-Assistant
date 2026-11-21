"""Tests for ops/poe2db_item_classes.py: class names from cached PoE2DB page titles."""
from pathlib import Path
import tempfile
import unittest

import poe2db_item_classes as classes


def page(root, lang, name, title):
    path = Path(root) / lang / f"{name}.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"<html><head><title>{title} - PoE2DB, Path of Exile Wiki {lang}</title></head></html>",
                    encoding="utf-8")


class TitleTests(unittest.TestCase):
    def test_cn_title_then_tw_then_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            page(tmp, "us", "Crossbows", "Crossbows")
            page(tmp, "cn", "Crossbows", "战弩")
            page(tmp, "tw", "Crossbows", "十字弓")
            page(tmp, "us", "Body_Armours", "Body_Armours")
            page(tmp, "cn", "Body_Armours", "Body_Armours")
            page(tmp, "tw", "Body_Armours", "胸甲")
            result = classes.build(Path(tmp), lambda text: text)
        self.assertEqual(result["pob"]["Crossbow"]["zh_hans"], "战弩")
        self.assertEqual(result["pob"]["Crossbow"]["source"], "cn")
        self.assertEqual(result["pob"]["Body Armour"]["zh_hans"], "胸甲")
        self.assertEqual(result["pob"]["Body Armour"]["source"], "tw")
        missing = {m.get("pob") or m.get("page") for m in result["missing"]}
        self.assertIn("Bows", missing)  # page not cached
        self.assertIn("Fishing Rod", missing)  # no class page at all
        self.assertNotIn("Bow", result["pob"])


if __name__ == "__main__":
    unittest.main()
