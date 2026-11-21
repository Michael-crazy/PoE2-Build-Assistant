"""Maintain the `poe2-assistant` PoB branch (U04).

Our PoB changes live as commits on `poe2-assistant` on top of the pinned fork
commit (sources/pob.json, sources/pob-branch.json). See sources/pob-branch.md for the patch format.

  migrate   one-shot: replay the legacy install scripts on a clean checkout of
            the base and commit each customisation separately
  scripted  apply the legacy install scripts to a copy of a tree (reference
            output for the equivalence check)
  compare   hash every file of two trees and list the differences
  verify-runtime
            check the committed i18n runtime files against the pinned ZIP
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from zipfile import ZipFile

OPS = Path(__file__).resolve().parent
sys.path.insert(0, str(OPS))
import enable_pob_unicode_paste  # noqa: E402
import hook_pob_assistant  # noqa: E402
import localize_pob  # noqa: E402
import localize_pob_calcs  # noqa: E402

BRANCH = "poe2-assistant"
AUTHOR = ("Claude", "noreply@anthropic.com")
TRAILER = "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
# Fixed dates make `migrate` reproducible: same base + same scripts = same ids.
DATE = "2026-11-20T00:00:00+00:00"
RELEASE_URL = ("https://github.com/woolkingx/PathOfBuilding-PoE2-i18n/releases/download/"
               "v0.1.0/PathOfBuilding-PoE2-i18n-portable.zip")
PROVENANCE = "poe2-assistant/i18n-runtime.json"
# Files the scripts leave behind that the branch deliberately does not keep.
SCRIPT_ONLY = {"runtime/z.dll.original"}
# Commits `migrate` creates; the last one is the scripts' full output.
MIGRATED = 5


def git(repo, *args, env=None, capture=True):
    result = subprocess.run(["git", "-C", str(repo), *args], check=True, text=True,
                            capture_output=capture, env=env)
    return result.stdout.strip() if capture else None


def sha256(path):
    with open(path, "rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def apply_localize(tree, release, source):
    argv = sys.argv
    sys.argv = ["localize_pob.py", str(tree), "--cjk-release", str(release),
                "--cjk-source", str(source)]
    try:
        localize_pob.main()
    finally:
        sys.argv = argv


def apply_scripts(tree, release, source):
    """The legacy install order used for the P04 Windows replay tree and U01."""
    apply_localize(tree, release, source)
    enable_pob_unicode_paste.patch_edit_control(tree / "src/Classes/EditControl.lua")
    localize_pob_calcs.install(tree)
    hook_pob_assistant.install(tree, hook_pob_assistant.U01_HOOK)


def runtime_provenance(release):
    with ZipFile(release) as archive:
        names = sorted(name for name in archive.namelist()
                       if "/" not in name and name.endswith(".dll") and name != "lua51.dll")
        files = {f"runtime/{name}": hashlib.sha256(archive.read(name)).hexdigest()
                 for name in (*names, *localize_pob.CJK_FONT_FILES)}
    return {
        "release": RELEASE_URL,
        "release_sha256": localize_pob.CJK_RELEASE_SHA,
        "source_repository": "https://github.com/woolkingx/PathOfBuilding-PoE2-i18n",
        "source_commit": localize_pob.CJK_SOURCE_PIN,
        "licence": "MIT (PathOfBuilding-PoE2-i18n LICENSE.md, same terms as PoB); "
                   "Noto Sans CJK under SIL OFL 1.1, see runtime/SimpleGraphic/Fonts/NotoSansCJK-LICENSE.txt",
        "notes": "All top-level DLLs of the release except lua51.dll (PoB keeps its own "
                 "LuaJIT and EXE), the CJK fallback font, and runtime/lua/xml.lua from "
                 "source_commit. runtime/z.dll is removed (the release ships zlib1.dll only).",
        "files": {**files, "runtime/lua/xml.lua": None},
    }


def commit(repo, message, paths):
    env = dict(os.environ, GIT_AUTHOR_NAME=AUTHOR[0], GIT_AUTHOR_EMAIL=AUTHOR[1],
               GIT_COMMITTER_NAME=AUTHOR[0], GIT_COMMITTER_EMAIL=AUTHOR[1],
               GIT_AUTHOR_DATE=DATE, GIT_COMMITTER_DATE=DATE)
    git(repo, "add", "-A", "--", *paths)
    git(repo, "commit", "-q", "-m", f"{message}\n\n{TRAILER}", env=env)
    return git(repo, "rev-parse", "--short", "HEAD")


def migrate(repo, base, release, source):
    repo = Path(repo)
    if git(repo, "status", "--porcelain"):
        raise SystemExit(f"{repo} has uncommitted changes")
    git(repo, "checkout", "-q", "-B", BRANCH, base)
    commits = []

    apply_localize(repo, release, source)
    (repo / "runtime/z.dll.original").unlink()
    provenance = runtime_provenance(release)
    provenance["files"]["runtime/lua/xml.lua"] = sha256(repo / "runtime/lua/xml.lua")
    (repo / PROVENANCE).parent.mkdir(exist_ok=True)
    (repo / PROVENANCE).write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    commits.append(commit(repo, "P04: ship the Chinese i18n runtime (DLLs, CJK font, xml.lua)",
                          ["runtime", PROVENANCE]))
    commits.append(commit(repo, "P04: Simplified Chinese menu labels and locale launchers", ["."]))

    enable_pob_unicode_paste.patch_edit_control(repo / "src/Classes/EditControl.lua")
    commits.append(commit(repo, "P07: keep valid UTF-8 when pasting into edit controls", ["."]))
    localize_pob_calcs.install(repo)
    commits.append(commit(repo, "P08: Simplified Chinese calculation labels", ["."]))
    hook_pob_assistant.install(repo, hook_pob_assistant.U01_HOOK)
    commits.append(commit(repo, "U01: start the in-game assistant shipped next to PoB", ["."]))
    return commits


def scripted(base_tree, out, release, source):
    out = Path(out)
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(base_tree, out, symlinks=True, ignore=shutil.ignore_patterns(".git"))
    apply_scripts(out, release, source)
    return out


def hashes(tree):
    tree = Path(tree)
    result = {}
    for path in tree.rglob("*"):
        rel = path.relative_to(tree).as_posix()
        if rel == ".git" or rel.startswith(".git/") or not path.is_file():
            continue
        result[rel] = sha256(path)
    return result


def compare(left, right, ignore=()):
    a, b = hashes(left), hashes(right)
    report = {
        "only_left": sorted(set(a) - set(b) - set(ignore)),
        "only_right": sorted(set(b) - set(a) - set(ignore)),
        "different": sorted(name for name in set(a) & set(b)
                            if a[name] != b[name] and name not in ignore),
        "same": sum(1 for name in set(a) & set(b) if a[name] == b[name]),
    }
    return report


def verify_runtime(tree, release):
    tree = Path(tree)
    recorded = json.loads((tree / PROVENANCE).read_text(encoding="utf-8"))
    expected = runtime_provenance(release)["files"]
    problems = []
    for name, digest in recorded["files"].items():
        want = expected.get(name) or digest  # xml.lua comes from the source commit, not the ZIP
        if digest != want:
            problems.append(f"{name}: provenance does not match the release")
        if not (tree / name).is_file() or sha256(tree / name) != digest:
            problems.append(f"{name}: committed file does not match provenance")
    if (tree / "runtime/z.dll").exists():
        problems.append("runtime/z.dll should be removed")
    return problems


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("migrate", "scripted", "verify-runtime"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--cjk-release", type=Path, required=True)
        if name != "verify-runtime":
            cmd.add_argument("--cjk-source", type=Path, required=True)
    sub.choices["migrate"].add_argument("repo", type=Path)
    sub.choices["migrate"].add_argument("--base", required=True)
    sub.choices["scripted"].add_argument("base_tree", type=Path)
    sub.choices["scripted"].add_argument("out", type=Path)
    sub.choices["verify-runtime"].add_argument("tree", type=Path)
    cmp = sub.add_parser("compare")
    cmp.add_argument("left", type=Path)
    cmp.add_argument("right", type=Path)
    cmp.add_argument("--ignore", action="append", default=[])
    args = parser.parse_args()

    if args.cmd == "migrate":
        print("\n".join(migrate(args.repo, args.base, args.cjk_release, args.cjk_source)))
    elif args.cmd == "scripted":
        print(scripted(args.base_tree, args.out, args.cjk_release, args.cjk_source))
    elif args.cmd == "compare":
        report = compare(args.left, args.right, args.ignore)
        print(json.dumps(report, indent=2, ensure_ascii=False))
        raise SystemExit(1 if report["only_left"] or report["only_right"] or report["different"] else 0)
    else:
        problems = verify_runtime(args.tree, args.cjk_release)
        print("\n".join(problems) or "i18n runtime matches the pinned release")
        raise SystemExit(1 if problems else 0)


if __name__ == "__main__":
    main()
