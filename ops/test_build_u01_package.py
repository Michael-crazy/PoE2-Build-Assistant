"""The release package must carry every project module its Python entry points import, POBG, and an
update manifest for the official PoB release layout (R02)."""
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest
from unittest import mock
import xml.etree.ElementTree as ET
import zipfile

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
            # pkg: PoB/ of the release layout, which holds pobg/ and python/.
            checkout, pkg, lib = root / "pobg-src", root / "PoE2助手" / "PoB", root / "lib"
            checkout.mkdir()
            commit = fake_pobg(checkout)
            (lib / "__pycache__").mkdir(parents=True)
            (lib / "helper.py").write_text("VALUE = 'from lib'\n", encoding="utf-8")
            (lib / "__pycache__/helper.cpython-312.pyc").write_bytes(b"")
            (lib / "PyWin32.chm").write_bytes(b"")
            pkg.mkdir(parents=True)
            package.install_pobg(pkg, checkout, lib, commit)
            pobg = pkg / "pobg"
            self.assertEqual(sorted(p.name for p in pobg.iterdir()),
                             ["LICENSE", "README.md", "README.zh-CN.md", "README.zh-TW.md", "data", "lib",
                              "mcp_config.py", "pyproject.toml", "run_pobg.py", "src"])
            self.assertTrue((pobg / "data/zh_cn/a.json").is_file())
            self.assertEqual(sorted(p.name for p in (pobg / "lib").iterdir()), ["helper.py"])
            # V10 #24: the configurations for Claude and other clients, with the package's paths.
            shown = subprocess.run([sys.executable, "-B", "-I", str(pobg / "mcp_config.py")], capture_output=True,
                                   env=dict(os.environ, PYTHONIOENCODING="utf-8"))
            self.assertEqual(shown.returncode, 0, shown.stderr)
            text = (pkg / "MCP配置.txt").read_text(encoding="utf-8-sig")
            self.assertEqual(shown.stdout.decode("utf-8").splitlines()[:-1], text.splitlines())
            python, launcher = str(pkg.resolve() / "python" / "python.exe"), str(pobg.resolve() / "run_pobg.py")
            self.assertIn(f'claude mcp add --scope user pobg -- "{python}" "{launcher}"', text)
            for client in ("Cursor", "VS Code", "Gemini CLI", "Codex CLI", "ChatGPT", "Cherry Studio"):
                self.assertIn(f"== {client}", text)
            blocks = [json.loads(b) for b in re.findall(r"^\{\n.*?^\}$", text, re.M | re.S)]
            server = {"command": python, "args": [launcher]}
            self.assertEqual([next(iter(b)) for b in blocks], ["mcpServers", "mcpServers", "servers"])
            self.assertEqual(blocks[0]["mcpServers"]["pobg"], server)
            self.assertEqual(blocks[2]["servers"]["pobg"], {"type": "stdio", **server})
            self.assertIn(f"command = '{python}'\nargs = ['{launcher}']", text)
            result = subprocess.run([sys.executable, "-B", str(pobg / "run_pobg.py")], capture_output=True,
                                    text=True, env={k: v for k, v in os.environ.items() if not k.startswith(("POBG", "POE2_"))})
            self.assertEqual(result.returncode, 0, result.stderr)
            started = json.loads(result.stdout)
            self.assertEqual((started["name"], started["helper"]), ("__main__", "from lib"))
            self.assertEqual(Path(started["cwd"]), pobg.resolve())
            self.assertEqual(started["env"], {"POBG_ZH": "cn",
                                              "POE2_ASSISTANT_BACKEND": str((pkg / "backend/scripts").resolve()),
                                              "POE2_ASSISTANT_ENGINE": str(pkg.resolve()),
                                              "POE2_ASSISTANT_POB_USER_DIR": str(pkg.resolve())})

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


LAUNCH = """function launch:OnInit()
\tlocal x = 1

\tif not self.devMode and not firstRunFile then
\t\tself:CheckForUpdate(true)
\tend
end
"""


def fake_pob_export(root):
    """A PoB branch export in the repository layout, with user state and developer files to leave out."""
    files = {
        "changelog.txt": "VERSION[0.23.1][2026/07/28]\n", "help.txt": "help", "LICENSE.md": "MIT",
        "README.md": "readme", "Start-PoB-zh-CN.cmd": "x", "spec/a.lua": "x",
        "src/Launch.lua": LAUNCH, "src/UpdateCheck.lua": "u", "src/HeadlessWrapper.lua": "h",
        "src/Modules/Main.lua": "m", "src/TreeData/0_4/tree.lua": "t", "src/Export/x.lua": "dev",
        "src/Settings.xml": "user", "src/Builds/My Build.xml": "user",
        "runtime/Path{space}of{space}Building-PoE2.exe": "exe", "runtime/Update.exe": "upd",
        "runtime/msvcr100.dll": "crt", "runtime/lua51.dll": "lua", "runtime/lua/xml.lua": "xml",
        "runtime/SimpleGraphic.cfg": "user", "poe2-assistant/package-mode.txt": "#",
        "poe2-assistant/terms/source.json": "{}",
    }
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")


