#!/usr/bin/env python3
"""Compare our PoE2DB (编年史) tables with POBG's Simplified Chinese data by English name (report only).

  python3 -B ops/poe2db_consistency.py --pobg <POBG checkout> [--terms data/terms/poe2db-1.0]
      [--out reports/poe2db-consistency]

Both sides come from poe2db.tw /cn/ pages, parsed by different code: ours by scripts/poe2db_terms.py
and the ops/poe2db_* name scripts, POBG's by its collectors (POBG_ZH=cn, files in data/zh_cn/ over data/).
Categories, each keyed by the English text:

  item_classes  names/item_classes.json pages          <-> items/classes.json pages (label)
  bases         <class>.json base_types                 <-> items/bases.jsonl
  uniques       <class>.json uniques                    <-> items/uniques.jsonl
  gems          gem tables (skill, support, spirit,...) <-> catalog/entity_index.jsonl gem kinds
  currency      stackable_currency.json currencies      <-> currency/currency.jsonl
  keywords      names/keywords.json keywords            <-> kg/keywords.jsonl
  mod_lines     mod templates ('#' per value)           <-> items/modifiers.jsonl text lines, values -> '#'

Chinese is compared with whitespace removed and dashes unified. Nothing is changed on either side:
the output lists `differ` (both have the English, the Chinese disagrees), `only_ours`, `only_pobg`.
Writes <out>.json and <out>.md.
"""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
GEM_TABLES = ("skill_gems", "support_gems", "spirit_gems", "meta_skill_gem", "lineage_supports")
GEM_KINDS = ("skill_gem", "support_gem", "spirit_gem")
VALUE = re.compile(r"\(\s*[+-]?\d+(?:\.\d+)?\s*[—–-]\s*[+-]?\d+(?:\.\d+)?\s*\)|[+-]?\d+(?:\.\d+)?")
SPACE = re.compile(r"\s+")
LIMIT = 200   # entries listed per category and kind in the JSON (counts are always complete)


def zh_key(text):
    return SPACE.sub("", (text or "").replace("—", "-").replace("–", "-"))


def en_key(text):
    return SPACE.sub(" ", (text or "").strip()).casefold()


def template(line):
    """'+(5—8) to Dexterity' -> '+# to Dexterity' (a sign stays only when the page writes '+')."""
    return VALUE.sub(lambda m: ("+" if m.group().startswith("+") else "") + "#", line or "")


def pobg_path(pobg, rel):
    """POBG reads data/zh_cn/<rel> over data/<rel> when it exists (POBG_ZH=cn)."""
    for path in (pobg / "data/zh_cn" / rel, pobg / "data" / rel):
        if path.exists():
            return path
    return None


def jsonl(path):
    if path is None:
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class Side:
    """English key -> {Chinese key: shown Chinese}, plus the English as written."""

    def __init__(self):
        self.zh = defaultdict(dict)
        self.en = {}

    def add(self, en, zh):
        if not en:
            return
        key = en_key(en)
        self.en.setdefault(key, en.strip())
        if zh:
            self.zh[key].setdefault(zh_key(zh), zh)
        else:
            self.zh.setdefault(key, {})


def ours(terms):
    tables = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(terms.glob("*.json"))}
    sides = {name: Side() for name in ("item_classes", "bases", "uniques", "gems", "currency", "keywords", "mod_lines")}
    classes = terms / "names/item_classes.json"
    if classes.exists():
        for page in json.loads(classes.read_text(encoding="utf-8")).get("pages", {}).values():
            sides["item_classes"].add(page.get("en"), page.get("zh_hans"))
    keywords = terms / "names/keywords.json"
    if keywords.exists():
        for en, entry in json.loads(keywords.read_text(encoding="utf-8")).get("keywords", {}).items():
            sides["keywords"].add(en, entry.get("zh_hans"))
    for name, table in tables.items():
        if name == "mods":
            continue
        for base in table.get("base_types", {}).values():
            sides["bases"].add(base.get("en"), base.get("zh_hans"))
        for unique in table.get("uniques", {}).values():
            sides["uniques"].add(unique.get("en"), unique.get("zh_hans"))
        if name in GEM_TABLES:
            for gem in table.get("gems", {}).values():
                sides["gems"].add(gem.get("en"), gem.get("zh_hans"))
        for currency in table.get("currencies", {}).values():
            sides["currency"].add(currency.get("en"), currency.get("zh_hans"))
    for mod in tables.get("mods", {}).get("mods", {}).values():
        en, zh = mod.get("en") or [], mod.get("zh_hans") or []
        if len(en) == len(zh):
            for line_en, line_zh in zip(en, zh):
                sides["mod_lines"].add(template(line_en), template(line_zh))
    return sides


