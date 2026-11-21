"""Build the U01 trial package: Chinese PoB that starts the in-game assistant.

Layout (all paths relative to the package root):

    PoE2助手/
      启动中文PoB.cmd     entry point: Chinese PoB, which starts the assistant
      使用说明.txt
      版本.json           pinned commits and the Python download
      PoB/                localized PoB (P04/P07/P08) + assistant hook; also the trial engine
      assistant/          EE2 shell (S01/M07) + assistant-backend.json
      python/             official Python embeddable package
      backend/            scripts/, data/terms/poe2db-1.0, data/terms/pob-localization/passives.json, sources/pob.json
      pobg/               POBG (A01: PoE2 data and build tools over MCP) at sources/pobg.json's commit,
                          lib/ with its dependencies, run_pobg.py to start it with python/
      显示Claude配置.cmd  prints the line each Claude client needs

Rerunning replaces the folder and the ZIP.
"""

import argparse
import ast
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from hook_pob_assistant import install as install_hook  # noqa: E402

NAME = "PoE2助手"
PYTHON_VERSION = "3.12.10"  # last 3.12 release with an embeddable package
PYTHON_URL = f"https://www.python.org/ftp/python/{PYTHON_VERSION}/python-{PYTHON_VERSION}-embed-amd64.zip"
PYTHON_SHA256 = "4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3"
# Entry points the package runs: the assistant backend, and the WeGame converter PoB starts (U07).
# Every project module they import is copied too (backend_scripts), so a new module can't be missed.
BACKEND_ENTRIES = ("assistant_backend", "wegame_import")
BACKEND_FILES = ("pob_server.lua",)  # loaded by path, not imported
# PoB user state in the source copy; a fresh package starts without it.
POB_USER_STATE = {"Settings.xml", "Builds", "imgui.ini", "SimpleGraphic.cfg", "z.dll.original",
                  "Start-PoB-zh-CN.cmd", "Start-PoB-en.cmd"}
POB_EXE = "Path{space}of{space}Building-PoE2.exe"
LAUNCHER = (
    "@echo off\r\n"
    "rem Chinese PoB; it starts the in-game assistant in the background.\r\n"
    'set "POE2_ASSISTANT_LOCALE=zh-CN"\r\n'
    f'start "" /d "%~dp0PoB\\runtime" "%~dp0PoB\\runtime\\{POB_EXE}"\r\n'
)
BACKEND_CONFIG = {
    "command": "../python/python.exe",
    "args": ["-B", "backend/scripts/assistant_backend.py", "--engine", "PoB"],
    "cwd": "..",
}
# POBG (A01): what goes in, and how it starts. Its MCP server runs on the package's Python; the
# launcher puts lib/ on sys.path (the ._pth file leaves it out) and points POBG at the backend's PoB
# engine (P02 trial server) and PoB's user folder, so it can give the numbers of a build.
POBG_FILES = ("src", "data", "LICENSE", "README.md", "README.zh-CN.md", "README.zh-TW.md", "pyproject.toml")
POBG_LAUNCHER = r'''r"""Start POBG (PoE2 data and build tools, an MCP server on stdio) with this package's Python.

    Claude Code:  claude mcp add --scope user pobg -- "<package>\python\python.exe" "<package>\pobg\run_pobg.py"
"""
import os
import runpy
import sys
from pathlib import Path

here = Path(__file__).resolve().parent
package = here.parent
lib = here / "lib"
sys.path[:0] = [str(here), str(lib), str(lib / "win32"), str(lib / "win32" / "lib")]
os.environ.setdefault("POBG_ZH", "cn")
os.environ.setdefault("POE2_ASSISTANT_BACKEND", str(package / "backend" / "scripts"))
os.environ.setdefault("POE2_ASSISTANT_ENGINE", str(package / "PoB"))
os.environ.setdefault("POE2_ASSISTANT_POB_USER_DIR", str(package / "PoB" / "src"))
os.chdir(here)
runpy.run_module("src.tools.mcp_server", run_name="__main__", alter_sys=True)
'''
# ASCII only: cmd reads a batch file in the console code page. %J% is the folder with doubled
# backslashes, for JSON.
CLAUDE_CONFIG = (
    "@echo off\r\n"
    "rem Prints the line that adds this package's POBG to Claude Code or Claude Desktop.\r\n"
    'set "P=%~dp0"\r\n'
    'set "J=%P:\\=\\\\%"\r\n'
    "echo Claude Code - run in a terminal:\r\n"
    'echo claude mcp add --scope user pobg -- "%P%python\\python.exe" "%P%pobg\\run_pobg.py"\r\n'
    "echo.\r\n"
    "echo Claude Desktop - add to mcpServers in claude_desktop_config.json, then restart it:\r\n"
    'echo "pobg": {"command": "%J%python\\\\python.exe", "args": ["%J%pobg\\\\run_pobg.py"]}\r\n'
    "echo.\r\n"
    "pause\r\n"
)

