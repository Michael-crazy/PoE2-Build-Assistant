"""P10b: build PoB's fallback interface-text module from the P10b candidate table.

  python3 -B ops/pob_ui_fallback.py --pob <PoB tree> [--fallback data/terms/pob-ui/fallback.json]
      [--overrides data/terms/pob-ui/overrides.json]

Reads the candidates that `ops/ui_fallback_prep.py` wrote (`fallback.json`) and the reviewed
decisions (`overrides.json`, small and hand-written) and writes
`<pob>/src/Modules/AssistantUiFallback.lua`, which `AssistantUiText.fallback` reads at draw time.
Rerun after either input changes; never edit the Lua file by hand.

Which candidates are used (`status` from the prep script):
  ok, fixed_exact, fixed_sub   used, unless the overrides keep them English
  likely_ui                    used, unless the overrides keep them English (old PoE1 names,
                               game words PoE2DB does not have, wrong sense)
  manual                       with a reviewed text in `overrides.zh`, or automatically when every
                               game term the prep script flagged appears in the text in PoE2DB
                               wording (after the Traditional -> Simplified step); else English
PoB2-i18n Traditional text (`i18n-zh_TW`) is converted to Simplified with OpenCC (`tw2sp`) first.
This needs `pip install opencc-python-reimplemented` (0.1.7) where the script runs; PoB does not.
PoB item type names (`Bow`, `Body Armour: Armour/Evasion`, `Flask: Life`...) come from the PoE2DB
class table `data/terms/poe2db-1.0/names/item_classes.json` (ops/poe2db_item_classes.py), defence subtypes
from `overrides.subTypes`; types the class table lacks stay English. Currency names (Trader
max-price list) come from the PoE2DB table `data/terms/poe2db-1.0/stackable_currency.json` (V10).
Trade-site pseudo stats (Trader query options, `# Empty Prefix Modifiers`) have no PoE2DB text; they use the
Tencent trade site's own Simplified text from `data/trade/stats.json` (V10, user decision 2026-11-21).
Templates with a value at both ends and one fixed word in between are not used (V10: `%sLevel %d %s`
turned `# to Level of ...` into half Chinese).
`overrides.zh` also replaces a candidate's text or adds strings the prep script found no
candidate for. `overrides.formats` adds string.format-style templates (`%d`, `%s`, `{0}`), and
`overrides.patterns` / `overrides.plainPatterns` add Lua patterns for lines PoB joins with `..`
(matched on the drawn text / on the text without colour codes).

Buff and state names a Chinese text keeps in English (`Chaotic Might`) are replaced with the PoE2DB
name from `data/terms/poe2db-1.0/names/keywords.json` (ops/poe2db_keywords.py), else the reviewed name in
`overrides.names` (Simplified source wording the user chose, with its source). Candidates that are still an
English sentence (4+ English words in a row) are dropped.

Output tables:
  exact         key (no colour codes, collapsed spaces) -> text
  formats       anchored Lua pattern on the drawn text -> replacement (`%1`..)
  plainFormats  the same on the text without colour codes
"""
import argparse
import json
from collections import Counter
from itertools import combinations
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FALLBACK = ROOT / "data/terms/pob-ui/fallback.json"
DEFAULT_OVERRIDES = ROOT / "data/terms/pob-ui/overrides.json"
MODULE = "src/Modules/AssistantUiFallback.lua"

COLOUR = re.compile(r"\^x[0-9A-Fa-f]{6}|\^\d")
SPEC = re.compile(r"%%|%[-+#0]*\d*(?:\.\d+)?[sdfgiqx]|\{\d+\}|\{#\}")
USED = {"ok", "fixed_exact", "fixed_sub"}
LUA_MAGIC = re.compile(r"([\^$()%.\[\]*+\-?])")


def normalize(text):
    """The runtime key: no colour codes, collapsed spaces."""
    return " ".join(COLOUR.sub("", text).split())


def placeholders(text):
    """Placeholders of a template in order, `%%` left out."""
    return [m.group(0) for m in SPEC.finditer(text) if m.group(0) != "%%"]


def lua_pattern(template):
    """Anchored Lua pattern for a template; every placeholder becomes a lazy capture."""
    out, pos = ["^"], 0
    for m in SPEC.finditer(template):
        out.append(LUA_MAGIC.sub(r"%\1", template[pos:m.start()]))
        out.append("%%" if m.group(0) == "%%" else "(.-)")
        pos = m.end()
    out.append(LUA_MAGIC.sub(r"%\1", template[pos:]))
    out.append("$")
    return "".join(out)


