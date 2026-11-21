"""Build (and optionally publish) a release: the steps .github/workflows/release.yml runs (R04).

    python -B ops/release_build.py --work <dir> [--tag v0.1.0] [--publish]

1. Version: `--tag` must be `v` + the newest entry of release/changelog.txt.
2. Sources: PoB, EE2 and POBG at the commits pinned in sources/pob-branch.json (head), ee2.json
   (head) and pobg.json (commit), fetched from each pin's `repository` (override with --pob-repo,
   --ee2-repo, --pobg-repo, e.g. a local mirror).
3. Assistant: the asset `assistant-<EE2 commit>.zip` of an earlier release is reused when one exists
   (players then download nothing for the assistant); otherwise EE2 is built (Node 24 on PATH).
4. Package: ops/build_u01_package.py -> <work>/out (ZIP, assistant zip, release-branch/, SHA256SUMS).
5. Release branch: <work>/release-branch-git holds the new commit for the PoB fork's branch
   `assistant-release` (the files PoB's updater fetches one by one).
6. Notes: <work>/out/notes.md from release/notes.md.
7. With --publish: create the GitHub release with the assets, then push the release branch. The
   release goes first so the branch's manifest never points at a missing assistant zip.
"""

import argparse
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_u01_package as package  # noqa: E402

RELEASE_REPO = "Michael-crazy/PoE2-Build-Assistant"
BRANCH_REMOTE = "git@github.com:Michael-crazy/PathOfBuilding-PoE2.git"
AUTHOR = ("Claude", "noreply@anthropic.com")


def log(message):
    print(f"[release] {message}", flush=True)


def run(*args, cwd=None, capture=False, env=None):
    log(" ".join(str(a) for a in args) + (f"  (in {cwd})" if cwd else ""))
    shell = sys.platform == "win32" and Path(str(args[0])).suffix == "" and args[0] in ("npm", "npx")
    result = subprocess.run([str(a) for a in args], cwd=cwd, check=True, text=True, env=env, shell=shell,
                            stdout=subprocess.PIPE if capture else None)
    return result.stdout.strip() if capture else None


def pins():
    load = lambda name: json.loads((ROOT / "sources" / name).read_text(encoding="utf-8"))  # noqa: E731
    pob, ee2, pobg = load("pob-branch.json"), load("ee2.json"), load("pobg.json")
    return {"pob": (pob["repository"], pob["head"]), "ee2": (ee2["repository"], ee2["head"]),
            "pobg": (pobg["repository"], pobg["commit"])}


def fetch(repository, commit, target):
    """A checkout of `commit` (only that commit when the server allows, as GitHub does)."""
    if (target / ".git").is_dir() and run("git", "-C", target, "rev-parse", "HEAD", capture=True) == commit:
        return target
    shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True)
    run("git", "init", "-q", cwd=target)
    run("git", "config", "core.autocrlf", "false", cwd=target)
    run("git", "config", "core.longpaths", "true", cwd=target)
    run("git", "remote", "add", "origin", repository, cwd=target)
    try:
        run("git", "fetch", "-q", "--depth", "1", "origin", commit, cwd=target)
    except subprocess.CalledProcessError:
        run("git", "fetch", "-q", "origin", "+refs/heads/*:refs/remotes/origin/*", cwd=target)
    run("git", "-c", "advice.detachedHead=false", "checkout", "-q", commit, cwd=target)
    if run("git", "rev-parse", "HEAD", cwd=target, capture=True) != commit:
        raise ValueError(f"{repository} 检出的不是 {commit}")
    return target


def export(checkout, commit, target):
    """`git archive` of the commit (no .git, no ignored files), as the PoB input of the package."""
    shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True)
    data = subprocess.run(["git", "-C", str(checkout), "archive", "--format=tar", commit],
                          check=True, stdout=subprocess.PIPE).stdout
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        archive.extractall(target, filter="data")
    return target