README = """PoE2 助手（U01 试用包）

用法
1. 先退出旧版助手（托盘图标 → 退出），以免两个助手抢快捷键。
2. 双击“启动中文PoB.cmd”。PoB 以简体中文打开，游戏内助手在后台启动，托盘里出现它的图标。
3. 在 PoB 里打开（或导入）要用的 BD。助手评估的是 PoB 当前打开的 BD，没保存的修改也算在内；
   PoB 关着时用最近打开的 BD 文件。BD 默认存在 PoB\\src\\Builds，可在 PoB 的“选项”里改 BD 目录。
4. 进游戏，鼠标指向背包、仓库或市集里的装备，按 Ctrl+Shift+D，弹出中文评估浮层。
   腾讯服需要管理员权限时，助手会提示，点按钮经 UAC 以管理员重启。
5. 关掉 PoB，助手随之退出。

在 Claude 里问 BD（POBG）
- 双击“显示Claude配置.cmd”，按提示把一行配置加到 Claude Code 或 Claude 桌面版，重启 Claude。
- 之后可以用中文问：技能、天赋、装备词缀、章节与引路石；让它出一个 BD（带 PoB 导入码）；
  或问“我 PoB 里当前 BD 的 DPS 和抗性”。数字由包里的 PoB 引擎计算：PoB 开着时用当前打开的 BD
  （含未保存的修改），关着时用最近打开的 BD 文件。
- 资料来自 poe2db.tw（简体中文，CC BY-NC-SA）、Path of Building 与 poe.ninja，见 pobg\\README.zh-CN.md。

说明
- 包里自带 Python（官方嵌入版），不需要另装。
- 助手的设置和日志在 %APPDATA%\\exiled-exchange-2，与旧版助手共用。
- 不要把这个文件夹放在需要管理员权限才能写入的位置（如 C:\\Program Files）。
"""


def run(*args):
    return subprocess.check_output(args, text=True).strip()


def backend_scripts(scripts=ROOT / "scripts", entries=BACKEND_ENTRIES):
    """File names of the entry modules and every project module they import, directly or not."""
    local = {path.stem for path in scripts.glob("*.py")}
    found, todo = set(), list(entries)
    while todo:
        module = todo.pop()
        if module in found:
            continue
        found.add(module)
        for node in ast.walk(ast.parse((scripts / f"{module}.py").read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                names = [node.module]
            else:
                continue
            todo += [name.split(".")[0] for name in names if name.split(".")[0] in local]
    return tuple(sorted(f"{module}.py" for module in found))


def python_zip(cache):
    path = cache / PYTHON_URL.rsplit("/", 1)[1]
    if not path.is_file():
        cache.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(PYTHON_URL) as response:
            path.write_bytes(response.read())
    with path.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != PYTHON_SHA256:
            raise ValueError(f"{path} 的 SHA-256 与固定值不符")
    return path


def pobg_lib(cache, requirements):
    """POBG's dependencies for the package's Python (Windows x64, CPython 3.12), installed once per
    requirement list into the cache with pip: wheels only, exact versions, no dependency resolution."""
    key = hashlib.sha256("\n".join(requirements).encode("utf-8")).hexdigest()[:12]
    target = cache / f"pobg-lib-{key}"
    if not target.is_dir():
        partial = cache / f"pobg-lib-{key}.partial"
        shutil.rmtree(partial, ignore_errors=True)
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--no-deps",
                               "--only-binary=:all:", "--platform", "win_amd64", "--implementation", "cp",
                               "--python-version", PYTHON_VERSION.rsplit(".", 1)[0], "--target", str(partial),
                               *requirements])
        partial.rename(target)
    return target


def install_pobg(package, checkout, lib, commit):
    """POBG's tracked files at `commit` (from a clean checkout of it), its lib/ and the launcher."""
    head = run("git", "-C", str(checkout), "rev-parse", "HEAD")
    if head != commit or run("git", "-C", str(checkout), "status", "--porcelain"):
        raise ValueError(f"{checkout} 必须是 sources/pobg.json 固定提交 {commit} 的干净检出（现在是 {head}）")
    target = package / "pobg"
    tar = subprocess.check_output(["git", "-C", str(checkout), "archive", "--format=tar", commit, *POBG_FILES])
    with tarfile.open(fileobj=io.BytesIO(tar)) as archive:
        archive.extractall(target, filter="data")
    shutil.copytree(lib, target / "lib", ignore=shutil.ignore_patterns("__pycache__", "*.chm"))
    (target / "run_pobg.py").write_text(POBG_LAUNCHER, encoding="utf-8")
    (package / "显示Claude配置.cmd").write_bytes(CLAUDE_CONFIG.encode("ascii"))


