"""R04: the release script reads its pins and fills the release notes."""
import tempfile
from pathlib import Path
import unittest

import release_build


class ReleaseBuildTests(unittest.TestCase):
    def test_pins_name_github_forks_and_full_commits(self):
        pins = release_build.pins()
        self.assertEqual(set(pins), {"pob", "ee2", "pobg"})
        for repository, commit in pins.values():
            self.assertRegex(repository, r"^https://github\.com/Michael-crazy/[\w.-]+\.git$")
            self.assertRegex(commit, r"^[0-9a-f]{40}$")

    def test_notes_carry_version_changes_checksums_and_no_placeholder(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            (out / "SHA256SUMS.txt").write_text("abc  PoE2-Assistant-v9.9.9.zip\n", encoding="utf-8")
            version, date = release_build.package.release_version()
            text = release_build.notes(out, version, date, reused=True).read_text(encoding="utf-8")
            self.assertIn(f"PoE2-Assistant-v{version}.zip", text)
            self.assertIn("abc  PoE2-Assistant-v9.9.9.zip", text)
            self.assertIn("不需要重新下载助手", text)
            self.assertIn("已保护你的电脑", text)
            self.assertNotRegex(text, r"\{(version|date|changes|checksums|assistant)\}")
            self.assertNotIn("VERSION[", text)
            for word in ("镜像", "国内下载", "网盘"):
                self.assertNotIn(word, text)


if __name__ == "__main__":
    unittest.main()
