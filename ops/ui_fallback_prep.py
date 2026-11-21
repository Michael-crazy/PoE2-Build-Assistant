"""P10b preprocessing: candidate Simplified/Traditional text for PoB interface strings we have not localized.

Collects the English string literals PoB draws (Classes/, Modules/), drops the ones our own tables
already cover (src/Modules/Assistant*.lua), and looks the rest up in, by priority:
  1. PoeCharm Simplified (`zh-rCN/*.csv`, `英文,中文`, `{0}` placeholders)
  2. PoB2-i18n Simplified (`src/Data/Lang/zh_CN/pob.lua`)
  3. PoB2-i18n Traditional (`src/Data/Lang/zh_TW/pob.lua`) - shown as is, a visible stopgap
Placeholders (`%s`, `%d`, `%.1f`, `{0}`) and colour codes (`^7`, `^xRRGGBB`) are normalized before matching.
Entries whose English contains a PoE2DB game term are flagged for review with the PoE2DB Chinese, because
game terms must follow PoE2DB (user rule), not PoeCharm or the Taiwan wording.

Review entries are then sorted automatically (`status`):
  likely_ui    flagged only as a capitalized word that is neither a PoE2DB name nor a name in PoB's own
               game data (src/Data): most likely interface text; a quick glance, since
               old PoE1 names in PoB (Wrath, Storm Brand) slip through
  fixed_exact  the whole string is a PoE2DB name: use the PoE2DB Chinese
  fixed_sub    every game term in it was put into PoE2DB wording (English left in the Traditional text,
               or a translation the source uses for that term where PoE2DB differs)
  manual       still needs a person
Each string also lists where PoB uses it (`sites`: file, line, kind) so P10b knows which draw path
(controls already localized at draw time, tooltips, breakdowns, warnings, config) it must hook.

Writes <out>/fallback.json (candidates) and <out>/report.txt (coverage per source and per PoB file).
Nothing is wired into PoB here; P10b does that.
"""
import argparse
import csv
import io
import json
from pathlib import Path
import re
import zipfile
from collections import Counter

LUA_STRING = re.compile(r'"((?:[^"\\\n]|\\.)*)"|\'((?:[^\'\\\n]|\\.)*)\'')
LUA_PAIR = re.compile(r'\[\s*"((?:[^"\\]|\\.)*)"\s*\]\s*=\s*"((?:[^"\\]|\\.)*)"')
COLOUR = re.compile(r"\^x[0-9A-Fa-f]{6}|\^\d")
PLACEHOLDER = re.compile(r"%[-+ #0]*\d*(?:\.\d+)?[sdfgiqx]|\{\d+\}")
LETTERS = re.compile(r"[A-Za-z]{2,}")
OWN_TABLES = ("AssistantUiText.lua", "AssistantConfigText.lua", "AssistantCalcLabels.lua", "AssistantSettings.lua")
# Not drawn as-is: mod-text parsing patterns (ModParser) and mod-name tooling; their wording reaches the
# screen only through mod lines, which P03 localizes from PoE2DB.
SKIP_FILES = {"ModParser.lua", "ModTools.lua", "ModStore.lua", "ModList.lua", "ModDB.lua"}
I18N_FILES = {"i18n-zh_CN": "src/Data/Lang/zh_CN/pob.lua", "i18n-zh_TW": "src/Data/Lang/zh_TW/pob.lua"}
SOURCES = ("poecharm", "i18n-zh_CN", "i18n-zh_TW")
# What a source line does with the literal; `control` text is localized at draw time already (P10 hooks in
# LabelControl, ButtonControl, EditControl), the others need P10b hooks.
SITE_KINDS = (
    ("tooltip", re.compile(r"AddLine|tooltip|Tooltip")),
    ("breakdown", re.compile(r"breakdown|Breakdown")),
    ("warning", re.compile(r"[Ww]arning")),
    ("config", re.compile(r"^\s*\{\s*var\s*=|\blabel\s*=|\bhelp\s*=")),
    ("control", re.compile(r"Control\b|\blabel\b|SetPlaceholder|DropDown")),
)


