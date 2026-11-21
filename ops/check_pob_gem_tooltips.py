#!/usr/bin/env python3
"""Check the Chinese gem tooltips (D02) headless: English vs zh-CN, line by line.

  python3 -B ops/check_pob_gem_tooltips.py --pob <PoB tree> [--gem Fireball ...] [--out report.json]

Dumps every gem tooltip (skills tab hover and passive tree style) twice through
ops/check_pob_gem_tooltips.lua, once English and once with POE2_ASSISTANT_LOCALE=zh-CN, then
counts the lines still English in the Chinese tooltip (by kind) and checks that each Chinese
line (descriptions aside) carries the numbers of its English line. --gem prints those tooltips side by side.
Exit status 0 when no line changes its numbers and the line counts match.
"""
import argparse
import collections
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "ops/check_pob_gem_tooltips.lua"
RUNTIME = Path.home() / ".local/state/poe2-assistant/p02-runtime"
COLOUR = re.compile(r"\^x[0-9A-Fa-f]{6}|\^\d")
NUMBER = re.compile(r"\d+(?:\.\d+)?")
CJK = re.compile(r"[㐀-鿿]")


def dump(pob, locale, out, level, quality):
    src = Path(pob).resolve() / "src"
    env = dict(os.environ, POE2_ASSISTANT_TERMS_DIR=str(Path(pob).resolve() / "poe2-assistant/terms"))
    env.pop("POE2_ASSISTANT_LOCALE", None)
    if locale:
        env["POE2_ASSISTANT_LOCALE"] = locale
    prelude = ("arg = {} "
               "package.path = '../runtime/lua/?.lua;../runtime/lua/?/init.lua;' .. package.path "
               f"package.cpath = {json.dumps(str(RUNTIME / '?.so'))} .. ';' .. package.cpath "
               f"CHECK_OUT = {json.dumps(str(out))} CHECK_LEVEL = {level} CHECK_QUALITY = {quality}")
    result = subprocess.run([str(RUNTIME / "LuaJIT/src/luajit"), "-e", prelude, str(CHECKER)],
                            cwd=src, env=env, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr[-3000:])
    return json.loads(Path(out).read_text(encoding="utf-8"))


def plain(line):
    return COLOUR.sub("", line).strip()


def kind(en_line):
    """What part of the tooltip an English line is, by the colour GemTooltip gives it."""
    head = en_line.lstrip()
    if head.startswith("^x6F9A98"):
        return "header"
    if head.startswith("^x74CABF"):
        return "title"
    if head.startswith("^xBAAD85"):
        return "description"
    if en_line.startswith("   ^x7F7F7F") and ":" not in en_line:
        return "tags"
    if head.startswith(("^x8888FF", "^xF05050", "^xB8DAF1")):
        return "stat"
    return "other"


def english(line):
    text = plain(line)
    return bool(re.search(r"[A-Za-z]{2,}", text)) and not CJK.search(text)


def compare(en, zh):
    stats = {mode: collections.Counter() for mode in en}
    left = {mode: collections.Counter() for mode in en}
    failures = []
    for mode in en:
        for gem, en_lines in en[mode].items():
            zh_lines = zh[mode].get(gem, [])
            if len(en_lines) != len(zh_lines):
                failures.append({"mode": mode, "gem": gem, "problem": "line count", "en": len(en_lines), "zh": len(zh_lines)})
                continue
            for e, z in zip(en_lines, zh_lines):
                if not english(e):
                    continue
                k = kind(e)
                stats[mode][k + " lines"] += 1
                if english(z):
                    stats[mode][k + " english"] += 1
                    left[mode][plain(z)] += 1
                elif k != "description" and sorted(NUMBER.findall(plain(e))) != sorted(NUMBER.findall(plain(z))):
                    # descriptions are fixed text: "twice" / "eight" are written as 2 / 8 in Chinese
                    failures.append({"mode": mode, "gem": gem, "problem": "numbers", "en": e, "zh": z})
    return stats, left, failures


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pob", required=True, type=Path)
    parser.add_argument("--gem", action="append", default=[], help="gem id or English name to print side by side")
    parser.add_argument("--level", type=int, default=20)
    parser.add_argument("--quality", type=int, default=20)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        en = dump(args.pob, None, Path(tmp) / "en.json", args.level, args.quality)
        zh = dump(args.pob, "zh-CN", Path(tmp) / "zh.json", args.level, args.quality)
    stats, left, failures = compare(en, zh)
    for wanted in args.gem:
        ids = [g for g in en["skills"] if g == wanted or g.endswith("/" + wanted)
               or any(plain(l) == wanted for l in en["skills"][g][:1])]
        for gem in ids:
            print(f"== {gem}")
            for e, z in zip(en["skills"][gem], zh["skills"][gem]):
                print(f"  {plain(e)!s:70.70} | {plain(z)}")
    for mode in stats:
        parts = []
        for k in ("title", "header", "tags", "description", "stat", "other"):
            n = stats[mode][k + " lines"]
            if n:
                parts.append(f"{k} {n - stats[mode][k + ' english']}/{n}")
        print(f"{mode}: Chinese / English lines by kind: " + ", ".join(parts))
        print(f"{mode}: most frequent lines still English: "
              + "; ".join(f"{t} x{c}" for t, c in left[mode].most_common(12)))
    print(f"failures: {len(failures)}")
    for failure in failures[:20]:
        print("FAIL", json.dumps(failure, ensure_ascii=False))
    if args.out:
        args.out.write_text(json.dumps({"stats": {m: dict(s) for m, s in stats.items()},
                                        "english_left": {m: c.most_common() for m, c in left.items()},
                                        "failures": failures}, ensure_ascii=False, indent=1), encoding="utf-8")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