def replacement(zh, count):
    """gsub replacement for a translated template, or None when it does not carry every value.

    `{n}` (PoeCharm) points at value n+1; `%d`/`%s`/`{#}` (PoB2-i18n, ours) take the values in order."""
    out, pos, seen, order = [], 0, [], 0
    for m in SPEC.finditer(zh):
        out.append(zh[pos:m.start()].replace("%", "%%"))
        token = m.group(0)
        if token == "%%":
            out.append("%%")
        else:
            index = int(token[1:-1]) + 1 if re.fullmatch(r"\{\d+\}", token) else order + 1
            order += 1
            if index > count:
                return None
            seen.append(index)
            out.append(f"%{index}")
        pos = m.end()
    out.append(zh[pos:].replace("%", "%%"))
    if sorted(set(seen)) != list(range(1, count + 1)):
        return None
    return "".join(out)


def literal_letters(template):
    return len(re.findall(r"[A-Za-z]", COLOUR.sub("", SPEC.sub("", template))))


def loose(template):
    """A template that starts and ends with a value and has a single fixed word in between
    (`%sLevel %d %s`) matches any text containing that word, e.g. a trade mod line."""
    plain = COLOUR.sub("", template).strip()
    marks = [m for m in SPEC.finditer(plain) if m.group(0) != "%%"]
    if not marks or marks[0].start() != 0 or marks[-1].end() != len(plain):
        return False
    return len(re.findall(r"[A-Za-z]+", SPEC.sub(" ", plain))) < 2


def recolour(en, zh):
    """Carry the English colour codes the source text dropped: the leading one, and one inner code
    that follows a value (`= %.1f ^8per second` -> `= {0} ^8每秒`)."""
    if "^" in zh:
        return zh
    lead = re.match(r"\^x[0-9A-Fa-f]{6}|\^\d", en)
    body = en[lead.end():] if lead else en
    inner = list(COLOUR.finditer(body))
    if len(inner) == 1:
        before = body[:inner[0].start()]
        k = len(placeholders(before))
        if k and re.search(r"(?:%[-+ #0]*\d*(?:\.\d+)?[sdfgiqx]|\{\d+\}|\{#\})\s*$", before):
            marks = [m for m in SPEC.finditer(zh) if m.group(0) != "%%"]
            if len(marks) >= k:
                at = marks[k - 1].end()
                rest = zh[at:]
                space = rest[:len(rest) - len(rest.lstrip())]
                zh = zh[:at] + space + inner[0].group(0) + rest.lstrip()
    if lead and not zh.startswith("^"):
        zh = lead.group(0) + zh
    return zh


def template_rules(en, zh):
    """(formats, plainFormats) rules for one template, or a reason it cannot be used."""
    count = len(placeholders(en))
    if literal_letters(en) < 3:
        return None, "too little fixed text to match safely"
    if loose(en):
        return None, "value at both ends and one fixed word: matches unrelated text"
    zh = recolour(en, zh)
    repl = replacement(zh, count)
    if repl is None:
        return None, "translation does not carry every value"
    # The drawn text may carry colour codes the template does not (values coloured by the caller),
    # so every template is also matched on the text without colour codes.
    plain_en = " ".join(COLOUR.sub("", en).split())
    return {"formats": [(lua_pattern(en), repl)],
            "plainFormats": [(lua_pattern(plain_en), replacement(COLOUR.sub("", zh), count))]}, None


ARMOUR_TYPES = ("Body Armour", "Boots", "Gloves", "Helmet", "Shield", "Buckler")


def terms_match(entry, zh):
    """Every flagged game term is in the text in PoE2DB wording (an adjective's 的 may be dropped)."""
    review = entry.get("review") or []
    if len(entry["key"].split()) <= 4 and not any(r["term"] == entry["key"].lower().rstrip(":") for r in review):
        return False  # a short name is only accepted when PoE2DB has the whole name, not a word of it
    return bool(review) and all(r.get("poe2db") and (r["poe2db"] in zh or r["poe2db"].rstrip("的") in zh)
                                for r in review)


def class_names(classes, sub_types):
    """Exact entries for PoB item type names, plain and with defence subtypes."""
    out = {}
    for pob_type, names in (classes or {}).get("pob", {}).items():
        out[pob_type] = names["zh_hans"]
        if names.get("en"):
            out[names["en"].replace("_", " ")] = names["zh_hans"]
    for armour in ARMOUR_TYPES:
        if armour not in out:
            continue
        words = list(sub_types)
        for size in range(1, len(words) + 1):
            for combo in combinations(words, size):
                out[f"{armour}: {'/'.join(combo)}"] = f"{out[armour]}：{'/'.join(sub_types[w] for w in combo)}"
    return out


