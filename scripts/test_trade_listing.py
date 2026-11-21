"""Authored offline trade contract checks; no live market claims."""

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from trade_listing import ListingError, normalize_listings

FIXTURE = Path(__file__).resolve().parents[1] / "tests/fixtures/m01/listings.json"
LEAGUE = "Offline Test League"
ENTRY = Path(__file__).with_name("trade_listing.py")


class ListingTests(unittest.TestCase):
    def setUp(self):
        self.payload = json.loads(FIXTURE.read_text())

    def test_unique_and_multimod_rare_keep_identity_item_price_and_order(self):
        before = deepcopy(self.payload)
        rows = normalize_listings(self.payload, league=LEAGUE)
        self.assertEqual([row["id"] for row in rows],
                         ["authored-unique-001", "authored-rare-002"])
        for source, row in zip(self.payload["result"], rows):
            self.assertEqual(row["item"], source["item"])
            self.assertEqual(row["price"], source["listing"]["price"])
            self.assertEqual((row["realm"], row["league"]), ("international", LEAGUE))
        self.assertEqual(len(rows[1]["item"]["explicitMods"]), 4)
        rows[0]["item"]["explicitMods"].append("changed")
        self.assertEqual(self.payload, before)

    def test_empty_results_and_unpriced_item(self):
        self.assertEqual(normalize_listings({"result": []}, league=LEAGUE), [])
        for listing in ({"price": None}, {}):
            self.payload["result"][0]["listing"] = listing
            rows = normalize_listings(self.payload, league=LEAGUE)
            self.assertIsNone(rows[0]["price"])

    def test_rejects_mixed_league_duplicate_missing_item_and_bad_envelopes(self):
        for payload in (None, {}, {"result": None}, {"result": [None]},
                        {"error": {"message": "failure"}, "result": []}):
            with self.subTest(payload=payload), self.assertRaises(ListingError):
                normalize_listings(payload, league=LEAGUE)
        for field, value in (("league", "Other League"), ("league", None),
                             ("typeLine", ""), ("rarity", None)):
            payload = deepcopy(self.payload)
            payload["result"][1]["item"][field] = value
            with self.subTest(field=field), self.assertRaises(ListingError):
                normalize_listings(payload, league=LEAGUE)
        payload = deepcopy(self.payload)
        del payload["result"][1]["item"]
        with self.assertRaises(ListingError):
            normalize_listings(payload, league=LEAGUE)
        self.payload["result"].append(deepcopy(self.payload["result"][0]))
        with self.assertRaisesRegex(ListingError, "duplicate"):
            normalize_listings(self.payload, league=LEAGUE)

    def test_rejects_invalid_price_without_silently_dropping_listing(self):
        for amount in (0, -1, True, "12", float("nan"), float("inf"), None):
            self.payload["result"][1]["listing"]["price"]["amount"] = amount
            with self.subTest(amount=amount), self.assertRaises(ListingError):
                normalize_listings(self.payload, league=LEAGUE)
        for price in ({}, "12 exalted", {"amount": 1, "currency": "", "type": "~price"}):
            self.payload["result"][1]["listing"]["price"] = price
            with self.subTest(price=price), self.assertRaises(ListingError):
                normalize_listings(self.payload, league=LEAGUE)

    def test_cli_success_and_failures(self):
        def run(path, league=LEAGUE):
            return subprocess.run([sys.executable, "-B", str(ENTRY), str(path),
                                   "--league", league], capture_output=True, text=True, timeout=5)
        result = run(FIXTURE)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(json.loads(result.stdout)), 2)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.json"
            failures = [run(path), run(FIXTURE, "Wrong League")]
            path.write_text("{bad json")
            failures.append(run(path))
        for result in failures:
            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stdout, "")
            self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
