#!/usr/bin/env python3
"""P10b: count English left in PoB's interface areas, headless, for one or two PoB trees.

  python3 -B ops/check_pob_ui_text.py --pob <tree> [--before <tree>] --build a.xml [--build ...]
      [--out report.json]

Runs ops/check_pob_ui_text.lua (zh-CN) on each tree with the same builds and prints, per area
(warnings, breakdown lines/cells, item/flask tooltips, Config labels/tooltips, passive tooltips,
Items tab, Craft Item popup), the lines drawn, the lines with no Chinese and an English word, and
mixed lines. With --before the counts of both trees are shown side by side. Builds are read only.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "ops/check_pob_ui_text.lua"
RUNTIME = Path.home() / ".local/state/poe2-assistant/p02-runtime"


def lua_string(text):
    return json.dumps(str(text))


def run(pob, builds, out):
    pob = Path(pob).resolve()
    env = dict(os.environ, POE2_ASSISTANT_LOCALE="zh-CN",
               POE2_ASSISTANT_TERMS_DIR=str(pob / "poe2-assistant/terms"))
    prelude = ("arg = {} "
               "package.path = '../runtime/lua/?.lua;../runtime/lua/?/init.lua;' .. package.path "
               f"package.cpath = {lua_string(RUNTIME / '?.so')} .. ';' .. package.cpath "
               f"CHECK_BUILDS = {{{', '.join(lua_string(Path(b).resolve()) for b in builds)}}} "
               f"CHECK_OUT = {lua_string(Path(out).resolve())}")
    result = subprocess.run([str(RUNTIME / "LuaJIT/src/luajit"), "-e", prelude, str(CHECKER)],
                            cwd=pob / "src", env=env, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr[-3000:])
    return json.loads(Path(out).read_text(encoding="utf-8"))


def table(after, before=None):
    rows = [f"{'area':24} {'lines':>6} {'English':>8} {'mixed':>6}" + ("   (before: English / mixed)" if before else "")]
    for name in sorted(after["areas"]):
        a = after["areas"][name]
        row = f"{name:24} {a['lines']:6} {a['english']:8} {a['mixed']:6}"
        if before:
            b = before["areas"].get(name, {"english": 0, "mixed": 0})
            row += f"   {b['english']} / {b['mixed']}"
        rows.append(row)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pob", type=Path, required=True)
    parser.add_argument("--before", type=Path, help="tree without the change, for before/after counts")
    parser.add_argument("--build", action="append", default=[], type=Path, required=True)
    parser.add_argument("--out", type=Path, help="write the after report (JSON) here")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        after = run(args.pob, args.build, Path(tmp) / "after.json")
        before = run(args.before, args.build, Path(tmp) / "before.json") if args.before else None
    if args.out:
        args.out.write_text(json.dumps({"after": after, "before": before}, ensure_ascii=False, indent=1) + "\n",
                            encoding="utf-8")
    print("\n".join(table(after, before)))


if __name__ == "__main__":
    main()
