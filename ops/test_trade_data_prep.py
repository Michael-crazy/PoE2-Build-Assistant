import json
from pathlib import Path
import tempfile
import unittest

import trade_data_prep as prep


def write(folder, name, result):
    (folder / f"{name}.json").write_text(json.dumps({"result": result}), encoding="utf-8")


class JoinTests(unittest.TestCase):
    def test_joins_by_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            tencent, intl = Path(tmp, "t"), Path(tmp, "i")
            tencent.mkdir(), intl.mkdir()
            write(tencent, "stats", [{"id": "explicit", "entries": [
                {"id": "explicit.stat_1", "text": "+#% 火焰抗性", "type": "explicit"},
                {"id": "explicit.stat_cn", "text": "只在国服", "type": "explicit"}]}])
            write(intl, "stats", [{"id": "explicit", "entries": [
                {"id": "explicit.stat_1", "text": "+#% to Fire Resistance", "type": "explicit"}]}])
            write(tencent, "static", [{"id": "Currency", "entries": [{"id": "divine", "text": "神圣石", "image": "/d.png"}]},
                                      {"id": "Runes", "entries": [{"id": "rune", "text": "符文"}]}])
            write(intl, "static", [{"id": "Currency", "entries": [{"id": "divine", "text": "Divine Orb"}]}])
            write(tencent, "leagues", [{"id": "奥杜尔秘符"}])
            stats, currency, leagues, only = prep.build(tencent, intl)
        self.assertEqual(stats, {"explicit.stat_1": {"en": "+#% to Fire Resistance", "zh": "+#% 火焰抗性", "type": "explicit"}})
        self.assertEqual(currency, [{"id": "divine", "en": "Divine Orb", "zh": "神圣石", "image": "/d.png"}])
        self.assertEqual(leagues, ["奥杜尔秘符"])
        self.assertEqual(only["stats_tencent_only"], ["explicit.stat_cn"])


if __name__ == "__main__":
    unittest.main()
