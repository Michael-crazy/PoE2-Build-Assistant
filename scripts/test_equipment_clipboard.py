"""Authored samples only: section/number fidelity and unresolved-mod diagnostics."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import unittest

from equipment_clipboard import inspect_clipboard

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/p05"


class ClipboardTests(unittest.TestCase):
    def setUp(self):
        self.profile = json.loads((FIXTURES / "profile.synthetic.json").read_text())

    def test_authored_samples_preserve_every_line_and_number(self):
        expected = {
            "simplified": [["+007"], ["12.50", "30.00"], ["-0.25"]],
            "traditional": [["0"], ["-2.00", "+3.50"], ["+0.00"]],
        }
        for name, numbers in expected.items():
            for ending in ("\n", "\r\n"):
                with self.subTest(name=name, ending=repr(ending)):
                    text = (FIXTURES / f"{name}.synthetic.txt").read_text().replace("\n", ending)
                    before = deepcopy(self.profile)
                    result = inspect_clipboard(text, self.profile)
                    self.assertEqual(result["raw_text"], text)
                    rows = result["separators"] + [row for section in result["sections"]
                                                         for row in section["lines"]]
                    self.assertEqual("".join(row["raw"] for row in sorted(rows, key=lambda r: r["line"])), text)
                    self.assertEqual(len(result["sections"]), 6)
                    self.assertEqual([m["numbers"] for m in result["matches"]], numbers)
                    self.assertEqual(len(result["issues"]), 1)
                    issue = result["issues"][0]
                    self.assertEqual((issue["section"], issue["line"], issue["code"]),
                                     (4, 17, "unmatched_mod"))
                    self.assertEqual(issue["text"], text.splitlines()[16])
                    self.assertEqual(result["pob_import"], "pending")
                    self.assertEqual(self.profile, before)

    def test_blank_lines_trailing_spaces_and_no_final_newline_survive(self):
        text = "标题  \n\n--------\n测试生命增加 +007\n\n--------\n尾注"
        self.profile["mod_sections"] = [1]
        result = inspect_clipboard(text, self.profile)
        self.assertEqual(result["raw_text"], text)
        self.assertEqual(result["sections"][0]["lines"][0]["text"], "标题  ")
        self.assertEqual(result["sections"][-1]["lines"][0]["raw"], "尾注")
        self.assertEqual(result["issues"], [])

    def test_unknown_and_ambiguous_rules_do_not_become_matches(self):
        self.profile["mod_sections"] = [0]
        self.profile["rules"].append({"id": "synthetic.other", "template": "测试生命增加 {number}"})
        result = inspect_clipboard("测试生命增加 10\n测试生命增加 1e3", self.profile)
        self.assertEqual(result["matches"], [])
        self.assertEqual([i["code"] for i in result["issues"]], ["ambiguous_mod", "unmatched_mod"])

    def test_invalid_input_profile_and_section_fail(self):
        for text, change in [("", {}), ("标题", {"scope": "production"}),
                             ("标题", {"mod_sections": [9]}),
                             ("标题", {"mod_sections": [True]}),
                             ("标题", {"rules": [None]})]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                inspect_clipboard(text, {**self.profile, **change})

    def test_cli_has_visible_unmatched_mod_and_retains_source(self):
        result = subprocess.run([sys.executable, "-B", str(ROOT / "scripts/equipment_clipboard.py"),
                                 str(FIXTURES / "simplified.synthetic.txt"), "--profile",
                                 str(FIXTURES / "profile.synthetic.json")],
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        original = (FIXTURES / "simplified.synthetic.txt").read_bytes().decode("utf-8")
        self.assertEqual(output["raw_text"], original)
        self.assertIn("词缀未匹配", result.stdout)


if __name__ == "__main__":
    unittest.main()
