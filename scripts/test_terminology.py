import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from terminology import Catalog, ROOT, normalize


FIXTURE = ROOT / "tests/fixtures/p03/terms.json"
PIN = json.loads((ROOT / "sources/pob.json").read_text())["commit"]


class TerminologyTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.catalog = self.load(self.data)

    def load(self, data):
        return Catalog(data, engine_commit=PIN, data_version="synthetic/1")

    def test_all_languages_and_alternate_aliases_keep_same_id(self):
        for row in self.data["entries"]:
            for names in row["aliases"].values():
                for name in names:
                    matches = self.catalog.lookup(name, kind=row["kind"])
                    self.assertEqual([term.id for term in matches], [row["id"]])
            self.assertEqual(self.catalog.by_id(row["id"]).aliases["en"][0],
                             row["aliases"]["en"][0])

    def test_normalization_unknown_and_exact_ids(self):
        self.assertEqual(self.catalog.lookup("  PAPER\t comet  ")[0].id,
                         "synthetic:skill:paper-comet")
        self.assertEqual(normalize("Cafe\u0301"), normalize("CAFÉ"))
        self.assertEqual(self.catalog.lookup("unknown"), ())
        self.assertIsNone(self.catalog.by_id("SYNTHETIC:skill:paper-comet"))
        with self.assertRaises(ValueError):
            self.catalog.lookup(" \t")

    def test_collisions_return_candidates_including_same_kind(self):
        self.assertEqual(len(self.catalog.lookup("练习火花")), 2)
        self.assertEqual(len(self.catalog.lookup("Practice Spark", kind="skill")), 1)
        self.data["entries"][1]["kind"] = "skill"
        self.assertEqual(len(self.load(self.data).lookup("Practice Spark", kind="skill")), 2)

    def test_version_and_schema_mismatch(self):
        for field in ("schema", "engine_commit", "data_version"):
            with self.subTest(field=field):
                bad = copy.deepcopy(self.data)
                bad[field] = "other-version"
                with self.assertRaises(ValueError):
                    self.load(bad)

    def test_reject_inconsistent_catalog(self):
        mutations = [
            lambda d: d["entries"].append(d["entries"][0]),
            lambda d: d["entries"][0].update(source="missing"),
            lambda d: d["entries"][0].update(kind="other"),
            lambda d: d["entries"][0]["aliases"].pop("zh-Hant"),
            lambda d: d["entries"][0]["aliases"].update(en=[""]),
            lambda d: d["sources"]["original-p03"].pop("license"),
        ]
        for mutate in mutations:
            bad = copy.deepcopy(self.data)
            mutate(bad)
            with self.assertRaises(ValueError):
                self.load(bad)

    def test_cli_utf8_statuses_and_invalid_files(self):
        base = [sys.executable, "-B", str(ROOT / "scripts/terminology.py"),
                "--catalog", str(FIXTURE), "--data-version", "synthetic/1"]
        for query, code, status in [("紙燈籠", 0, "found"), ("练习火花", 3, "ambiguous"),
                                    ("unknown", 2, "not_found")]:
            result = subprocess.run(base + ["--alias", query], cwd="/tmp", capture_output=True,
                                    text=True, encoding="utf-8", check=False)
            self.assertEqual(result.returncode, code, result.stderr)
            self.assertEqual(json.loads(result.stdout)["status"], status)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"
            for contents in ("{", "[]"):
                path.write_text(contents)
                result = subprocess.run(base + ["--catalog", str(path), "--alias", "x"],
                                        capture_output=True, text=True, check=False)
                self.assertEqual(result.returncode, 1)
                self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
