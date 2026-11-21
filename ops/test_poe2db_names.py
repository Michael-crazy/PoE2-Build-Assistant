"""D03: the PoE2DB name tables live in data/terms/poe2db-1.0/names/, apart from the item class tables."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import item_text  # noqa: E402
import pob_ui_fallback  # noqa: E402,F401  (defaults point at names/)
import poe2db_item_classes  # noqa: E402
import poe2db_keywords  # noqa: E402
import ui_fallback_prep as prep  # noqa: E402

TERMS = ROOT / "data/terms/poe2db-1.0"


class LayoutTests(unittest.TestCase):
    def test_top_level_holds_only_item_tables(self):
        for path in TERMS.glob("*.json"):
            meta = json.loads(path.read_text(encoding="utf-8"))["metadata"]
            self.assertTrue(path.name == "mods.json" or meta.get("item_class"), path.name)
        self.assertTrue((TERMS / "names/item_classes.json").exists())
        self.assertTrue((TERMS / "names/keywords.json").exists())

    def test_scripts_default_to_names(self):
        self.assertEqual(poe2db_item_classes.DEFAULT_OUT, TERMS / "names/item_classes.json")
        self.assertEqual(poe2db_keywords.DEFAULT_OUT, TERMS / "names/keywords.json")
        source = (ROOT / "ops/pob_ui_fallback.py").read_text(encoding="utf-8")
        self.assertIn('"data/terms/poe2db-1.0/names/item_classes.json"', source)
        self.assertIn('"data/terms/poe2db-1.0/names/keywords.json"', source)

    def test_item_text_loads_without_name_tables(self):
        terms = item_text.Terms(TERMS)
        self.assertTrue(terms.names["base"])

    def test_game_terms_reads_names_subfolder_in_flat_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "names").mkdir()
            (root / "amulets.json").write_text(json.dumps({"x": {"en": "Onslaught", "zh_hans": "甲"}}), encoding="utf-8")
            (root / "names/keywords.json").write_text(json.dumps(
                {"names": {"Onslaught": {"zh_hans": "乙"}, "Arcane Surge": {"zh_hans": "奥术涌动"}}}), encoding="utf-8")
            (root / "zz.json").write_text(json.dumps({"x": {"en": "Arcane Surge", "zh_hans": "丙"}}), encoding="utf-8")
            terms = prep.game_terms(root)
        self.assertEqual(terms["onslaught"], "甲")          # amulets.json sorts before keywords.json
        self.assertEqual(terms["arcane surge"], "奥术涌动")  # keywords.json before zz.json


if __name__ == "__main__":
    unittest.main()
