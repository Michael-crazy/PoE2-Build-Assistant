#!/usr/bin/env python3
"""Update every PoE2DB (编年史) derived table in order, through the shared fetcher (R03 / U05 entry point).

  python3 -B ops/poe2db_update.py --engine /tmp/poe2-pob-source [--offline] [--pob-tree <PoB checkout>]
      [--pobg <POBG checkout with data/zh_cn>] [--out-root <dir>] [--only terms,names,...]

Steps (each one a script that can also be run alone):
  fetch        scripts/poe2db_fetch.py: class pages + sub pages + Keywords (us/cn/tw), gem pages (us/cn);
               cached pages and recorded 404s are not fetched again; 4 s between requests. --offline skips it.
               R03: --refresh-index DAYS refetches the index pages older than DAYS (new gems/items);
               --refresh-before ISO refetches the whole cache first (new season, resumable).
  terms        scripts/poe2db_terms.py -> data/terms/poe2db-1.0/<class>.json + mods.json
  names        ops/poe2db_item_classes.py, ops/poe2db_keywords.py -> data/terms/poe2db-1.0/names/
  localization scripts/pob_localization.py -> data/terms/pob-localization/ (PoB's display tables)
  gem_tooltips scripts/pob_gem_tooltips.py -> data/terms/pob-localization/gem_tooltips.json (needs --luajit)
  pob          with --pob-tree: copy the PoB display tables to <tree>/poe2-assistant/terms (source.json
               hashes rewritten) and regenerate src/Modules/AssistantUiFallback.lua (ops/pob_ui_fallback.py)
  consistency  with --pobg: ops/poe2db_consistency.py, our tables against POBG's by English name (report only)

--out-root writes the data/ tree and the evidence somewhere else (to compare with the committed tables);
by default it is this repository. Evidence (summaries, mismatches, reports) goes to
<out-root>/reports/poe2db-update/ (git-ignored). Nothing is pushed or committed.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import poe2db_fetch  # noqa: E402

STATE = Path.home() / ".local/state/poe2-assistant"
# Page names for scripts/poe2db_terms.py: D01's 39 classes plus M08a's currency page. Sub pages come
# from poe2db_terms.SUBPAGES.
CLASSES = [
    "Amulets", "Augment", "Belts", "Body_Armours", "Boots", "Bows", "Bucklers", "Charms", "Claws", "Crossbows",
    "Daggers", "Flails", "Foci", "Gloves", "Helmets", "Jewels", "Life_Flasks", "Lineage_Supports", "Mana_Flasks",
    "Meta_Skill_Gem", "One_Hand_Axes", "One_Hand_Maces", "One_Hand_Swords", "Quarterstaves", "Quivers", "Rings",
    "Sceptres", "Shields", "Skill_Gems", "Spears", "Spirit_Gems", "Stackable_Currency", "Staves", "Support_Gems",
    "Talismans", "Traps", "Two_Hand_Axes", "Two_Hand_Maces", "Two_Hand_Swords", "Wands",
]
EXTRA_PAGES = ["Keywords"]
STEPS = ["fetch", "terms", "names", "localization", "gem_tooltips", "pob", "consistency"]
POB_TERMS = ("bases.json", "gems.json", "gem_tooltips.json", "mods.json", "passives.json", "uniques.json")


def run(*args, env=None):
    command = [sys.executable, "-B", *map(str, args)]
    print("$", " ".join(command[2:]), flush=True)
    subprocess.run(command, check=True, cwd=ROOT, env=env)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def export_pob_terms(localization, pob_tree, project_commit):
    """Copy the display tables into <pob_tree>/poe2-assistant/terms and refresh source.json."""
    dest = Path(pob_tree) / "poe2-assistant/terms"
    dest.mkdir(parents=True, exist_ok=True)
    source_path = dest / "source.json"
    source = json.loads(source_path.read_text(encoding="utf-8")) if source_path.exists() else {"files": {}}
    for name in POB_TERMS:
        shutil.copyfile(localization / name, dest / name)
        table = json.loads((localization / name).read_text(encoding="utf-8"))
        meta = table.get("metadata") or table  # gem_tooltips.json keeps format/pob_commit at the top
        entry = source.setdefault("files", {}).setdefault(name, {})
        entry["sha256"] = sha256(dest / name)
        for key in ("format", "terms_version", "pob_commit"):
            if key in meta:
                entry[key] = meta[key]
    if project_commit:
        source["project_commit"] = project_commit
    source_path.write_text(json.dumps(source, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return dest


def project_commit():
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True,
                              check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cache", type=Path, default=poe2db_fetch.DEFAULT_CACHE)
    parser.add_argument("--engine", type=Path, required=True, help="pinned PoB engine (sources/pob.json commit)")
    parser.add_argument("--luajit", type=Path, help="LuaJIT for the gem tooltip step (skipped without it)")
    parser.add_argument("--lua-cpath", default="")
    parser.add_argument("--pob-tree", type=Path, help="PoB checkout to write the generated PoB files into")
    parser.add_argument("--pobg", type=Path, help="POBG checkout (data/zh_cn) for the consistency check")
    parser.add_argument("--out-root", type=Path, default=ROOT)
    parser.add_argument("--offline", action="store_true", help="never use the network")
    parser.add_argument("--only", help="comma-separated steps: " + ",".join(STEPS))
    parser.add_argument("--refresh-index", type=float, metavar="DAYS",
                        help="R03: refetch the class/sub/Keywords pages and gem indexes older than DAYS "
                             "(finds new gems and items; other cached pages are kept)")
    parser.add_argument("--refresh-before", metavar="ISO",
                        help="R03 new season: refetch every cached page fetched before this time first "
                             "(resumable with the same value)")
    args = parser.parse_args(argv)
    steps = args.only.split(",") if args.only else STEPS
    unknown = set(steps) - set(STEPS)
    if unknown:
        parser.error(f"unknown steps: {sorted(unknown)}")
    env = dict(os.environ, POE2DB_OFFLINE="1") if args.offline else dict(os.environ)
    out = args.out_root.resolve()
    terms = out / "data/terms/poe2db-1.0"
    names = terms / "names"
    localization = out / "data/terms/pob-localization"
    evidence = out / "reports/poe2db-update"
    for folder in (names, localization, evidence):
        folder.mkdir(parents=True, exist_ok=True)
    cache = str(args.cache)
    done = []

    if "fetch" in steps and not args.offline:
        import poe2db_terms
        pages = list(CLASSES) + [p for c in CLASSES for p in poe2db_terms.SUBPAGES.get(c, [])] + EXTRA_PAGES
        fetch = [ROOT / "scripts/poe2db_fetch.py", "--cache", cache]
        if args.refresh_before:  # R03 new season: every cached page again, then the lists below
            run(*fetch, "--refresh-before", args.refresh_before, "refresh", env=env)
            fetch += ["--refresh-before", args.refresh_before]
        index = ["--max-age", str(args.refresh_index)] if args.refresh_index is not None else []
        gem_index = ["--index-max-age", str(args.refresh_index)] if args.refresh_index is not None else []
        run(*fetch, *index, "pages", *pages, env=env)
        run(*fetch, "gems", *gem_index, env=env)
        done.append("fetch")
    if "terms" in steps:
        run(ROOT / "scripts/poe2db_terms.py", "--cache", cache, "--pob", args.engine, "--out", terms,
            "--evidence", evidence / "terms", *CLASSES, env=env)
        done.append("terms")
    if "names" in steps:
        run(ROOT / "ops/poe2db_item_classes.py", "--cache", cache, "--out", names / "item_classes.json", env=env)
        keywords = ["--pob-terms", args.pob_tree / "poe2-assistant/terms"] if args.pob_tree else []
        run(ROOT / "ops/poe2db_keywords.py", "--cache", cache, "--terms", terms, "--out", names / "keywords.json",
            *keywords, env=env)
        done.append("names")
    if "localization" in steps:
        run(ROOT / "scripts/pob_localization.py", "--terms", terms, "--pob", args.engine, "--out", localization,
            "--tree", args.cache / "tree", env=env)
        done.append("localization")
    if "gem_tooltips" in steps and args.luajit:
        run(ROOT / "scripts/pob_gem_tooltips.py", "--cache", cache, "--engine", args.engine, "--luajit", args.luajit,
            "--lua-cpath", args.lua_cpath, "--terms", terms, "--localization", localization,
            "--out", localization / "gem_tooltips.json", "--report", evidence / "gem_tooltips", env=env)
        done.append("gem_tooltips")
    if "pob" in steps and args.pob_tree:
        export_pob_terms(localization, args.pob_tree, project_commit())
        run(ROOT / "ops/pob_ui_fallback.py", "--pob", args.pob_tree, "--classes", names / "item_classes.json",
            "--keywords", names / "keywords.json", "--stats", evidence / "pob-ui-fallback-stats.json", env=env)
        done.append("pob")
    if "consistency" in steps and args.pobg:
        run(ROOT / "ops/poe2db_consistency.py", "--terms", terms, "--pobg", args.pobg,
            "--out", evidence / "consistency", env=env)
        done.append("consistency")
    skipped = [s for s in steps if s not in done]
    print(json.dumps({"done": done, "skipped": skipped}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