def published_assistant(repo, name):
    """(tag, download URL) of the newest release that has the asset `name`, or None."""
    try:
        listing = run("gh", "api", f"repos/{repo}/releases", "--paginate", "--jq",
                      f'.[] | select(.draft | not) | .tag_name as $t | .assets[] | select(.name == "{name}") '
                      '| [$t, .browser_download_url] | @tsv', capture=True)
    except (subprocess.CalledProcessError, FileNotFoundError) as error:
        log(f"查不到已发布的助手 zip（{error}），将构建 EE2")
        return None
    rows = [line.split("\t") for line in listing.splitlines() if line.strip()]
    return tuple(rows[0]) if rows else None


def build_ee2(checkout):
    """EE2's win-unpacked folder, built as for U01 (Node 24; unsigned, no resource editing)."""
    for part in ("renderer", "main"):
        run("npm", "ci", "--no-audit", "--no-fund", cwd=checkout / part)
    run("npm", "run", "make-index-files", cwd=checkout / "renderer")
    run("npm", "run", "build", cwd=checkout / "renderer")
    run("npm", "run", "build", cwd=checkout / "main")
    run("npx", "electron-builder", "build", "--win", "dir", "--x64", "-c.win.signAndEditExecutable=false",
        "--publish", "never", cwd=checkout / "main")
    unpacked = checkout / "main/dist/win-unpacked"
    if not (unpacked / "Exiled Exchange 2.exe").is_file():
        raise FileNotFoundError(f"{unpacked} 里没有 Exiled Exchange 2.exe")
    return unpacked


def release_branch(out, work, remote, branch, tag):
    """Commit out/release-branch as the next state of `branch` (fetched from `remote` if it exists)."""
    repo = work / "release-branch-git"
    shutil.rmtree(repo, ignore_errors=True)
    repo.mkdir(parents=True)
    run("git", "init", "-q", cwd=repo)
    for key, value in (("core.autocrlf", "false"), ("core.longpaths", "true"), ("core.quotepath", "false"),
                       ("user.name", AUTHOR[0]), ("user.email", AUTHOR[1])):
        run("git", "config", key, value, cwd=repo)
    run("git", "remote", "add", "origin", remote, cwd=repo)
    try:
        run("git", "fetch", "-q", "--depth", "1", "origin", f"refs/heads/{branch}", cwd=repo)
        run("git", "checkout", "-q", "-B", branch, "FETCH_HEAD", cwd=repo)
    except subprocess.CalledProcessError:
        log(f"{remote} 还没有 {branch} 分支，新建")
        run("git", "checkout", "-q", "--orphan", branch, cwd=repo)
    for child in repo.iterdir():
        if child.name != ".git":
            shutil.rmtree(child) if child.is_dir() else child.unlink()
    shutil.copytree(out / "release-branch", repo, dirs_exist_ok=True)
    run("git", "add", "-A", cwd=repo)
    message = f"Release {tag}\n\nPoB's update files for {tag} (ops/release_build.py).\n"
    run("git", "commit", "-q", "--allow-empty", "-m", message, cwd=repo)
    return repo


