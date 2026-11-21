"""Build the release package: Chinese PoB that starts the in-game assistant and updates itself.

Layout (R02: PoB in the official portable layout, everything else inside it so PoB's own updater
can replace any file; all paths relative to the package root):

    PoE2助手/
      启动中文PoB.cmd     entry point: Chinese PoB, which starts the assistant
      显示MCP配置.cmd     prints how to add POBG to Claude and other MCP clients (V10 #24)
      使用说明.txt
      PoB/                PoB as an official release lays it out: the repository's src/, runtime/
                          and changelog/help/licence side by side, manifest.xml with version,
                          branch and platform (update checks on, user data next to the scripts)
        poe2-assistant/   package marker, term tables (from the PoB branch)
        assistant-app/    EE2 shell (S01/M07) + assistant-backend.json (not "assistant/": PoB keeps
                          the player's live build and WeGame files in <user dir>/Assistant, and
                          Windows names are case-insensitive)
        python/           official Python embeddable package
        backend/          scripts/, data/terms/poe2db-1.0, data/terms/pob-localization/passives.json, sources/
        pobg/             POBG (A01) at sources/pobg.json's commit, lib/ with its dependencies,
                          run_pobg.py to start it with python/, mcp_config.py to print client settings
        licenses/         this project's licence, third-party notices, the data licence
        版本.json         version and pinned commits
        Builds/, Settings.xml ...   the player's data, created by PoB; never in the manifest

Outputs in --out: the folder, `PoE2助手-v<version>.zip`, `release-branch/` (what the release branch
holds: every manifest file but the assistant's, plus manifest.xml), `assistant-<EE2 commit>.zip`
(the assistant part, only when built from --assistant) and SHA256SUMS.txt.

The manifest's parts (UpdateCheck.lua): default/program/tree/runtime as upstream, backend (our scripts,
POBG sources, docs) and python (python/, pobg/lib) from the release branch, assistant (EE2) from the
assistant zip on a GitHub Release. runtime, python and assistant files are replaced after PoB exits.
Rerunning replaces every output.
"""

import argparse
import ast
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import xml.etree.ElementTree as ET
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
                  "Start-PoB-zh-CN.cmd", "Start-PoB-en.cmd", "first.run", "installed.cfg"}
# What an official release takes from the repository (PoB's manifest.cfg): root files, src/ but
# its developer tools, runtime/. We keep HeadlessWrapper.lua and _SimpleGraphic.def.lua: the backend
# runs PoB headless with them (P02).
POB_ROOT_FILES = ("changelog.txt", "help.txt", "LICENSE.md")
POB_SRC_SKIP = {"Export", "LaunchInstall.lua", "luacov.stats.out", "poe_api_response.json"}
# Shipped but not in the manifest, like upstream: Update.exe applies runtime updates and cannot
# replace itself (nor the C runtime it loads).
POB_UNMANAGED = {"Update.exe", "msvcr100.dll"}
POB_EXE = "Path of Building-PoE2.exe"
ASSISTANT_DIR = "assistant-app"
RELEASE_BRANCH = "assistant-release"
RAW_BASE = "https://raw.githubusercontent.com/Michael-crazy/PathOfBuilding-PoE2/{branch}/"
RELEASE_BASE = "https://github.com/Michael-crazy/PoE2-Build-Assistant/releases/download"
CHANGELOG = ROOT / "release/changelog.txt"
LAUNCHER = (
    "@echo off\r\n"
    "rem Chinese PoB; it starts the in-game assistant in the background.\r\n"
    'set "POE2_ASSISTANT_LOCALE=zh-CN"\r\n'
    f'start "" /d "%~dp0PoB" "%~dp0PoB\\{POB_EXE}"\r\n'
)
BACKEND_CONFIG = {
    "command": "../python/python.exe",
    "args": ["-B", "backend/scripts/assistant_backend.py", "--engine", "."],
    "cwd": "..",
}
# POBG (A01): what goes in, and how it starts. Its MCP server runs on the package's Python; the
# launcher puts lib/ on sys.path (the ._pth file leaves it out) and points POBG at the backend's PoB
# engine (P02 trial server) and PoB's user folder (PoB/ itself in the release layout).
POBG_FILES = ("src", "data", "LICENSE", "README.md", "README.zh-CN.md", "README.zh-TW.md", "pyproject.toml")
POBG_LAUNCHER = r'''r"""Start POBG (PoE2 data and build tools, an MCP server on stdio) with this package's Python.

    Claude Code:  claude mcp add --scope user pobg -- "<package>\PoB\python\python.exe" "<package>\PoB\pobg\run_pobg.py"
"""
import os
import runpy
import sys
from pathlib import Path

here = Path(__file__).resolve().parent
pob = here.parent
lib = here / "lib"
sys.path[:0] = [str(here), str(lib), str(lib / "win32"), str(lib / "win32" / "lib")]
os.environ.setdefault("POBG_ZH", "cn")
os.environ.setdefault("POE2_ASSISTANT_BACKEND", str(pob / "backend" / "scripts"))
os.environ.setdefault("POE2_ASSISTANT_ENGINE", str(pob))
os.environ.setdefault("POE2_ASSISTANT_POB_USER_DIR", str(pob))
os.chdir(here)
runpy.run_module("src.tools.mcp_server", run_name="__main__", alter_sys=True)
'''
# ASCII only: cmd reads a batch file in the console code page. The text (Chinese, JSON with escaped
# paths) comes from mcp_config.py on the package's Python, which also saves it to MCP配置.txt.
MCP_CONFIG_NAME = "显示MCP配置.cmd"
MCP_CONFIG = (
    "@echo off\r\n"
    "rem Prints how to add this package's POBG (MCP server) to Claude and other AI clients.\r\n"
    '"%~dp0PoB\\python\\python.exe" -I "%~dp0PoB\\pobg\\mcp_config.py"\r\n'
    "pause\r\n"
)