def lua_unescape(text):
    return re.sub(r"\\(.)", lambda m: {"n": "\n", "t": "\t"}.get(m.group(1), m.group(1)), text)


def normalize(text):
    """Matching key: no colour codes, placeholders as {#}, collapsed spaces."""
    text = COLOUR.sub("", text)
    text = PLACEHOLDER.sub("{#}", text)
    return " ".join(text.split())


def looks_like_text(text):
    """Literals PoB shows to people, not identifiers, patterns or file names."""
    plain = COLOUR.sub("", text).strip()
    if not LETTERS.search(plain) or len(plain) < 2:
        return False
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", plain) and not re.match(r"[A-Z][a-z]", plain):
        return False  # identifiers such as `mainSkill`
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+", plain):
        return False  # dotted names such as `Data.Gems`
    if re.fullmatch(r"[A-Z][a-z]+(?:[A-Z0-9][A-Za-z0-9]*)+", plain):
        return False  # internal stat and mod names such as `FireMin`, `LifeRegenPercent`
    if re.match(r"(?:Condition|Multiplier|PerStat|StatThreshold|Effective|SkillPart|Skill):[A-Za-z]", plain):
        return False  # modifier tags, not text
    if not LETTERS.search(re.sub(r"\{\d+:[^}]*\}", "", plain)):
        return False  # CalcSections number templates such as `{0:output:WardPercentCost}`
    if any(mark in plain for mark in ("%a", "%w", "%d+", "[%", "^%", "%s*", ".lua", "/", "\\")) and " " not in plain:
        return False
    return True


def site_kind(line, name):
    if name == "ConfigOptions.lua":
        return "config"
    for kind, pattern in SITE_KINDS:
        if pattern.search(line):
            return kind
    return "other"


def pob_strings(src):
    """{normalized key: {"en": first raw literal, "files": set, "sites": list}} for Classes/ and Modules/."""
    found = {}
    for folder in ("Classes", "Modules"):
        for path in sorted((src / folder).glob("*.lua")):
            if path.name in SKIP_FILES or path.name.startswith("Assistant"):
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            lines = text.split("\n")
            for match in LUA_STRING.finditer(text):
                raw = lua_unescape(match.group(1) if match.group(1) is not None else match.group(2))
                if not looks_like_text(raw):
                    continue
                key = normalize(raw)
                number = text.count("\n", 0, match.start()) + 1
                entry = found.setdefault(key, {"en": raw, "files": set(), "sites": []})
                entry["files"].add(f"{folder}/{path.name}")
                entry["sites"].append({"file": f"{folder}/{path.name}", "line": number,
                                       "kind": site_kind(lines[number - 1], path.name)})
    return found


def lua_pairs(text):
    return {lua_unescape(en): lua_unescape(zh) for en, zh in LUA_PAIR.findall(text)}


def own_keys(src):
    keys = set()
    for name in OWN_TABLES:
        path = src / "Modules" / name
        if path.exists():
            keys.update(normalize(en) for en in lua_pairs(path.read_text(encoding="utf-8")))
    return keys


def poecharm_table(folder):
    table = {}
    for path in sorted(folder.glob("*.csv")):
        if path.name in ("statDescriptions.csv",):  # mod lines: game terms, PoE2DB owns these
            continue
        for row in csv.reader(io.StringIO(path.read_text(encoding="utf-8-sig", errors="replace"))):
            if len(row) >= 2 and row[0].strip() and row[1].strip():
                table.setdefault(normalize(row[0]), row[1].strip())
    return table


def i18n_tables(zip_path):
    with zipfile.ZipFile(zip_path) as archive:
        return {source: {normalize(en): zh for en, zh in lua_pairs(archive.read(member).decode("utf-8")).items()}
                for source, member in I18N_FILES.items()}