UNTRANSLATED = re.compile(r"[A-Za-z][A-Za-z']*(?:[ ,]+[A-Za-z][A-Za-z']*){3,}")
CJK = re.compile(r"[一-鿿]")


def untranslated(zh):
    """A source text that is still an English sentence (4+ English words in a row), maybe with a
    game word swapped in: showing it is no better than the English."""
    return UNTRANSLATED.search(COLOUR.sub("", SPEC.sub("", zh))) is not None


def name_rules(keywords, reviewed=None):
    """(regex, Chinese) for buff and state names, longest first: PoE2DB names (keywords.json), then
    the reviewed names in `overrides.names` for the ones PoE2DB lacks (PoE2DB wins when it has one)."""
    names = {en: item["zh_hans"] for en, item in (keywords or {}).get("names", {}).items()}
    for en, item in (reviewed or {}).items():
        names.setdefault(en, item["zh"])
    return [(re.compile(r"(?<![A-Za-z])" + re.escape(en) + r"(?![A-Za-z])"), zh)
            for en, zh in sorted(names.items(), key=lambda kv: -len(kv[0]))]


def with_names(zh, rules):
    """Put PoE2DB names for the buff/state names a Chinese text kept in English."""
    if not CJK.search(zh):
        return zh
    for pattern, name in rules:
        zh = pattern.sub(name, zh)
    return zh


def currency_names(currency):
    """Exact entries for currency names (Trader max-price list) from the PoE2DB currency table."""
    out = {}
    for entry in ((currency or {}).get("currencies") or {}).values():
        if entry.get("en") and entry.get("zh_hans"):
            out[entry["en"]] = entry["zh_hans"]
    return out


def pseudo_stats(trade_stats):
    """Exact entries for the trade site's pseudo stats: English text -> Tencent trade site text."""
    return {normalize(entry["en"]): entry["zh"] for entry in (trade_stats or {}).values()
            if entry.get("type") == "pseudo" and entry.get("en") and entry.get("zh")}


def build(fallback, overrides, classes=None, to_simplified=lambda text: text, keywords=None, currency=None,
          trade_stats=None):
    names = name_rules(keywords, overrides.get("names"))
    zh_over = {normalize(key): text for key, text in overrides.get("zh", {}).items()}
    english = {normalize(key) for key in overrides.get("english", [])}
    exact, formats, plain_formats = {}, [], []
    stats = {"used_by_source": Counter(), "used_by_status": Counter(), "kept_english": Counter(),
             "overrides_zh": len(zh_over), "rejected": []}
    for entry in fallback["entries"]:
        key, status = entry["key"], entry["status"]
        if key in english:
            stats["kept_english"][status] += 1
            continue
        zh = zh_over.get(key)
        source = "override" if zh is not None else entry["source"]
        if zh is None:
            zh = to_simplified(entry["zh"]) if entry["source"] == "i18n-zh_TW" else entry["zh"]
            if status == "manual" and terms_match(entry, zh):
                status = "manual_auto"
            elif status not in USED and status != "likely_ui":
                stats["kept_english"][status] += 1
                continue
            if untranslated(zh):
                stats["kept_english"]["untranslated"] += 1
                continue
        zh = with_names(zh, names)
        if "{#}" in key:
            rules, why = template_rules(entry["en"], zh)
            if not rules:
                stats["rejected"].append({"en": entry["en"], "zh": zh, "why": why})
                stats["kept_english"][status] += 1
                continue
            formats += rules["formats"]
            plain_formats += rules.get("plainFormats", [])
        else:
            if zh.strip() == key:
                continue
            exact[key] = zh
        stats["used_by_source"][source] += 1
        stats["used_by_status"][status] += 1
    for key, zh in class_names(classes, overrides.get("subTypes", {})).items():
        if key not in zh_over:
            exact[key] = zh
            stats["used_by_source"]["poe2db-classes"] += 1
    for key, zh in currency_names(currency).items():
        if key not in zh_over and key not in exact:
            exact[key] = zh
            stats["used_by_source"]["poe2db-currency"] += 1
    for key, zh in pseudo_stats(trade_stats).items():
        if key not in zh_over and key not in exact:
            exact[key] = zh
            stats["used_by_source"]["tencent-trade-pseudo"] += 1
    known = {e["key"] for e in fallback["entries"]}
    for key, zh in zh_over.items():
        if key in known:
            continue
        zh = with_names(zh, names)
        if placeholders(key):
            rules, why = template_rules(key, zh)
            if not rules:
                raise ValueError(f"override template {key!r}: {why}")
            formats += rules["formats"]
            plain_formats += rules.get("plainFormats", [])
        else:
            exact[normalize(key)] = zh
        stats["used_by_source"]["override"] += 1
        stats["used_by_status"]["added"] += 1
    for en, zh in overrides.get("formats", []):
        rules, why = template_rules(en, zh)
        if not rules:
            raise ValueError(f"override format {en!r}: {why}")
        formats += rules["formats"]
        plain_formats += rules.get("plainFormats", [])
    patterns = [tuple(rule) for rule in overrides.get("patterns", [])]
    plain_patterns = [tuple(rule) for rule in overrides.get("plainPatterns", [])]
    # Longer fixed text first, so a specific template wins over a general one; stable order.
    rank = lambda rule: (-len(re.sub(r"\(\.-\)|%.", "", rule[0])), rule)
    tables = {"exact": exact, "formats": patterns + sorted(set(formats), key=rank),
              "plainFormats": plain_patterns + sorted(set(plain_formats), key=rank)}
    stats["tables"] = {name: len(value) for name, value in tables.items()}
    return tables, stats


