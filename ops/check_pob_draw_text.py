#!/usr/bin/env python3
"""V10: count English PoB actually draws (DrawString) per view, headless, sorted by cause.

  python3 -B ops/check_pob_draw_text.py --pob <tree> [--before <tree>] --build main.xml
      [--build compare.xml] [--out report.json] [--lines]

Runs ops/check_pob_draw_text.lua (zh-CN) on each tree: the sidebar, each build view, each
Compare sub-view with the second build loaded as comparison (and the Compare Power Report), the
Trader popup and its Query Options popup, plus their drop-down lists. Prints per area the lines
drawn, the English lines, mixed lines and English lines by cause (a_unhooked: our tables have it
but the path does not look it up; b_missing: no source; c_term: PoE2DB term not looked up;
d_joined: runtime-joined text; e_name: item/build/user names). --lines also prints the English
lines. Builds are read only.
"""
import argparse
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_pob_ui_text  # noqa: E402

CHECKER = Path(__file__).resolve().parent / "check_pob_draw_text.lua"
CAUSES = ("a_unhooked", "b_missing", "c_term", "d_joined", "e_name")


def table(after, before=None):
    head = f"{'area':34} {'lines':>5} {'Eng':>5} {'mix':>4}  " + " ".join(f"{c[:1]:>4}" for c in CAUSES)
    rows = [head + ("   before: Eng/mix  a/b/c/d/e" if before else "")]
    for name in sorted(set(after["areas"]) | set((before or {"areas": {}})["areas"])):
        a = after["areas"].get(name, {"lines": 0, "english": 0, "mixed": 0, "causes": {}})
        row = (f"{name:34} {a['lines']:5} {a['english']:5} {a['mixed']:4}  "
               + " ".join(f"{(a['causes'] or {}).get(c, 0):4}" for c in CAUSES))
        if before:
            b = before["areas"].get(name, {"english": 0, "mixed": 0, "causes": {}})
            row += f"   {b['english']}/{b['mixed']}  " + "/".join(str((b['causes'] or {}).get(c, 0)) for c in CAUSES)
        rows.append(row)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pob", type=Path, required=True)
    parser.add_argument("--before", type=Path)
    parser.add_argument("--build", action="append", default=[], type=Path, required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--lines", action="store_true")
    args = parser.parse_args()
    check_pob_ui_text.CHECKER = CHECKER
    with tempfile.TemporaryDirectory() as tmp:
        after = check_pob_ui_text.run(args.pob, args.build, Path(tmp) / "after.json")
        before = check_pob_ui_text.run(args.before, args.build, Path(tmp) / "before.json") if args.before else None
    if args.out:
        args.out.write_text(json.dumps({"after": after, "before": before}, ensure_ascii=False, indent=1) + "\n",
                            encoding="utf-8")
    print("\n".join(table(after, before)))
    if args.lines:
        for name in sorted(after["areas"]):
            for entry in after["areas"][name].get("englishLines") or []:
                print(f"{name}\t{entry['cause']}\t{entry['line']}")


if __name__ == "__main__":
    main()
