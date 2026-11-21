"""Rebase our PoB and EE2 branches onto an upstream commit and run the regression checks (U04).

Works in a scratch directory on Linux; the home repositories and branches are
never changed. Conflicts are reported (the rebase is aborted), not resolved,
except that a conflict only in EE2's renderer/package-lock.json is resolved by
taking upstream's lock file and regenerating it.

  python3 -B ops/rebase_check.py --work /tmp/u04-check [--fetch]
      [--pob-onto upstream/dev] [--ee2-onto upstream/master] [--skip-pob] [--skip-ee2]
      [--pob-suite]   also run the full scripts/ suite against the rebased PoB
      [--pob-branch task/X]  check a task branch of the PoB home repo instead of the pinned one
      [--ee2-branch task/X]  same for the EE2 home repo
      [--sources DIR]  read pob-branch.json / ee2.json from DIR instead of sources/ (U05 watcher, drills)

Pins and repositories come from sources/pob-branch.json and sources/ee2.json; see
sources/pob-branch.md. Exit status 0 only when every rebase and check passes.
"""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ops"))
import pob_branch  # noqa: E402

STATE = Path.home() / ".local/state/poe2-assistant"
RUNTIME = STATE / "p02-runtime"
I18N = STATE / "i18n"
IDENTITY = {"GIT_AUTHOR_NAME": "Claude", "GIT_AUTHOR_EMAIL": "noreply@anthropic.com",
            "GIT_COMMITTER_NAME": "Claude", "GIT_COMMITTER_EMAIL": "noreply@anthropic.com"}
LOCKFILE = "renderer/package-lock.json"


def run(cmd, cwd=None, env=None, check=True):
    result = subprocess.run(cmd, cwd=cwd, env={**os.environ, **IDENTITY, **(env or {})},
                            text=True, capture_output=True)
    if check and result.returncode:
        raise RuntimeError(f"{' '.join(map(str, cmd))} failed:\n{result.stdout}{result.stderr}")
    return result


def git(repo, *args, check=True):
    return run(["git", "-C", str(repo), *args], check=check)


SOURCES = ROOT / "sources"


def load(name):
    return json.loads((SOURCES / name).read_text(encoding="utf-8"))


def clone(home, work, upstream_refs):
    if work.exists():
        shutil.rmtree(work)
    git(home.parent, "clone", "-q", "--no-checkout", str(home), str(work))
    git(work, "fetch", "-q", str(home), upstream_refs)


def rebase(repo, base, onto, branch, resolve_lockfile=False):
    """Rebase `branch` from `base` onto `onto`; return a report dict."""
    report = {"onto": git(repo, "rev-parse", onto).stdout.strip(), "base": base,
              "upstream_commits": int(git(repo, "rev-list", "--count", f"{base}..{onto}").stdout),
              "our_commits": int(git(repo, "rev-list", "--count", f"{base}..{branch}").stdout),
              "conflicts": [], "auto_resolved": []}
    git(repo, "checkout", "-q", "-B", "rebase-check", branch)
    result = git(repo, "rebase", "-q", "--onto", onto, base, check=False)
    while result.returncode:
        files = git(repo, "diff", "--name-only", "--diff-filter=U").stdout.split()
        subject = git(repo, "log", "-1", "--format=%h %s", "REBASE_HEAD", check=False).stdout.strip()
        if resolve_lockfile and files == [LOCKFILE]:
            git(repo, "checkout", "--ours", "--", LOCKFILE)  # upstream's lock file
            run(["npm", "install", "--package-lock-only", "--ignore-scripts", "--no-audit", "--no-fund"],
                cwd=repo / "renderer")
            git(repo, "add", LOCKFILE)
            report["auto_resolved"].append({"commit": subject, "files": files})
            result = git(repo, "-c", "core.editor=true", "rebase", "--continue", check=False)
            continue
        report["conflicts"].append({"commit": subject, "files": files})
        git(repo, "rebase", "--abort")
        break
    report["head"] = git(repo, "rev-parse", "HEAD").stdout.strip() if not report["conflicts"] else None
    return report


def check(name, func, results):
    try:
        detail = func()
        results.append({"check": name, "ok": True, "detail": detail})
    except Exception as error:  # report every failing check, keep going
        results.append({"check": name, "ok": False, "detail": str(error)[-3000:]})


