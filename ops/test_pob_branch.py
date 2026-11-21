import tempfile
from pathlib import Path
import unittest

from pob_branch import compare


class CompareTests(unittest.TestCase):
    def test_reports_each_kind_of_difference_and_skips_git_and_ignored_files(self):
        with tempfile.TemporaryDirectory() as left, tempfile.TemporaryDirectory() as right:
            left, right = Path(left), Path(right)
            for root in (left, right):
                (root / "src").mkdir()
                (root / "src/same.lua").write_text("x = 1\n")
                (root / ".git").mkdir()
                (root / ".git/HEAD").write_text(str(root))
            (left / "src/changed.lua").write_text("a\n")
            (right / "src/changed.lua").write_text("b\n")
            (left / "runtime.bak").write_text("old")
            (left / "only.txt").write_text("l")
            (right / "new.json").write_text("{}")
            report = compare(left, right, ignore={"runtime.bak"})
            self.assertEqual(report, {"only_left": ["only.txt"], "only_right": ["new.json"],
                                      "different": ["src/changed.lua"], "same": 1})


if __name__ == "__main__":
    unittest.main()