README = """PoE2 助手 v{version}

用法
1. 先退出旧版助手（托盘图标 → 退出），以免两个助手抢快捷键。
2. 双击“启动中文PoB.cmd”。PoB 以简体中文打开，游戏内助手在后台启动，托盘里出现它的图标。
3. 在 PoB 里打开（或导入）要用的 BD。助手评估的是 PoB 当前打开的 BD，没保存的修改也算在内；
   PoB 关着时用最近打开的 BD 文件。BD 默认存在 PoB\\Builds，可在 PoB 的“选项”里改 BD 目录。
4. 进游戏，鼠标指向背包、仓库或市集里的装备，按 Ctrl+Shift+D，弹出中文评估浮层。
   腾讯服需要管理员权限时，助手会提示，点按钮经 UAC 以管理员重启。
5. 关掉 PoB，助手随之退出。

更新
- PoB 启动时在后台检查更新，左下角出现“更新已就绪”时点它，再点“更新”。PoB 会关闭、替换文件后自动重开；
  也可以点左下角“检查更新”手动检查。左下角显示当前版本号。
- 更新只替换程序文件，你的 BD（PoB\\Builds）和设置（PoB\\Settings.xml、助手设置）不受影响。
- 助手有新版本时要下载一个较大的文件（约 150 MB），只改 PoB 时只下载改动的文件。

在 AI 助手里问 BD（POBG，MCP）
- 双击“显示MCP配置.cmd”，按你用的客户端照着加一次配置，重启客户端。列出了 Claude Code、Claude 桌面版、
  Cursor、VS Code、Gemini CLI、Codex CLI、ChatGPT 桌面版、Cherry Studio 的写法，内容同时存到 PoB\\MCP配置.txt；
  其他支持本地（stdio）MCP 的客户端按“通用”一节填命令和参数。挪动文件夹后要重新运行它并更新配置。
- 之后可以用中文问：技能、天赋、装备词缀、章节与引路石；让它出一个 BD（带 PoB 导入码）；
  或问“我 PoB 里当前 BD 的 DPS 和抗性”。数字由包里的 PoB 引擎计算：PoB 开着时用当前打开的 BD
  （含未保存的修改），关着时用最近打开的 BD 文件。
- 资料来自 poe2db.tw（简体中文，CC BY-NC-SA）、Path of Building 与 poe.ninja，见 PoB\\pobg\\README.zh-CN.md。
- 更新 Python 或 POBG 依赖时，如果 AI 客户端正开着 POBG，要先关掉客户端再更新。

说明
- 包里自带 Python（官方嵌入版），不需要另装。
- 助手的设置和日志在 %APPDATA%\\exiled-exchange-2，与旧版助手共用。
- 不要把这个文件夹放在需要管理员权限才能写入的位置（如 C:\\Program Files），否则无法更新。
- 许可：本项目代码 MIT，编年史数据 CC BY-NC-SA（仅限非商业），第三方组件见 PoB\\licenses。
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


def install_pobg(pob, checkout, lib, commit):
    """POBG's tracked files at `commit` (from a clean checkout of it) in pob/pobg, its lib/ and the launcher."""
    head = run("git", "-C", str(checkout), "rev-parse", "HEAD")
    if head != commit or run("git", "-C", str(checkout), "status", "--porcelain"):
        raise ValueError(f"{checkout} 必须是 sources/pobg.json 固定提交 {commit} 的干净检出（现在是 {head}）")
    target = pob / "pobg"
    tar = subprocess.check_output(["git", "-C", str(checkout), "archive", "--format=tar", commit, *POBG_FILES])
    with tarfile.open(fileobj=io.BytesIO(tar)) as archive:
        archive.extractall(target, filter="data")
    shutil.copytree(lib, target / "lib", ignore=shutil.ignore_patterns("__pycache__", "*.chm"))
    (target / "run_pobg.py").write_text(POBG_LAUNCHER, encoding="utf-8")
    shutil.copy(ROOT / "ops/pobg_mcp_config.py", target / "mcp_config.py")


