"""Synthetic Tencent contract checks; no client samples or network requests."""

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import unittest

from trade_listing import ListingError, normalize_listings

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/m02/listings.synthetic.json"
LEAGUE = "合成腾讯测试赛季"


class TencentListingTests(unittest.TestCase):
    def setUp(self):
        self.payload = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_simplified_item_and_raw_price_survive_without_translation(self):
        before = deepcopy(self.payload)
        rows = normalize_listings(self.payload, league=LEAGUE, realm="tencent")
        self.assertIn("合成", self.payload["_provenance"])
        self.assertEqual(len(rows), 2)
        for source, row in zip(self.payload["result"], rows):
            self.assertEqual(row, {"id": source["id"], "realm": "tencent",
                                   "league": LEAGUE, "item": source["item"],
                                   "price": source["listing"]["price"]})
        rows[1]["item"]["explicitMods"].append("改动")
        rows[0]["price"]["currency"] = "改动"
        self.assertEqual(self.payload, before)

    def test_same_id_in_separate_realms_stays_separate(self):
        international = normalize_listings(self.payload, league=LEAGUE)
        tencent = normalize_listings(self.payload, league=LEAGUE, realm="tencent")
        self.assertNotEqual((international[0]["realm"], international[0]["id"]),
                            (tencent[0]["realm"], tencent[0]["id"]))
        with self.assertRaisesRegex(ListingError, "realm"):
            normalize_listings(self.payload, league=LEAGUE, realm="unknown")

    def test_empty_and_unpriced_are_not_fabricated_quotes(self):
        self.assertEqual(normalize_listings({"result": []}, league=LEAGUE,
                                            realm="tencent"), [])
        for listing in ({}, {"price": None}):
            self.payload["result"][0]["listing"] = listing
            rows = normalize_listings(self.payload, league=LEAGUE, realm="tencent")
            self.assertIsNone(rows[0]["price"])

    def test_tencent_reuses_batch_failure_rules(self):
        for mutation in ("league", "duplicate", "price", "error"):
            payload = deepcopy(self.payload)
            if mutation == "league":
                payload["result"][1]["item"]["league"] = "其他赛季"
            elif mutation == "duplicate":
                payload["result"][1]["id"] = payload["result"][0]["id"]
            elif mutation == "price":
                payload["result"][1]["listing"]["price"]["amount"] = "12"
            else:
                payload["error"] = {"message": "合成失败"}
            with self.subTest(mutation=mutation), self.assertRaises(ListingError):
                normalize_listings(payload, league=LEAGUE, realm="tencent")

    def test_cli_tencent_and_wrong_league_no_partial_output(self):
        for league, status in ((LEAGUE, 0), ("其他赛季", 1)):
            result = subprocess.run(
                [sys.executable, "-B", str(ROOT / "scripts/trade_listing.py"),
                 str(FIXTURE), "--realm", "tencent", "--league", league],
                capture_output=True, text=True, encoding="utf-8", timeout=5)
            self.assertEqual(result.returncode, status, result.stderr)
            if status == 0:
                self.assertIn("合成晨光", result.stdout)
                self.assertTrue(all(row["realm"] == "tencent"
                                    for row in json.loads(result.stdout)))
            else:
                self.assertEqual(result.stdout, "")
                self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
