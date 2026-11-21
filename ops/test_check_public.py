"""Tests for ops/check_public.py. Sample secrets below are made up; they are built from pieces so this
file itself stays clean when the checker scans the repository."""

from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_public as cp  # noqa: E402

HOME = "/ho" + "me/"
USERS = "C:" + "\\Users\\"


def kinds(text, terms=()):
    return [k for k, _, _ in cp.scan_text(text, terms)]


class Patterns(unittest.TestCase):
    def test_share_links_and_json_fields(self):
        self.assertEqual(kinds("https://www.wegame.com.cn/helper/poe2/#/share/" + "AbCdEf0123456789xyz"), ["share_link"])
        self.assertEqual(kinds('"openid"' + ': "o_9x8y7z6w"'), ["json_private_field"])
        self.assertEqual(kinds('"nick_name"' + ': "某玩家"'), ["json_private_field"])
        self.assertEqual(kinds('"role_id": "' + "123456789" + '"'), ["role_id"])
        self.assertEqual(kinds('"role_id"' + ': 12345678'), ["role_id"])

    def test_anonymised_values_pass(self):
        for text in ('"openid": "<removed>"', '"share_code": ""', '"role_id": "1"',
                     "https://www.wegame.com.cn/helper/poe2/#/share/<分享码>", "PRIVATE = ('openid', 'share_code')"):
            self.assertEqual(kinds(text), [], text)

    def test_cookies(self):
        self.assertEqual(kinds("POESESSID=" + "0123456789abcdef0123456789abcdef"), ["poesessid"])
        self.assertEqual(kinds("p_skey=" + "Xy12_ab-CD34"), ["login_cookie"])
        self.assertEqual(kinds("Cookie: " + "sessionid=abcdefgh12345"), ["cookie_header"])
        self.assertEqual(kinds("POESESSID cookie is never stored"), [])
        self.assertEqual(kinds("headers['Cookie'] = f'POESESSID={value}'"), [])

    def test_local_paths(self):
        self.assertEqual(kinds(USERS + "someone\\Documents"), ["windows_user_path"])
        self.assertEqual(kinds("C:/" + "Users/someone/x"), ["windows_user_path"])
        self.assertEqual(kinds(HOME + "someone/workspaces"), ["home_path"])
        self.assertEqual(kinds("/Users/" + "someone/x"), ["mac_user_path"])
        for text in (USERS + "<you>\\Documents", USERS + "…", "%USERPROFILE%", HOME + "<user>/x", "$HOME/.local", "~/x",
                     USERS + "Public\\x", "https://example.org/home/page"):
            self.assertEqual(kinds(text), [], text)

    def test_email(self):
        self.assertEqual(kinds("mail " + "someone" + "@" + "gmail.com"), ["email"])
        for text in ("Co-Authored-By: Claude <noreply@anthropic.com>", "a@example.com",
                     "1+x@users.noreply.github.com", "git@github.com:owner/repo.git"):
            self.assertEqual(kinds(text), [], text)

    def test_private_terms_case_insensitive(self):
        self.assertEqual(kinds("ssh build-HOST-7 uptime", ["Build-Host-7"]), ["private_term"])
        self.assertEqual(kinds("nothing here", ["Build-Host-7"]), [])


class Directory(unittest.TestCase):
    def test_scan_reports_files_large_files_and_skips_git_and_binary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            (root / ".git/config").write_text("url = " + HOME + "someone/x\n", encoding="utf-8")
            (root / "ok.md").write_text("clean\n", encoding="utf-8")
            (root / "bad.md").write_text("line\nsee " + HOME + "someone/x\n", encoding="utf-8")
            (root / "blob.bin").write_bytes(b"\0" + (HOME + "someone").encode())
            (root / "big.json").write_bytes(b"x" * 2048)
            (root / "host-7.txt").write_text("x\n", encoding="utf-8")
            files, findings = cp.check(root, ["host-7"], max_bytes=1024)
            self.assertEqual(files, 5)
            got = sorted((f["file"], f["kind"], f["line"]) for f in findings)
            self.assertEqual(got, [("bad.md", "home_path", 2), ("big.json", "large_file", 0),
                                   ("host-7.txt", "private_term_in_path", 0)])

    def test_exit_code_and_terms_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "tree"
            root.mkdir()
            (root / "a.txt").write_text("hello\n", encoding="utf-8")
            terms = Path(tmp) / "terms.txt"
            terms.write_text("# comment\nhello\n", encoding="utf-8")
            self.assertEqual(cp.load_terms(terms), ["hello"])
            self.assertEqual(cp.load_terms(Path(tmp) / "missing.txt"), [])
            self.assertEqual(cp.main([str(root), "--terms", str(terms)]), 1)
            self.assertEqual(cp.main([str(root), "--terms", str(Path(tmp) / "missing.txt")]), 0)


if __name__ == "__main__":
    unittest.main()