def release_version(changelog=CHANGELOG):
    """The version and date of the newest entry, `VERSION[x.y.z][yyyy/mm/dd]` (PoB's changelog format)."""
    for line in changelog.read_text(encoding="utf-8").splitlines():
        found = re.fullmatch(r"VERSION\[(\d+\.\d+\.\d+)\]\[(.+)\]", line.strip())
        if found:
            return found.group(1), found.group(2)
    raise ValueError(f"{changelog} 没有 VERSION[x.y.z][日期] 行")


def layout_pob(source, pob, commit):
    """The PoB export (repository layout) as an official release lays it out, in `pob`.
    Returns {relative name: manifest part} for every file that came from PoB."""
    parts = {}

    def copy(src, name, part):
        target = pob / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
        parts[name] = part

    def tree(directory, skip=()):
        for path in sorted(directory.rglob("*")):
            relative = path.relative_to(directory)
            if path.is_file() and not ({*relative.parts} & (POB_USER_STATE | set(skip))):
                yield path, relative.as_posix()

    for name in POB_ROOT_FILES:
        copy(source / name, name, "default")
    for path, name in tree(source / "src", POB_SRC_SKIP):
        copy(path, name, "tree" if name.startswith("TreeData/") else "program")
    for path, name in tree(source / "runtime"):
        copy(path, name.replace("{space}", " "), "runtime")
    for path, name in tree(source / "poe2-assistant"):
        copy(path, f"poe2-assistant/{name}", "program")
    # The pinned commit, or the poe2-assistant branch head (sources/pob-branch.md); the trial
    # engine accepts either.
    (pob / ".pob-commit").write_text(commit + "\n", encoding="utf-8")
    parts[".pob-commit"] = "program"
    install_hook(pob)
    return parts


def file_part(name, pob_parts):
    """Manifest part of a file under PoB/ (see the module docstring)."""
    if name in pob_parts:
        return pob_parts[name]
    if name == "assistant-app/assistant-backend.json":
        return "backend"
    if name.startswith("assistant-app/"):
        return "assistant"
    if name.startswith(("python/", "pobg/lib/")):
        return "python"
    return "backend"


def manifest_name(name):
    """Upstream writes spaces in file names as {space} (UpdateCheck.lua turns them back)."""
    return name.replace(" ", "{space}")