def game_terms(*terms_dirs):
    """English -> Simplified PoE2DB names (multi-word phrases and single words of 4+ letters).

    Reads `{"en": .., "zh_hans": ..}` nodes and `{"<English>": {"zh_hans": ..}}` maps (P03 tables), including
    the name tables in a `names/` subfolder."""
    pairs = {}

    def add(en, zh):
        if isinstance(en, str) and isinstance(zh, str) and zh and 4 <= len(en) <= 40 and "{" not in en and "#" not in en:
            pairs.setdefault(en.lower(), zh)

    def walk(node):
        if isinstance(node, dict):
            add(node.get("en"), node.get("zh_hans"))
            for name, value in node.items():
                if isinstance(value, dict) and "en" not in value and isinstance(value.get("zh_hans"), str):
                    add(name, value["zh_hans"])
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    for terms_dir in terms_dirs:
        for path in sorted(terms_dir.rglob("*.json"), key=lambda p: p.name):  # same order as one flat folder
            walk(json.loads(path.read_text(encoding="utf-8")))
    return pairs


def term_hits(english, terms, longest=4):
    words = re.findall(r"[A-Za-z']+", english)
    hits = []
    for size in range(longest, 0, -1):
        for i in range(len(words) - size + 1):
            phrase = " ".join(words[i:i + size]).lower()
            if phrase in terms and not any(phrase in hit[0] for hit in hits):
                hits.append((phrase, terms[phrase]))
    return hits


def pob_game_names(src):
    """Lower-cased names in PoB's game data (gems, bases, uniques, skills), PoE2DB coverage or not."""
    names = set()
    pattern = re.compile(r'\bname\s*=\s*"([^"\n]{3,60})"|^\s*\[\s*"([A-Z][^"\n]{2,60})"\s*\]\s*=\s*\{', re.MULTILINE)
    for path in (src / "Data").rglob("*.lua"):
        for match in pattern.finditer(path.read_text(encoding="utf-8", errors="replace")):
            names.add((match.group(1) or match.group(2)).lower())
    return names


def known_term(word, terms):
    """PoE2DB name for a word or two, allowing a plural or an -ing/-ed form."""
    word = word.lower()
    for form in (word, word[:-1] if word.endswith("s") else None, re.sub(r"(?:ing|ed)$", "", word)):
        if form and form in terms:
            return terms[form]
    return None


def conflicts(entries, terms):
    """Source wording -> PoE2DB wording, learned from entries that are exactly one PoE2DB name."""
    found = {}
    for entry in entries:
        poe2db = terms.get(entry["key"].lower())
        zh = entry["zh"].strip()
        if poe2db and zh != poe2db and len(zh) >= 2 and zh not in poe2db and re.fullmatch(r"[\u4e00-\u9fff]+", zh):
            found.setdefault(zh, poe2db)
    return found


def classify(entry, terms, learned, game_names=frozenset()):
    """Set `status` (and a corrected `zh` when it can be fixed by rule) on a review entry."""
    review = entry["review"]
    exact = terms.get(entry["key"].lower())
    if exact:
        entry["zh"], entry["status"] = exact, "fixed_exact"
        return
    if review[0]["poe2db"] is None:
        name = known_term(entry["key"], terms)
        word = entry["key"].lower()
        in_pob = {word, word[:-1] if word.endswith("s") else word} & game_names
        entry["status"] = "likely_ui" if name is None and not in_pob else "manual"
        if name:
            review[0]["poe2db"] = name
        return
    zh = entry["zh"]
    for hit in review:
        zh = re.sub(re.escape(hit["term"]), hit["poe2db"], zh, flags=re.IGNORECASE)
    for wrong, right in learned.items():
        if wrong in zh:
            zh = zh.replace(wrong, right)
    if all(hit["poe2db"] in zh for hit in review):
        entry["zh"], entry["status"] = zh, "fixed_sub"
    else:
        entry["status"] = "manual"