def pob_checks(repo, work, suite):
    tree = work / "pob-tree"
    if tree.exists():
        shutil.rmtree(tree)
    tree.mkdir(parents=True)
    archive = subprocess.run(["git", "-C", str(repo), "archive", "HEAD"], check=True, capture_output=True)
    subprocess.run(["tar", "-x", "-C", str(tree)], input=archive.stdout, check=True)
    head = git(repo, "rev-parse", "HEAD").stdout.strip()
    (tree / ".pob-commit").write_text(head + "\n", encoding="utf-8")
    engine_env = {"POB_ENGINE": str(tree), "POE2_POB_CANDIDATE": head}
    release, source = I18N / "PathOfBuilding-PoE2-i18n-portable.zip", I18N / "source"
    results = []

    def replay():
        # The legacy scripts applied to the new upstream must still give exactly the
        # rebased commit that `migrate` made from them (the U01 commit).
        ours = git(repo, "rev-list", "--reverse", "upstream-onto..HEAD").stdout.split()
        migrated = ours[pob_branch.MIGRATED - 1]
        subject = git(repo, "log", "-1", "--format=%s", migrated).stdout.strip()
        if not subject.startswith("U01:"):
            raise AssertionError(f"commit {pob_branch.MIGRATED} is not the U01 hook: {subject}")
        trees = {}
        for name, ref in (("pob-onto", "upstream-onto"), ("pob-migrated", migrated)):
            trees[name] = work / name
            if trees[name].exists():
                shutil.rmtree(trees[name])
            trees[name].mkdir()
            data = subprocess.run(["git", "-C", str(repo), "archive", ref], check=True, capture_output=True)
            subprocess.run(["tar", "-x", "-C", str(trees[name])], input=data.stdout, check=True)
        scripted = pob_branch.scripted(trees["pob-onto"], work / "pob-scripted", release, source)
        report = pob_branch.compare(scripted, trees["pob-migrated"],
                                    pob_branch.SCRIPT_ONLY | {pob_branch.PROVENANCE})
        if report["only_left"] or report["only_right"] or report["different"]:
            raise AssertionError(f"scripts on upstream differ from the rebased commits: {report}")
        return f"scripts on upstream == rebased {subject[:4]} commit ({report['same']} files)"

    def runtime():
        problems = pob_branch.verify_runtime(tree, release)
        if problems:
            raise AssertionError("; ".join(problems))
        return "i18n runtime matches the pinned release"

    def paste():
        prelude = f'package.cpath="{RUNTIME}/?.so;"..package.cpath; utf8=require("lua-utf8")'
        return run([str(RUNTIME / "LuaJIT/src/luajit"), "-e", prelude,
                    str(ROOT / "ops/check_pob_unicode_paste.lua"),
                    str(tree / "src/Classes/EditControl.lua")]).stdout.strip()

    def lua_syntax():
        changed = git(repo, "diff", "--name-only", "--diff-filter=AM", "upstream-onto", "HEAD",
                      "--", "*.lua").stdout.split()
        for name in changed:
            run([str(RUNTIME / "LuaJIT/src/luajit"), "-e", f'assert(loadfile("{tree / name}"))'])
        return f"{len(changed)} changed Lua files compile"

    def hook():
        return run([sys.executable, "-B", "-m", "unittest", "-q", "test_hook_pob_assistant"],
                   cwd=ROOT / "ops").stderr.strip().splitlines()[-1]

    def engine():
        return run([sys.executable, "-B", "-m", "unittest", "-q", "test_pob_server"],
                   cwd=ROOT / "scripts", env=engine_env).stderr.strip().splitlines()[-1]

    def terms():
        # P03: Chinese display lines keep PoB's numbers (whole tree and unique database).
        if not (tree / "src/Modules/AssistantTerms.lua").exists():
            return "no AssistantTerms.lua (before P03)"
        out = run([sys.executable, "-B", str(ROOT / "ops/check_pob_terms.py"), "--pob", str(tree)])
        return " ".join(out.stdout.strip().splitlines()[-3:])

    def full_suite():
        result = run([sys.executable, "-B", "-m", "unittest", "discover", "-s", "scripts", "-p", "test_*.py"],
                     cwd=ROOT, env=engine_env, check=False)
        out = result.stderr.strip().splitlines()
        if result.returncode:  # name the failing tests (the report keeps the last 3000 characters)
            failing = [line for line in out if line.startswith(("ERROR: ", "FAIL: "))]
            raise AssertionError("\n".join(failing[:40] + out[-3:]))
        return " ".join(out[-3:])

    for name, func in [("replay install scripts", replay), ("i18n runtime", runtime),
                       ("Lua syntax", lua_syntax), ("P07 paste", paste), ("U01 hook", hook),
                       ("real engine (test_pob_server)", engine), ("P03 terms numbers", terms)]:
        check(name, func, results)
    if suite:
        check("full scripts suite", full_suite, results)
    return results