def file_sha1(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha1").hexdigest()


def manifest(pob, pob_parts, version, branch, raw_base, assistant_url):
    """manifest.xml for the package in `pob` (bytes); returns (xml, {name: (part, sha1)})."""
    files = {}
    for path in sorted(pob.rglob("*")):
        name = path.relative_to(pob).as_posix()
        if path.is_file() and name != "manifest.xml" and name not in POB_UNMANAGED:
            files[name] = (file_part(name, pob_parts), file_sha1(path))
    root = ET.Element("PoBVersion")
    ET.SubElement(root, "Version", number=version, platform="win32", branch=branch)
    for part in ("default", "program", "tree", "runtime", "backend", "python"):
        attributes = {"part": part, "url": raw_base}
        if part == "runtime":
            attributes["platform"] = "win32"
        ET.SubElement(root, "Source", attributes)
    ET.SubElement(root, "Source", part="assistant", url=assistant_url)
    for name, (part, sha1) in sorted(files.items(), key=lambda item: (item[1][0], item[0].lower())):
        ET.SubElement(root, "File", name=manifest_name(name), part=part, sha1=sha1)
    ET.indent(root, "\t")
    return ET.tostring(root, encoding="UTF-8", xml_declaration=True) + b"\n", files


def write_zip(path, entries):
    """ZIP of (archive name, source path) pairs, with fixed timestamps so equal input gives equal bytes."""
    path.unlink(missing_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for name, source in entries:
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            with source.open("rb") as stream, bundle.open(info, "w") as out:
                shutil.copyfileobj(stream, out, 1 << 20)


def assistant_zip_name(ee2_commit):
    return f"assistant-{ee2_commit[:12]}.zip"


def install_assistant(pob, assistant, assistant_zip):
    """EE2's files in pob/assistant-app: from its win-unpacked folder, or from an earlier release's assistant
    zip (entry names as in the manifest, so the files are byte for byte what the updater installs)."""
    target = pob / ASSISTANT_DIR
    if assistant:
        shutil.copytree(assistant, target)
        (target / "assistant-backend.json").unlink(missing_ok=True)
        return
    with zipfile.ZipFile(assistant_zip) as archive:
        for info in archive.infolist():
            name = info.filename.replace("{space}", " ")
            if info.is_dir():
                continue
            if not name.startswith("assistant-app/") or ".." in Path(name).parts:
                raise ValueError(f"{assistant_zip} 里有不属于助手的文件：{info.filename}")
            out = pob / name
            out.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as stream, out.open("wb") as copy:
                shutil.copyfileobj(stream, copy, 1 << 20)


def build(pob, assistant, ee2_commit, out, cache, pobg, pob_commit=None, make_zip=True, *, version=None,
          assistant_zip=None, assistant_url=None, branch=RELEASE_BRANCH, raw_base=RAW_BASE,
          release_base=RELEASE_BASE):
    if bool(assistant) == bool(assistant_zip):
        raise ValueError("--assistant 和 --assistant-zip 二选一")
    version, date = (version, None) if version else release_version()
    package = out / NAME
    for old in (package, out / "release-branch"):
        if old.exists():
            shutil.rmtree(old)
    package.mkdir(parents=True)
    root = package / "PoB"
    pin = json.loads((ROOT / "sources/pob.json").read_text(encoding="utf-8"))
    pob_commit = pob_commit or pin["commit"]

    pob_parts = layout_pob(pob, root, pob_commit)
    changelog = CHANGELOG.read_text(encoding="utf-8").rstrip("\n") + "\n\n" + (pob / "changelog.txt").read_text(encoding="utf-8")
    (root / "changelog.txt").write_text(changelog, encoding="utf-8", newline="\n")

    with zipfile.ZipFile(python_zip(cache)) as archive:
        archive.extractall(root / "python")
    # The ._pth file replaces sys.path and leaves out the script's directory.
    pth = root / f"python/python{PYTHON_VERSION.replace('.', '')[:3]}._pth"
    pth.write_text(pth.read_text(encoding="utf-8").replace(".\n", ".\n../backend/scripts\n", 1), encoding="utf-8")
    install_assistant(root, assistant, assistant_zip)
    (root / "assistant-app/assistant-backend.json").write_text(
        json.dumps(BACKEND_CONFIG, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    backend = root / "backend"
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
    install_pobg(root, pobg, pobg_lib(cache, pobg_pin["requirements"]), pobg_pin["commit"])
    licenses = root / "licenses"
    licenses.mkdir()
    shutil.copy2(ROOT / "LICENSE", licenses / "LICENSE-PoE2-Build-Assistant.txt")
    shutil.copy2(ROOT / "THIRD-PARTY-NOTICES.md", licenses / "THIRD-PARTY-NOTICES.md")
    shutil.copy2(ROOT / "data/DATA-LICENSE.md", licenses / "DATA-LICENSE.md")
    shutil.copy2(pob / "LICENSE.md", licenses / "LICENSE-PathOfBuilding.md")

    readme = README.format(version=version).replace("\n", "\r\n")
    (root / "使用说明.txt").write_text(readme, encoding="utf-8-sig")
    (package / "使用说明.txt").write_text(readme, encoding="utf-8-sig")
    (package / "启动中文PoB.cmd").write_bytes(LAUNCHER.encode("ascii"))
    (package / MCP_CONFIG_NAME).write_bytes(MCP_CONFIG.encode("ascii"))

    tag = f"v{version}"
    zip_name = assistant_zip_name(ee2_commit)
    assistant_url = assistant_url or f"{release_base}/{tag}/{zip_name}"
    if not assistant_url.endswith(".zip"):
        raise ValueError("助手 part 的地址必须以 .zip 结尾（UpdateCheck.lua 据此整包下载再解出）")
    versions = {
        "version": version,
        "date": date,
        "project_commit": run("git", "-C", str(ROOT), "rev-parse", "HEAD"),
        "project_dirty": bool(run("git", "-C", str(ROOT), "status", "--porcelain")),
        "pob_commit": pob_commit,
        "ee2_commit": ee2_commit,
        "pobg_commit": pobg_pin["commit"],
        "python": {"version": PYTHON_VERSION, "url": PYTHON_URL, "sha256": PYTHON_SHA256},
        "update": {"branch": branch, "files": raw_base, "assistant": assistant_url},
    }
    (root / "版本.json").write_text(json.dumps(versions, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    text, files = manifest(root, pob_parts, version, branch, raw_base, assistant_url)
    (root / "manifest.xml").write_bytes(text)

    # The release branch: every file the updater fetches one by one, under its manifest name.
    branch_dir = out / "release-branch"
    branch_dir.mkdir()
    for name, (part, _) in files.items():
        if part != "assistant":
            target = branch_dir / manifest_name(name)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / name, target)
    (branch_dir / "manifest.xml").write_bytes(text)
    (branch_dir / ".gitattributes").write_text("* -text\n", encoding="utf-8")  # serve the exact bytes

    outputs = []
    if assistant:
        new_zip = out / zip_name
        write_zip(new_zip, [(manifest_name(name), root / name) for name, (part, _) in sorted(files.items())
                            if part == "assistant"])
        outputs.append(new_zip)
    archive = out / f"{NAME}-{tag}.zip"
    archive.unlink(missing_ok=True)
    if make_zip:
        write_zip(archive, [(path.relative_to(out).as_posix(), path)
                            for path in sorted(package.rglob("*")) if path.is_file()])
        outputs.insert(0, archive)
    sums = out / "SHA256SUMS.txt"
    lines = []
    for path in outputs:
        with path.open("rb") as stream:
            lines.append(f"{hashlib.file_digest(stream, 'sha256').hexdigest()}  {path.name}\n")
    sums.write_text("".join(lines), encoding="utf-8")
    return package, (archive if make_zip else None)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pob", type=Path, required=True,
                        help="PoB 分支导出目录（仓库布局：src、runtime、poe2-assistant），见 sources/pob-branch.md")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--assistant", type=Path, help="EE2 win-unpacked 目录（新建助手 zip）")
    source.add_argument("--assistant-zip", type=Path, help="已发布的助手 zip（EE2 没变时复用，不重建）")
    parser.add_argument("--assistant-url", help="manifest 里助手 zip 的下载地址；默认本版本 Release 的资产地址")
    parser.add_argument("--ee2-commit", required=True, help="构建助手的 EE2 提交")
    parser.add_argument("--pobg", type=Path, required=True, help="POBG 的干净检出，HEAD 为 sources/pobg.json 的固定提交")
    parser.add_argument("--out", type=Path, required=True, help="输出目录")
    parser.add_argument("--cache", type=Path, help="Python 嵌入版与 POBG 依赖缓存，默认 <out>/cache")
    parser.add_argument("--pob-commit", help="--pob 的提交（通常是 sources/pob-branch.json 的 head）")
    parser.add_argument("--version", help="版本号 x.y.z；默认取 release/changelog.txt 最新一条")
    parser.add_argument("--branch", default=RELEASE_BRANCH, help=f"发布分支名（默认 {RELEASE_BRANCH}）")
    parser.add_argument("--raw-base", default=RAW_BASE, help="发布分支文件的下载地址，{branch} 由 PoB 替换")
    parser.add_argument("--release-base", default=RELEASE_BASE, help="Release 资产地址前缀（后接 /v<版本>/<文件>）")
    parser.add_argument("--no-zip", action="store_true", help="不打完整 ZIP")
    args = parser.parse_args()
    package, archive = build(args.pob.resolve(), args.assistant and args.assistant.resolve(), args.ee2_commit,
                             args.out.resolve(), (args.cache or args.out / "cache").resolve(),
                             args.pobg.resolve(), args.pob_commit, not args.no_zip, version=args.version,
                             assistant_zip=args.assistant_zip and args.assistant_zip.resolve(),
                             assistant_url=args.assistant_url, branch=args.branch, raw_base=args.raw_base,
                             release_base=args.release_base)
    size = sum(path.stat().st_size for path in package.rglob("*") if path.is_file())
    print(f"{package}  {size / 2**20:.0f} MiB")
    for path in sorted(args.out.resolve().glob("*.zip")):
        print(f"{path}  {path.stat().st_size / 2**20:.0f} MiB")


if __name__ == "__main__":
    main()
