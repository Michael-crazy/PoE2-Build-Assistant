#!/usr/bin/env python3
"""Check the PoB Chinese display layer (P03) headless: localized lines keep PoB's numbers.

  python3 -B ops/check_pob_terms.py --pob <PoB tree with src/Modules/AssistantTerms.lua>
      [--build some.xml ...] [--out report.json]

Loads each build in HeadlessWrapper with POE2_ASSISTANT_LOCALE=zh-CN and localizes every
allocated node (name, stat lines), item (name, mod lines) and gem as PoB would draw it; then
the whole passive tree and every unique in the item database (with ranges). A localized line
fails when its numbers differ from the English line (English number words such as "eight"
may appear as digits). Builds are read only. Exit status 0 when nothing fails.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "ops/check_pob_terms.lua"
RUNTIME = Path.home() / ".local/state/poe2-assistant/p02-runtime"


def lua_string(text):
    return json.dumps(str(text))  # a JSON string literal is a valid Lua string literal here


def run(pob, builds, out):
    pob = Path(pob).resolve()
    src = pob / "src"
    if not (src / "Modules/AssistantTerms.lua").exists():
        raise SystemExit(f"{pob} has no src/Modules/AssistantTerms.lua")
    env = dict(os.environ, POE2_ASSISTANT_LOCALE="zh-CN",
               POE2_ASSISTANT_TERMS_DIR=str(pob / "poe2-assistant/terms"))
    prelude = ("arg = {} "
               "package.path = '../runtime/lua/?.lua;../runtime/lua/?/init.lua;' .. package.path "
               f"package.cpath = {lua_string(RUNTIME / '?.so')} .. ';' .. package.cpath "
               f"CHECK_BUILDS = {{{', '.join(lua_string(Path(b).resolve()) for b in builds)}}} "
               f"CHECK_OUT = {lua_string(Path(out).resolve())}")
    result = subprocess.run([str(RUNTIME / "LuaJIT/src/luajit"), "-e", prelude, str(CHECKER)],
                            cwd=src, env=env, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr[-3000:])
    return json.loads(Path(out).read_text(encoding="utf-8"))


def summary(report):
    lines = []
    for entry in report["builds"]:
        parts = [f"{key} {entry[key]['localized']}/{entry[key]['lines']} lines, "
                 f"{entry[key]['names_localized']}/{entry[key]['names']} names" for key in ("tree", "items")]
        parts.append(f"gems {entry['gems']['names_localized']}/{entry['gems']['names']} names")
        lines.append(f"{Path(entry['build']).name}: {entry['allocated_nodes']} nodes; " + "; ".join(parts))
    for key in ("tree", "unique_db"):
        c = report[key]
        lines.append(f"{key}: {c['localized']}/{c['lines']} lines, {c['names_localized']}/{c['names']} names")
    lines.append(f"number words written as digits: {len(report['word_numbers'])}; failures: {report['failure_count']}")
    return lines


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pob", required=True, type=Path)
    parser.add_argument("--build", action="append", default=[], type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        out = args.out or Path(tmp) / "report.json"
        report = run(args.pob, args.build, out)
    for line in summary(report):
        print(line)
    for failure in report["failures"][:20]:
        print("FAIL", json.dumps(failure, ensure_ascii=False))
    sys.exit(1 if report["failure_count"] else 0)


if __name__ == "__main__":
    main()