def ee2_checks(repo):
    results = []
    for package in ("main", "renderer"):
        check(f"{package}: npm ci", lambda p=package: run(
            ["npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund"], cwd=repo / p).stdout[-200:], results)
    commands = {
        "main": [["npx", "tsc", "--noEmit"], ["npx", "eslint", "src"], ["npx", "prettier", "--check", "src"]],
        "renderer": [["npx", "vue-tsc", "--noEmit"], ["npx", "eslint", "--ext", ".ts,.vue", "src"],
                     ["npx", "prettier", "--check", "src"]],
    }
    for package, cmds in commands.items():
        for cmd in cmds:
            check(f"{package}: {' '.join(cmd[1:])}", lambda c=cmd, p=package: (
                run(c, cwd=repo / p).stdout.strip().splitlines() or ["ok"])[-1], results)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--work", type=Path, required=True, help="scratch directory (replaced)")
    parser.add_argument("--fetch", action="store_true", help="fetch upstream into the home repos first")
    parser.add_argument("--pob-onto", default="upstream/dev")
    parser.add_argument("--ee2-onto", default="upstream/master")
    parser.add_argument("--skip-pob", action="store_true")
    parser.add_argument("--skip-ee2", action="store_true")
    parser.add_argument("--pob-suite", action="store_true", help="run the full scripts/ suite too")
    parser.add_argument("--pob-branch", help="PoB branch to check (default: pob-branch.json name)")
    parser.add_argument("--ee2-branch", help="EE2 branch to check (default: ee2.json branch)")
    parser.add_argument("--sources", type=Path, help="folder with the pins (default: sources/)")
    args = parser.parse_args()
    if args.sources:
        global SOURCES
        SOURCES = args.sources.resolve()
    args.work.mkdir(parents=True, exist_ok=True)
    report = {}

    if not args.skip_pob:
        pin = load("pob-branch.json")
        home = Path(os.path.expanduser(pin["home"]))
        if args.fetch:
            git(home, "fetch", "-q", "upstream")
        repo = args.work / "pob"
        clone(home, repo, "+refs/remotes/upstream/*:refs/remotes/upstream/*")
        result = rebase(repo, pin["base"], args.pob_onto.replace("upstream/", "refs/remotes/upstream/"),
                        f"origin/{args.pob_branch or pin['name']}")
        if not result["conflicts"]:
            git(repo, "update-ref", "refs/heads/upstream-onto", result["onto"])
            result["checks"] = pob_checks(repo, args.work, args.pob_suite)
        report["pob"] = result

    if not args.skip_ee2:
        pin = load("ee2.json")
        home = Path(os.path.expanduser(pin["home"]))
        repo = args.work / "ee2"
        clone(home, repo, "+refs/heads/*:refs/remotes/origin/*")
        git(repo, "remote", "add", "upstream", pin["upstream"])
        git(repo, "fetch", "-q", "--tags", "upstream")
        result = rebase(repo, pin["base"], args.ee2_onto, f"origin/{args.ee2_branch or pin['branch']}",
                        resolve_lockfile=True)
        if not result["conflicts"]:
            result["checks"] = ee2_checks(repo)
        report["ee2"] = result

    (args.work / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    ok = True
    for name, result in report.items():
        print(f"== {name}: onto {result['onto'][:10]} (+{result['upstream_commits']} upstream, "
              f"{result['our_commits']} ours)")
        for item in result["auto_resolved"]:
            print(f"   auto-resolved {item['files']} in {item['commit']}")
        for item in result["conflicts"]:
            ok = False
            print(f"   CONFLICT in {item['commit']}: {', '.join(item['files'])}")
        for item in result.get("checks", []):
            ok &= item["ok"]
            print(f"   {'ok  ' if item['ok'] else 'FAIL'} {item['check']}: {item['detail'].splitlines()[-1] if item['detail'] else ''}")
    print(f"report: {args.work / 'report.json'}")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