def build(src, poecharm, i18n_zip, terms_dirs):
    strings = pob_strings(src)
    covered = own_keys(src)
    tables = {"poecharm": poecharm_table(poecharm), **i18n_tables(i18n_zip)}
    terms = game_terms(*terms_dirs)
    entries, missing = [], []
    for key, info in sorted(strings.items()):
        if key in covered:
            continue
        for source in SOURCES:
            zh = tables[source].get(key)
            if zh:
                review = [{"term": en, "poe2db": cn} for en, cn in term_hits(key, terms) if cn not in zh]
                if not review and re.fullmatch(r"[A-Z][a-z]+(?: [A-Z][a-z]+)?", key):
                    # A capitalized word or two is often a game term PoE2DB lists under another form
                    # (ailment, keystone, buff): check against PoE2DB before using.
                    review.append({"term": key.lower(), "poe2db": None})
                entries.append({"en": info["en"], "key": key, "zh": zh, "source": source,
                                "files": sorted(info["files"]), "sites": info["sites"], "review": review,
                                "status": "review" if review else "ok"})
                break
        else:
            missing.append({"en": info["en"], "key": key, "files": sorted(info["files"]), "sites": info["sites"]})
    learned = conflicts(entries, terms)
    game_names = pob_game_names(src)
    for entry in entries:
        if entry["review"]:
            classify(entry, terms, learned, game_names)
    stats = {"pob_strings": len(strings), "already_ours": sum(1 for k in strings if k in covered),
             "candidates": len(entries), "missing": len(missing),
             "by_source": {s: sum(1 for e in entries if e["source"] == s) for s in SOURCES},
             "needs_review": sum(1 for e in entries if e["review"]),
             "review_status": {s: sum(1 for e in entries if e["status"] == s)
                               for s in ("likely_ui", "fixed_exact", "fixed_sub", "manual")},
             "sites_by_kind": {group: dict(sorted(Counter(site["kind"] for e in items for site in e["sites"]).items()))
                               for group, items in (("candidates", entries), ("missing", missing))},
             "learned_conflicts": len(learned),
             "table_sizes": {s: len(t) for s, t in tables.items()}, "poe2db_terms": len(terms)}
    return {"stats": stats, "entries": entries, "missing": missing}


def report(result):
    stats = result["stats"]
    lines = ["P10b preprocessing (ops/ui_fallback_prep.py)", json.dumps(stats, ensure_ascii=False, indent=1), "",
             "per PoB file: candidates by source / missing"]
    per_file = {}
    for entry in result["entries"]:
        for name in entry["files"]:
            per_file.setdefault(name, {s: 0 for s in SOURCES} | {"missing": 0})[entry["source"]] += 1
    for entry in result["missing"]:
        for name in entry["files"]:
            per_file.setdefault(name, {s: 0 for s in SOURCES} | {"missing": 0})["missing"] += 1
    for name, counts in sorted(per_file.items(), key=lambda kv: -sum(kv[1].values())):
        lines.append(f"  {name:45} " + "  ".join(f"{k}={v}" for k, v in counts.items()))
    lines += ["", "manual review (en | candidate | PoE2DB terms)"]
    for entry in result["entries"]:
        if entry["status"] == "manual":
            terms = ", ".join(f"{r['term']}={r['poe2db']}" for r in entry["review"])
            lines.append(f"  {entry['key'][:70]} | {entry['zh'][:40]} | {terms}".replace("\n", " "))
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pob", type=Path, required=True, help="PoB tree (poe2-assistant branch), contains src/")
    parser.add_argument("--poecharm", type=Path, required=True, help="PoeCharm zh-rCN folder of CSV files")
    parser.add_argument("--i18n-zip", type=Path, required=True, help="PoB2-i18n v0.1.0 portable ZIP")
    parser.add_argument("--terms", type=Path, default=Path(__file__).resolve().parents[1] / "data/terms/poe2db-1.0")
    parser.add_argument("--pob-terms", type=Path, help="P03 tables (default <pob>/poe2-assistant/terms)")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = build(args.pob / "src", args.poecharm, args.i18n_zip,
                   [args.terms, args.pob_terms or args.pob / "poe2-assistant/terms"])
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "fallback.json").write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (args.out / "report.txt").write_text(report(result), encoding="utf-8")
    print(json.dumps(result["stats"], ensure_ascii=False))


if __name__ == "__main__":
    main()