def notes(out, version, date, reused):
    """Release notes from release/notes.md: {version}, {date}, {changes}, {checksums}, {assistant}."""
    changelog = (ROOT / "release/changelog.txt").read_text(encoding="utf-8").splitlines()
    changes, started = [], False
    for line in changelog:
        if line.startswith("VERSION["):
            if started:
                break
            started = True
            continue
        changes.append(line)
    template = (ROOT / "release/notes.md").read_text(encoding="utf-8")
    assistant = ("本版本助手（游戏内浮层）没有变化，从旧版本更新时不需要重新下载助手。" if reused else
                 "本版本助手（游戏内浮层）有更新，从旧版本更新时会下载约 150 MB。")
    text = (template.replace("{version}", version).replace("{date}", date or "")
            .replace("{changes}", "\n".join(changes).strip())
            .replace("{checksums}", (out / "SHA256SUMS.txt").read_text(encoding="utf-8").strip())
            .replace("{assistant}", assistant))
    (out / "notes.md").write_text(text, encoding="utf-8")
    return out / "notes.md"


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--work", type=Path, required=True, help="工作目录（源码、缓存、输出）")
    parser.add_argument("--tag", help="版本 tag（v<版本>）；省略时只按 changelog 的版本构建")
    parser.add_argument("--pob-repo", help="PoB 仓库地址（默认 pob-branch.json 的 repository）")
    parser.add_argument("--ee2-repo", help="EE2 仓库地址（默认 ee2.json 的 repository）")
    parser.add_argument("--pobg-repo", help="POBG 仓库地址（默认 pobg.json 的 repository）")
    parser.add_argument("--pob-commit", help="本机演练用：PoB 提交（默认 pob-branch.json 的 head）；发布时不要用")
    parser.add_argument("--release-repo", default=RELEASE_REPO, help="发布 Release 的仓库")
    parser.add_argument("--branch-remote", default=BRANCH_REMOTE, help="发布分支所在仓库（PoB fork）")
    parser.add_argument("--branch", default=package.RELEASE_BRANCH)
    parser.add_argument("--raw-base", default=package.RAW_BASE)
    parser.add_argument("--release-base", help="Release 资产地址前缀（默认 https://github.com/<release-repo>/releases/download）")
    parser.add_argument("--no-reuse", action="store_true", help="不复用已发布的助手 zip，总是构建 EE2")
    parser.add_argument("--assistant", type=Path, help="直接用这个 EE2 win-unpacked 目录（本机演练），不构建也不复用")
    parser.add_argument("--publish", action="store_true", help="建 Release、上传、推发布分支")
    args = parser.parse_args()

    work = args.work.resolve()
    version, date = package.release_version()
    tag = f"v{version}"
    if args.tag and args.tag != tag:
        raise SystemExit(f"tag {args.tag} 与 release/changelog.txt 最新版本 {tag} 不一致")
    release_base = args.release_base or f"https://github.com/{args.release_repo}/releases/download"
    log(f"版本 {tag}（{date}）")

    sources = pins()
    if args.pob_commit:
        if args.publish:
            raise SystemExit("--pob-commit 只用于本机演练，不能和 --publish 一起用")
        sources["pob"] = (sources["pob"][0], args.pob_commit)
    overrides = {"pob": args.pob_repo, "ee2": args.ee2_repo, "pobg": args.pobg_repo}
    checkouts = {}
    for key in ("pob", "pobg"):
        repository, commit = sources[key]
        checkouts[key] = fetch(overrides[key] or repository, commit, work / "src" / key)
    pob_export = export(checkouts["pob"], sources["pob"][1], work / "pob-export")

    ee2_commit = sources["ee2"][1]
    zip_name = package.assistant_zip_name(ee2_commit)
    assistant = assistant_zip = assistant_url = None
    found = None if (args.no_reuse or args.assistant) else published_assistant(args.release_repo, zip_name)
    if args.assistant:
        assistant = args.assistant.resolve()
    elif found:
        old_tag, assistant_url = found
        log(f"复用 {old_tag} 的 {zip_name}")
        downloads = work / "downloads"
        downloads.mkdir(parents=True, exist_ok=True)
        run("gh", "release", "download", old_tag, "-p", zip_name, "-D", downloads, "--clobber", "-R", args.release_repo)
        assistant_zip = downloads / zip_name
    else:
        checkout = fetch(overrides["ee2"] or sources["ee2"][0], ee2_commit, work / "src" / "ee2")
        assistant = build_ee2(checkout)

    out = work / "out"
    package.build(pob_export, assistant, ee2_commit, out, work / "cache", checkouts["pobg"],
                  pob_commit=sources["pob"][1], assistant_zip=assistant_zip,
                  assistant_url=assistant_url, branch=args.branch, raw_base=args.raw_base,
                  release_base=release_base)
    repo = release_branch(out, work, args.branch_remote, args.branch, tag)
    notes_file = notes(out, version, date, reused=bool(found))
    assets = [out / f"{package.ZIP_NAME}-{tag}.zip", out / "SHA256SUMS.txt"]
    if not found:
        assets.append(out / zip_name)
    log("产物：" + ", ".join(str(a) for a in assets))
    if not args.publish:
        log("未加 --publish：不建 Release、不推发布分支")
        return
    run("gh", "release", "create", tag, *assets, "--title", f"{package.NAME} {tag}", "--notes-file", notes_file,
        "--verify-tag", "-R", args.release_repo)
    run("git", "push", "origin", f"HEAD:refs/heads/{args.branch}", cwd=repo)
    log("已发布")


if __name__ == "__main__":
    main()
