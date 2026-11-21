"""Tests for ops/poe2db_update.py: step order and the PoB terms export."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import poe2db_update as up


class UpdateTests(unittest.TestCase):
    def test_export_rewrites_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            loc, tree = Path(tmp) / "loc", Path(tmp) / "pob"
            loc.mkdir()
            for name in up.POB_TERMS:
                table = {"metadata": {"format": "f", "pob_commit": "p"}, name: 1}
                if name == "gem_tooltips.json":
                    table = {"format": "poe2-gem-tooltips/1", "pob_commit": "p", "effects": {}}
                (loc / name).write_text(json.dumps(table), encoding="utf-8")
            (tree / "poe2-assistant/terms").mkdir(parents=True)
            (tree / "poe2-assistant/terms/source.json").write_text(json.dumps(
                {"task": "P03", "project_commit": "old", "files": {"mods.json": {"sha256": "x", "format": "f"}}}),
                encoding="utf-8")
            dest = up.export_pob_terms(loc, tree, "abc")
            source = json.loads((dest / "source.json").read_text(encoding="utf-8"))
            self.assertEqual(source["task"], "P03")
            self.assertEqual(source["project_commit"], "abc")
            self.assertEqual(sorted(source["files"]), sorted(up.POB_TERMS))
            mods = (dest / "mods.json").read_bytes()
            self.assertEqual(source["files"]["mods.json"]["sha256"], hashlib.sha256(mods).hexdigest())
            self.assertEqual(source["files"]["mods.json"]["pob_commit"], "p")
            self.assertEqual(source["files"]["gem_tooltips.json"]["format"], "poe2-gem-tooltips/1")

    def test_steps_in_order_offline(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(up, "run") as run:
            up.main(["--engine", "/e", "--offline", "--out-root", tmp, "--pobg", "/g"])
        scripts = [Path(str(c.args[0])).name for c in run.call_args_list]
        self.assertEqual(scripts, ["poe2db_terms.py", "poe2db_item_classes.py", "poe2db_keywords.py",
                                   "pob_localization.py", "poe2db_consistency.py"])
        self.assertEqual(run.call_args_list[0].kwargs["env"]["POE2DB_OFFLINE"], "1")

    def test_fetch_step_uses_the_shared_fetcher(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(up, "run") as run:
            up.main(["--engine", "/e", "--out-root", tmp, "--only", "fetch"])
        calls = [c.args for c in run.call_args_list]
        self.assertEqual(Path(str(calls[0][0])).name, "poe2db_fetch.py")
        self.assertIn("Keywords", calls[0])
        self.assertIn("Body_Armours_str", calls[0])   # sub pages from poe2db_terms.SUBPAGES
        self.assertEqual(calls[1][-1], "gems")


if __name__ == "__main__":
    unittest.main()