class ReleaseLayoutTests(unittest.TestCase):
    def test_pob_is_laid_out_flat_without_user_state_or_developer_files(self):
        with tempfile.TemporaryDirectory() as directory:
            source, pob = Path(directory) / "export", Path(directory) / "PoB"
            fake_pob_export(source)
            parts = package.layout_pob(source, pob, "c" * 40)
            names = sorted(p.relative_to(pob).as_posix() for p in pob.rglob("*") if p.is_file())
            self.assertEqual(names, [".pob-commit", "HeadlessWrapper.lua", "LICENSE.md", "Launch.lua",
                                     "Modules/Main.lua", "Path of Building-PoE2.exe", "TreeData/0_4/tree.lua",
                                     "Update.exe", "UpdateCheck.lua", "changelog.txt", "help.txt", "lua/xml.lua",
                                     "lua51.dll", "msvcr100.dll", "poe2-assistant/package-mode.txt",
                                     "poe2-assistant/terms/source.json"])
            self.assertEqual((parts["Path of Building-PoE2.exe"], parts["lua/xml.lua"], parts["TreeData/0_4/tree.lua"],
                              parts["Launch.lua"], parts["help.txt"]), ("runtime", "runtime", "tree", "program", "default"))
            self.assertIn('GetRuntimePath() .. "/assistant-app/Exiled Exchange 2.exe"', (pob / "Launch.lua").read_text(encoding="utf-8"))

    def test_manifest_parts_sources_and_names(self):
        with tempfile.TemporaryDirectory() as directory:
            source, pob = Path(directory) / "export", Path(directory) / "PoB"
            fake_pob_export(source)
            parts = package.layout_pob(source, pob, "c" * 40)
            for name in ("assistant-app/Exiled Exchange 2.exe", "assistant-app/assistant-backend.json", "python/python.exe",
                         "pobg/lib/x.pyd", "pobg/src/a.py", "backend/scripts/a.py", "版本.json"):
                (pob / name).parent.mkdir(parents=True, exist_ok=True)
                (pob / name).write_bytes(name.encode("utf-8"))
            text, files = package.manifest(pob, parts, "0.1.0", "assistant-release", "http://x/{branch}/",
                                           "http://y/v0.1.0/assistant-abc.zip")
            root = ET.fromstring(text)
            self.assertEqual(root.find("Version").attrib, {"number": "0.1.0", "platform": "win32", "branch": "assistant-release"})
            sources = {s.get("part"): (s.get("url"), s.get("platform")) for s in root.iter("Source")}
            self.assertEqual(sources["assistant"], ("http://y/v0.1.0/assistant-abc.zip", None))
            self.assertEqual(sources["runtime"], ("http://x/{branch}/", "win32"))
            self.assertEqual(set(sources), {"default", "program", "tree", "runtime", "backend", "python", "assistant"})
            entries = {f.get("name"): f.get("part") for f in root.iter("File")}
            self.assertEqual(entries["assistant-app/Exiled{space}Exchange{space}2.exe"], "assistant")
            self.assertEqual(entries["Path{space}of{space}Building-PoE2.exe"], "runtime")
            self.assertEqual((entries["assistant-app/assistant-backend.json"], entries["python/python.exe"],
                              entries["pobg/lib/x.pyd"], entries["pobg/src/a.py"], entries["版本.json"]),
                             ("backend", "python", "python", "backend", "backend"))
            self.assertNotIn("Update.exe", entries)
            self.assertNotIn("msvcr100.dll", entries)
            sha1 = {f.get("name"): f.get("sha1") for f in root.iter("File")}
            self.assertEqual(sha1["版本.json"], hashlib.sha1("版本.json".encode("utf-8")).hexdigest())

    def test_version_comes_from_the_newest_changelog_entry(self):
        version, date = package.release_version()
        self.assertRegex(version, r"^\d+\.\d+\.\d+$")
        self.assertRegex(date, r"^\d{4}/\d{2}/\d{2}$")
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "changelog.txt"
            log.write_text("VERSION[0.2.0][2027/01/02]\n* b\n\nVERSION[0.1.0][2026/11/21]\n* a\n", encoding="utf-8")
            self.assertEqual(package.release_version(log), ("0.2.0", "2027/01/02"))

    def test_assistant_zip_round_trips_with_manifest_names(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "a/assistant-app/resources").mkdir(parents=True)
            (root / "a/assistant-app/Exiled Exchange 2.exe").write_bytes(b"exe")
            (root / "a/assistant-app/resources/app.asar").write_bytes(b"asar")
            files = ["assistant-app/Exiled Exchange 2.exe", "assistant-app/resources/app.asar"]
            package.write_zip(root / "z.zip", [(package.manifest_name(n), root / "a" / n) for n in files])
            with zipfile.ZipFile(root / "z.zip") as archive:
                self.assertEqual(sorted(archive.namelist()), ["assistant-app/Exiled{space}Exchange{space}2.exe",
                                                              "assistant-app/resources/app.asar"])
            package.install_assistant(root / "b", None, root / "z.zip")
            self.assertEqual((root / "b/assistant-app/Exiled Exchange 2.exe").read_bytes(), b"exe")
            first = (root / "z.zip").read_bytes()
            package.write_zip(root / "z.zip", [(package.manifest_name(n), root / "a" / n) for n in files])
            self.assertEqual((root / "z.zip").read_bytes(), first)


if __name__ == "__main__":
    unittest.main()