def pobg_sides(pobg):
    sides = {name: Side() for name in ("item_classes", "bases", "uniques", "gems", "currency", "keywords", "mod_lines")}
    classes = pobg_path(pobg, "items/classes.json")
    if classes:
        for page in json.loads(classes.read_text(encoding="utf-8")).get("pages", []):
            sides["item_classes"].add(page.get("label"), page.get("label_zh_tw"))
    for row in jsonl(pobg_path(pobg, "items/bases.jsonl")):
        sides["bases"].add(row.get("name"), row.get("name_zh_tw"))
    for row in jsonl(pobg_path(pobg, "items/uniques.jsonl")):
        sides["uniques"].add(row.get("name"), row.get("name_zh_tw"))
    for row in jsonl(pobg_path(pobg, "catalog/entity_index.jsonl")):
        if row.get("kind") in GEM_KINDS:
            sides["gems"].add(row.get("name_en"), row.get("name_zh_tw"))
    for row in jsonl(pobg_path(pobg, "currency/currency.jsonl")):
        sides["currency"].add(row.get("name"), row.get("name_zh_tw"))
    for row in jsonl(pobg_path(pobg, "kg/keywords.jsonl")):
        sides["keywords"].add(row.get("name_en"), row.get("name_zh_tw"))
    for row in jsonl(pobg_path(pobg, "items/modifiers.jsonl")):
        en, zh = (row.get("text") or "").split("\n"), (row.get("text_zh_tw") or "").split("\n")
        if row.get("text") and len(en) == len(zh):
            for line_en, line_zh in zip(en, zh):
                sides["mod_lines"].add(template(line_en), template(line_zh))
    return sides


def compare(a, b):
    """Counts and lists for one category."""
    both = sorted(set(a.zh) & set(b.zh))
    differ, same, one_side_blank = [], 0, 0
    for key in both:
        za, zb = a.zh[key], b.zh[key]
        if not za or not zb:
            one_side_blank += 1
            continue
        if set(za) & set(zb):
            same += 1
            continue
        differ.append({"en": a.en[key], "ours": sorted(za.values()), "pobg": sorted(zb.values())})
    only_ours = sorted(a.en[k] for k in set(a.zh) - set(b.zh))
    only_pobg = sorted(b.en[k] for k in set(b.zh) - set(a.zh))
    return {"counts": {"ours": len(a.zh), "pobg": len(b.zh), "both": len(both), "same": same,
                       "differ": len(differ), "no_chinese_on_one_side": one_side_blank,
                       "only_ours": len(only_ours), "only_pobg": len(only_pobg)},
            "differ": differ[:LIMIT], "only_ours": only_ours[:LIMIT], "only_pobg": only_pobg[:LIMIT]}


def check(terms, pobg):
    a, b = ours(terms), pobg_sides(pobg)
    return {name: compare(a[name], b[name]) for name in a}


def markdown(result, pobg_label):
    lines = [f"# 编年史表与 POBG 一致性（按英文名，{pobg_label}）", "",
             "| 类别 | 我们 | POBG | 两边都有 | 一致 | 中文不一致 | 一边无中文 | 仅我们 | 仅 POBG |",
             "|---|---|---|---|---|---|---|---|---|"]
    for name, part in result.items():
        c = part["counts"]
        lines.append(f"| {name} | {c['ours']} | {c['pobg']} | {c['both']} | {c['same']} | {c['differ']} | "
                     f"{c['no_chinese_on_one_side']} | {c['only_ours']} | {c['only_pobg']} |")
    for name, part in result.items():
        if not part["differ"]:
            continue
        lines += ["", f"## {name}：中文不一致（前 30 条）", ""]
        for row in part["differ"][:30]:
            lines.append(f"- {row['en']}：我们 {' / '.join(row['ours'])}；POBG {' / '.join(row['pobg'])}")
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--terms", type=Path, default=ROOT / "data/terms/poe2db-1.0")
    parser.add_argument("--pobg", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=ROOT / "reports/poe2db-consistency")
    args = parser.parse_args(argv)
    result = check(args.terms, args.pobg)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.with_suffix(".json").write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    args.out.with_suffix(".md").write_text(markdown(result, args.pobg.name), encoding="utf-8")
    print(json.dumps({k: v["counts"] for k, v in result.items()}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