def lua_string(text):
    out = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t")
    return '"' + re.sub(r"[\x00-\x08\x0b-\x1f]", lambda m: f"\\{ord(m.group(0))}", out) + '"'


def lua_module(tables, stats):
    lines = ["-- PoE2 assistant (P10b): fallback Simplified Chinese for PoB interface text.",
             "-- GENERATED by ops/pob_ui_fallback.py (project repo) from data/terms/pob-ui/fallback.json",
             "-- and data/terms/pob-ui/overrides.json. Do not edit; rerun the script.",
             "-- Used by source: " + ", ".join(f"{k} {v}" for k, v in sorted(stats["used_by_source"].items())),
             "return {", "    exact = {"]
    for key in sorted(tables["exact"]):
        lines.append(f"        [{lua_string(key)}] = {lua_string(tables['exact'][key])},")
    lines.append("    },")
    for name in ("formats", "plainFormats"):
        lines.append(f"    {name} = {{")
        for pattern, repl in tables[name]:
            lines.append(f"        {{ {lua_string(pattern)}, {lua_string(repl)} }},")
        lines.append("    },")
    lines.append("}")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pob", type=Path, required=True, help="PoB tree (poe2-assistant branch)")
    parser.add_argument("--fallback", type=Path, default=DEFAULT_FALLBACK)
    parser.add_argument("--overrides", type=Path, default=DEFAULT_OVERRIDES)
    parser.add_argument("--classes", type=Path, default=ROOT / "data/terms/poe2db-1.0/names/item_classes.json")
    parser.add_argument("--keywords", type=Path, default=ROOT / "data/terms/poe2db-1.0/names/keywords.json")
    parser.add_argument("--currency", type=Path, default=ROOT / "data/terms/poe2db-1.0/stackable_currency.json")
    parser.add_argument("--trade-stats", type=Path, default=ROOT / "data/trade/stats.json")
    parser.add_argument("--stats", type=Path, help="write the counts and rejected templates here (JSON)")
    args = parser.parse_args()
    fallback = json.loads(args.fallback.read_text(encoding="utf-8"))
    overrides = json.loads(args.overrides.read_text(encoding="utf-8"))
    classes = json.loads(args.classes.read_text(encoding="utf-8"))
    import opencc  # generation only: pip install opencc-python-reimplemented
    tw2sp = opencc.OpenCC("tw2sp").convert
    keywords = json.loads(args.keywords.read_text(encoding="utf-8")) if args.keywords.exists() else None
    currency = json.loads(args.currency.read_text(encoding="utf-8")) if args.currency.exists() else None
    tables, stats = build(fallback, overrides, classes, lambda text: tw2sp(text).replace("缺省", "默认"), keywords,
                          currency, json.loads(args.trade_stats.read_text(encoding="utf-8"))
                          if args.trade_stats.exists() else None)
    (args.pob / MODULE).write_text(lua_module(tables, stats), encoding="utf-8", newline="\n")
    summary = {k: (dict(v) if isinstance(v, Counter) else v) for k, v in stats.items() if k != "rejected"}
    summary["rejected"] = len(stats["rejected"])
    if args.stats:
        args.stats.write_text(json.dumps(dict(summary, rejected_list=stats["rejected"]), ensure_ascii=False,
                                         indent=1) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