def copy_pob(source, target, commit):
    def ignore(directory, names):
        return {name for name in names if name in POB_USER_STATE}
    shutil.copytree(source, target, ignore=ignore)
    (target / "src/Builds").mkdir(exist_ok=True)
    # The pinned commit, or the poe2-assistant branch head (sources/pob-branch.md); the trial
    # engine accepts either.
    (target / ".pob-commit").write_text(commit + "\n", encoding="utf-8")
    install_hook(target)


def build(pob, assistant, ee2_commit, out, cache, pobg, pob_commit=None, make_zip=True):
    package = out / NAME
    if package.exists():
        shutil.rmtree(package)
    package.mkdir(parents=True)
    pin = json.loads((ROOT / "sources/pob.json").read_text(encoding="utf-8"))
    pob_commit = pob_commit or pin["commit"]

    with zipfile.ZipFile(python_zip(cache)) as archive:
        archive.extractall(package / "python")
    # The ._pth file replaces sys.path and leaves out the script's directory.
    pth = package / f"python/python{PYTHON_VERSION.replace('.', '')[:3]}._pth"
    pth.write_text(pth.read_text(encoding="utf-8").replace(".\n", ".\n../backend/scripts\n", 1), encoding="utf-8")
    copy_pob(pob, package / "PoB", pob_commit)
    shutil.copytree(assistant, package / "assistant")
    (package / "assistant/assistant-backend.json").write_text(
        json.dumps(BACKEND_CONFIG, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    backend = package / "backend"
    (backend / "scripts").mkdir(parents=True)
    for name in backend_scripts() + BACKEND_FILES:
        shutil.copy2(ROOT / "scripts" / name, backend / "scripts" / name)
    shutil.copytree(ROOT / "data/terms/poe2db-1.0", backend / "data/terms/poe2db-1.0")
    (backend / "data/terms/pob-localization").mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "data/terms/pob-localization/passives.json", backend / "data/terms/pob-localization/passives.json")  # U07 anoints
    (backend / "sources").mkdir()
    for name in ("pob.json", "pob-branch.json"):
        shutil.copy2(ROOT / "sources" / name, backend / "sources" / name)
    pobg_pin = json.loads((ROOT / "sources/pobg.json").read_text(encoding="utf-8"))
    install_pobg(package, pobg, pobg_lib(cache, pobg_pin["requirements"]), pobg_pin["commit"])

    (package / "启动中文PoB.cmd").write_bytes(LAUNCHER.encode("ascii"))
    (package / "使用说明.txt").write_text(README.replace("\n", "\r\n"), encoding="utf-8-sig")
    versions = {
        "project_commit": run("git", "-C", str(ROOT), "rev-parse", "HEAD"),
        "project_dirty": bool(run("git", "-C", str(ROOT), "status", "--porcelain")),
        "pob_commit": pob_commit,
        "ee2_commit": ee2_commit,
        "pobg_commit": pobg_pin["commit"],
        "python": {"version": PYTHON_VERSION, "url": PYTHON_URL, "sha256": PYTHON_SHA256},
    }
    (package / "版本.json").write_text(json.dumps(versions, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    archive = out / f"{NAME}-U01.zip"
    archive.unlink(missing_ok=True)
    if not make_zip:
        return package, None
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for path in sorted(package.rglob("*")):
            bundle.write(path, path.relative_to(out).as_posix())
    return package, archive


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pob", type=Path, required=True, help="已装好 P04/P07/P08 汉化的固定 PoB 目录")
    parser.add_argument("--assistant", type=Path, required=True, help="EE2 win-unpacked 目录")
    parser.add_argument("--ee2-commit", required=True, help="构建 --assistant 的 EE2 提交")
    parser.add_argument("--pobg", type=Path, required=True, help="POBG 的干净检出，HEAD 为 sources/pobg.json 的固定提交")
    parser.add_argument("--out", type=Path, required=True, help="输出目录（生成 PoE2助手/ 和 ZIP）")
    parser.add_argument("--cache", type=Path, help="Python 嵌入版下载缓存，默认 <out>/cache")
    parser.add_argument("--pob-commit", help="--pob 来自 poe2-assistant 分支导出时，填分支头（见 sources/pob-branch.json）")
    parser.add_argument("--no-zip", action="store_true", help="只生成文件夹，不打 ZIP")
    args = parser.parse_args()
    package, archive = build(args.pob.resolve(), args.assistant.resolve(), args.ee2_commit,
                             args.out.resolve(), (args.cache or args.out / "cache").resolve(),
                             args.pobg.resolve(), args.pob_commit, not args.no_zip)
    size = sum(path.stat().st_size for path in package.rglob("*") if path.is_file())
    print(f"{package}  {size / 2**20:.0f} MiB")
    if archive:
        print(f"{archive}  {archive.stat().st_size / 2**20:.0f} MiB")


if __name__ == "__main__":
    main()
