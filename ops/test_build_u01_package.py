"""The trial package must carry every project module its Python entry points import, and POBG."""
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest
from unittest import mock

import build_u01_package as package


class BackendScriptsTests(unittest.TestCase):
    def test_follows_imports_transitively(self):
        with tempfile.TemporaryDirectory() as directory:
            scripts = Path(directory)
            (scripts / "entry.py").write_text("import json\nimport middle\n", encoding="utf-8")
            (scripts / "middle.py").write_text("from leaf import x\n", encoding="utf-8")
            (scripts / "leaf.py").write_text("x = 1\n", encoding="utf-8")
            (scripts / "unused.py").write_text("", encoding="utf-8")
            self.assertEqual(package.backend_scripts(scripts, ("entry",)), ("entry.py", "leaf.py", "middle.py"))

    def test_copied_backend_imports_cleanly(self):
        # Regression: U06 added pob_command.py, the hand-written list missed it, and the
        # packaged backend died on import. Import the entry points from a copy of only these files.
        with tempfile.TemporaryDirectory() as directory:
            backend = Path(directory) / "backend"  # same layout as the package: backend/{scripts,sources}
            (backend / "scripts").mkdir(parents=True)
            (backend / "sources").mkdir()
            for name in package.backend_scripts() + package.BACKEND_FILES:
                (backend / "scripts" / name).write_bytes((package.ROOT / "scripts" / name).read_bytes())
            for name in ("pob.json", "pob-branch.json"):
                (backend / "sources" / name).write_bytes((package.ROOT / "sources" / name).read_bytes())
            for entry in package.BACKEND_ENTRIES:
                result = subprocess.run([sys.executable, "-B", "-c", f"import {entry}"], cwd=backend / "scripts",
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)



def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def fake_pobg(root):
    """A POBG checkout: an MCP server module that reports how it was started, plus files left out."""
    server = root / "src/tools/mcp_server.py"
    server.parent.mkdir(parents=True)
    (root / "src/__init__.py").write_text("", encoding="utf-8")
    (root / "src/tools/__init__.py").write_text("", encoding="utf-8")
    server.write_text(
        "import json, os, sys\n"
        "import helper\n"
        "keys = ('POBG_ZH', 'POE2_ASSISTANT_BACKEND', 'POE2_ASSISTANT_ENGINE', 'POE2_ASSISTANT_POB_USER_DIR')\n"
        "print(json.dumps({'name': __name__, 'cwd': os.getcwd(), 'helper': helper.VALUE,\n"
        "                  'env': {k: os.environ.get(k) for k in keys}}))\n", encoding="utf-8")
    for name in ("LICENSE", "README.md", "README.zh-CN.md", "README.zh-TW.md", "pyproject.toml"):
        (root / name).write_text(name, encoding="utf-8")
    (root / "data/zh_cn").mkdir(parents=True)
    (root / "data/zh_cn/a.json").write_text("{}", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests/test_x.py").write_text("", encoding="utf-8")
    git("init", "-q", cwd=root)
    git("add", "-A", cwd=root)
    git("-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "pobg", cwd=root)
    return git("rev-parse", "HEAD", cwd=root)


class PobgTests(unittest.TestCase):
    def test_pin_lists_exact_requirements(self):
        pin = json.loads((package.ROOT / "sources/pobg.json").read_text(encoding="utf-8"))
        self.assertRegex(pin["commit"], r"^[0-9a-f]{40}$")
        self.assertTrue(all(re.fullmatch(r"[A-Za-z0-9_.-]+==[0-9][0-9A-Za-z.]*", r) for r in pin["requirements"]))
        self.assertTrue({"mcp", "networkx", "requests", "beautifulsoup4", "pywin32"}
                        <= {r.split("==")[0] for r in pin["requirements"]})

    def test_installs_tracked_files_lib_and_a_launcher_that_starts_the_server(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkout, pkg, lib = root / "pobg-src", root / "PoE2助手", root / "lib"
            checkout.mkdir()
            commit = fake_pobg(checkout)
            (lib / "__pycache__").mkdir(parents=True)
            (lib / "helper.py").write_text("VALUE = 'from lib'\n", encoding="utf-8")
            (lib / "__pycache__/helper.cpython-312.pyc").write_bytes(b"")
            (lib / "PyWin32.chm").write_bytes(b"")
            pkg.mkdir()
            package.install_pobg(pkg, checkout, lib, commit)
            pobg = pkg / "pobg"
            self.assertEqual(sorted(p.name for p in pobg.iterdir()),
                             ["LICENSE", "README.md", "README.zh-CN.md", "README.zh-TW.md", "data", "lib",
                              "pyproject.toml", "run_pobg.py", "src"])
            self.assertTrue((pobg / "data/zh_cn/a.json").is_file())
            self.assertEqual(sorted(p.name for p in (pobg / "lib").iterdir()), ["helper.py"])
            cmd = (pkg / "显示Claude配置.cmd").read_bytes().decode("ascii")
            self.assertIn('claude mcp add --scope user pobg -- "%P%python\\python.exe" "%P%pobg\\run_pobg.py"', cmd)
            self.assertIn('"args": ["%J%pobg\\\\run_pobg.py"]', cmd)
            result = subprocess.run([sys.executable, "-B", str(pobg / "run_pobg.py")], capture_output=True,
                                    text=True, env={k: v for k, v in os.environ.items() if not k.startswith(("POBG", "POE2_"))})
            self.assertEqual(result.returncode, 0, result.stderr)
            started = json.loads(result.stdout)
            self.assertEqual((started["name"], started["helper"]), ("__main__", "from lib"))
            self.assertEqual(Path(started["cwd"]), pobg.resolve())
            self.assertEqual(started["env"], {"POBG_ZH": "cn",
                                              "POE2_ASSISTANT_BACKEND": str((pkg / "backend/scripts").resolve()),
                                              "POE2_ASSISTANT_ENGINE": str((pkg / "PoB").resolve()),
                                              "POE2_ASSISTANT_POB_USER_DIR": str((pkg / "PoB/src").resolve())})

    def test_refuses_a_checkout_that_is_not_the_pinned_commit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "pobg-src").mkdir()
            commit = fake_pobg(root / "pobg-src")
            with self.assertRaisesRegex(ValueError, "固定提交"):
                package.install_pobg(root / "pkg", root / "pobg-src", root / "lib", "0" * 40)
            (root / "pobg-src/README.md").write_text("changed", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "干净检出"):
                package.install_pobg(root / "pkg", root / "pobg-src", root / "lib", commit)

    def test_lib_is_installed_once_per_requirement_list(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            calls = []

            def fake_pip(args):
                calls.append(args)
                Path(args[args.index("--target") + 1]).mkdir(parents=True)
            with mock.patch.object(package.subprocess, "check_call", fake_pip):
                first = package.pobg_lib(cache, ["mcp==2.3.0"])
                again = package.pobg_lib(cache, ["mcp==2.3.0"])
            self.assertEqual(first, again)
            self.assertTrue(first.is_dir() and len(calls) == 1)
            args = calls[0]
            for flag in ("--no-deps", "--only-binary=:all:"):
                self.assertIn(flag, args)
            self.assertEqual(args[args.index("--platform") + 1], "win_amd64")
            self.assertEqual(args[args.index("--python-version") + 1], "3.12")
            self.assertEqual(args[-1], "mcp==2.3.0")


if __name__ == "__main__":
    unittest.main()
