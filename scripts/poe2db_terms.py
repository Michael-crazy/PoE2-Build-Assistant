"""Build PoE2DB Simplified / Traditional Chinese / English term tables from cached pages.

Reads pages through the shared PoE2DB fetcher (``scripts/poe2db_fetch.py``: cache
``manifest.json``, ``us|cn|tw/<Class>.html``), offline unless ``--fetch`` is given (then
missing pages are fetched 4 s apart into the cache), plus optional ``poecharm/zh-rCN``. Item class pages embed a ``new ModsView({...})`` JSON object; the
us, cn and tw lists are in the same order, so mods pair by section and index and are
checked against each other. Base items, uniques and gems pair by href slug.

Output: one ``<class>.json`` per page (mods by ID, rune socketables, base types,
uniques, or gems) and, when several classes are built, ``mods.json``: every mod ID
once with its templates and the classes it appears on, for reverse matching.

Usage:
  python3 scripts/poe2db_terms.py --cache DIR [--fetch] --pob /tmp/poe2-pob-source \
      --out data/terms/poe2db-1.0 --evidence reports/poe2db-terms Rings
"""

import argparse
import csv
import html
import json
import re
import sys
import unicodedata
import urllib.parse
from collections import Counter
from pathlib import Path

import poe2db_fetch

FETCH = False   # --fetch: let _read_pages fetch pages missing from the cache
_FETCHERS = {}

TABLE_VERSION = "poe2db-1.0"
LICENSE_NOTE = (
    "PoE2DB (https://poe2db.tw) wiki content is available under CC BY-NC-SA 3.0 unless "
    "otherwise noted; bulk use pending confirmation with the site owner. "
    "Game data (c) Grinding Gear Games."
)
# ModGenerationTypeID values seen on PoE2DB item pages.
GENERATION_TYPES = {"1": "Prefix", "2": "Suffix", "3": "Unique", "5": "Corrupted"}

_NDASH = re.compile(r'<span class="ndash">\s*—\s*</span>')
_VALUE_SPAN = re.compile(r"<span class='mod-value'>(.*?)</span>")
_VALUE = re.compile(r"\((-?\d+(?:\.\d+)?)—(-?\d+(?:\.\d+)?)\)|(-?\d+(?:\.\d+)?)")
_TAG = re.compile(r"<[^>]+>")
_MOD_ID = re.compile(r"Data%5CMods%2F([^&\"]+)")


def parse_mod_text(markup):
    """Return (lines, ranges): template lines with '#' placeholders and [min, max] per value."""
    ranges = []

    def value(match):
        inner = match.group(1)

        def number(m):
            if m.group(3) is not None:
                ranges.append([float(m.group(3))] * 2)
            else:
                ranges.append([float(m.group(1)), float(m.group(2))])
            return "#"

        return _VALUE.sub(number, inner, count=1)

    text = _VALUE_SPAN.sub(value, _NDASH.sub("—", markup))
    lines = []
    for part in re.split(r"<br\s*/?>|\n", text):
        line = re.sub(r"\s+", " ", html.unescape(_TAG.sub("", part))).strip()
        if line:
            lines.append(line)
    return lines, ranges


def extract_modsview(page):
    marker = "new ModsView("
    start = page.find(marker)
    if start < 0:
        raise ValueError("page has no ModsView data")
    data, _ = json.JSONDecoder().raw_decode(page, start + len(marker))
    return data


def mod_sections(data):
    return [(k, v) for k, v in data.items() if isinstance(v, list) and v and isinstance(v[0], dict)]


def mod_id(entry):
    if entry.get("Code"):
        return entry["Code"]
    m = _MOD_ID.search(entry.get("hover", ""))
    return urllib.parse.unquote(m.group(1)) if m else None


def link_text(markup):
    return re.sub(r"\s+", " ", html.unescape(_TAG.sub("", markup))).strip()


def _cards(page):
    # Tab ids are localised (RingsItem / 戒指物品), so scan every tab pane's cards.
    cards = []
    for pane in page.split('class="tab-pane')[1:]:
        cards.extend(pane.split('<div class="col">')[1:])
    return cards


def _slug(href, seen):
    """href slug; repeated cards (variants such as Two-Stone Ring) get '#2', '#3' in page order."""
    slug = re.sub(r"^/(us|cn|tw)/", "", href)
    seen[slug] += 1
    return slug if seen[slug] == 1 else f"{slug}#{seen[slug]}"


def _lines(card, cls):
    lines = []
    for part in re.findall(rf'<div class="{cls}">(.*?)</div>', card, re.S):
        lines.extend(parse_mod_text(part)[0])
    return lines


def parse_items(page):
    """Base types and uniques keyed by href slug."""
    bases, uniques, seen = {}, {}, Counter()
    for card in _cards(page):
        m = re.search(r'<a class="whiteitem[^"]*"[^>]*href="([^"]+)">([^<]+)</a>', card)
        if m:
            bases[_slug(m.group(1), seen)] = {"name": html.unescape(m.group(2)).strip(),
                                        "implicits": _lines(card, "implicitMod")}
            continue
        m = re.search(r'<a class="UniqueItem"[^>]*href="([^"]+)"><span class="uniqueName">(.*?)</span>\s*'
                      r'<span class="uniqueTypeLine">(.*?)</span>', card)
        if m:
            uniques[_slug(m.group(1), seen)] = {"name": link_text(m.group(2)), "base": link_text(m.group(3)),
                                                "implicits": _lines(card, "implicitMod"),
                                                "explicits": _lines(card, "explicitMod")}
    return bases, uniques


def _range_key(ranges):
    return sorted(tuple(r) for r in ranges)


LANGS = (("zh_hans", "cn"), ("zh_hant", "tw"))


SOCKET_SECTIONS = ("socketable", "bonded")
_SOCKET_BASE = re.compile(r"BaseItemTypes%2F([^&\"]+)")


ESSENCE_SECTIONS = ("essence", "perfect_essence")


def pick_one_lines(us_data):
    """Essence display lines shared by several mod IDs, e.g. '+# to Strength, Dexterity or
    Intelligence' or a defence line that picks the mod matching the base."""
    ids = {}
    for section, entries in mod_sections(us_data):
        if section in ESSENCE_SECTIONS:
            for entry in entries:
                ids.setdefault(tuple(parse_mod_text(entry["str"])[0]), set()).add(mod_id(entry))
    return {text for text, idents in ids.items() if len(idents) > 1}


def pair_mods(us_data, cn_data, tw_data=None, socketables=None, mods=None, resolve_id=None):
    """Pair cn/tw mod lists with us by section and index. Returns (mods by id, mismatches).

    Rune and soul core lines (socketable/bonded) carry no mod ID; when a socketables dict
    is given they are collected there, keyed by the socketable's base item ID. Pass mods
    to merge several pages (attribute sub-pages) into one class table. Entries whose hover
    is a hashed link carry no ID; resolve_id(entry, en_lines) may supply it."""
    mods = {} if mods is None else mods
    mismatches = []
    pick_one = pick_one_lines(us_data)
    pages = [(lang, side, dict(mod_sections(data)))
             for (lang, side), data in zip(LANGS, (cn_data, tw_data)) if data is not None]
    for section, us_list in mod_sections(us_data):
        for _, side, sections in pages:
            if len(sections.get(section, [])) != len(us_list):
                mismatches.append({"section": section, "problem": "list length", "side": side,
                                   "us": len(us_list), side: len(sections.get(section, []))})
        for index, us in enumerate(us_list):
            ident = mod_id(us)
            en_lines, en_ranges = parse_mod_text(us["str"])
            if ident is None and resolve_id and section not in SOCKET_SECTIONS:
                ident = resolve_id(us, en_lines)
            record = {
                "id": ident, "section": section, "index": index,
                "family": us.get("ModFamilyList", []), "generation_type": us.get("ModGenerationTypeID"),
                "level": int(us["Level"]), "en": en_lines, "ranges": en_ranges,
            }
            socket = None
            if ident is None and section in SOCKET_SECTIONS and socketables is not None:
                m = _SOCKET_BASE.search(us.get("Name", ""))
                socket = urllib.parse.unquote(m.group(1)) if m else None
            problems = [] if ident is not None or socket else ["no mod id on us entry"]
            names = {}
            for lang, side, sections in pages:
                local_list = sections.get(section, [])
                local = local_list[index] if index < len(local_list) else None
                if local is None:
                    problems.append(f"missing on {side} page")
                    continue
                zh_lines, zh_ranges = parse_mod_text(local["str"])
                record[lang] = zh_lines
                names[lang] = local.get("Name", "")
                for key in ("ModFamilyList", "ModGenerationTypeID", "Level"):
                    if us.get(key) != local.get(key):
                        problems.append(f"{key}: us={us.get(key)!r} {side}={local.get(key)!r}")
                if _range_key(en_ranges) != _range_key(zh_ranges):
                    problems.append(f"ranges: us={en_ranges} {side}={zh_ranges}")
                if len(en_lines) != len(zh_lines):
                    problems.append(f"line count: us={len(en_lines)} {side}={len(zh_lines)}")
                local_ident = local.get("Code") or (local.get("Name") if us.get("Name") == ident else None)
                if local_ident and local_ident != ident:
                    problems.append(f"id: us={ident} {side}={local_ident}")
            if socket and not problems:
                entry = socketables.setdefault(socket, {"name": {"en": link_text(us.get("Name", "")),
                                                                 **{l: link_text(n) for l, n in names.items()}},
                                                        "lines": []})
                line = {k: record[k] for k in ("en", "zh_hans", "zh_hant", "ranges") if k in record}
                entry["lines"].append(dict(line, section=section))
                continue
            if section in ESSENCE_SECTIONS:
                record["essence"] = {"en": link_text(us.get("Name", "")),
                                     **{lang: link_text(name) for lang, name in names.items()}}
            elif us.get("Name") and us.get("Name") != ident:
                record["affix"] = {"en": us["Name"], **names}
            if problems:
                mismatches.append({"section": section, "index": index, "id": ident, "en": en_lines,
                                   **{lang: record.get(lang) for lang, _, _ in pages}, "problems": problems})
                continue
            _merge(mods, record, mismatches, section in ESSENCE_SECTIONS and tuple(en_lines) in pick_one)
    return mods, mismatches


TEXT_KEYS = ("en", "zh_hans", "zh_hant", "ranges")


def _merge(mods, record, mismatches, pick_one=False):
    """pick_one: the record's text is an essence pick-one line; it goes on the essence
    entry only, and the mod's own text comes from a section that shows it."""
    ident = record["id"]
    section = record.pop("section")
    record.pop("index")
    essence = record.pop("essence", None)
    if pick_one:
        essence = dict(essence, line={k: record.pop(k) for k in TEXT_KEYS if k in record})
    existing = mods.get(ident)
    if existing is None:
        record["sections"] = [section]
        record["essences"] = [essence] if essence else []
        mods[ident] = record
        return
    if pick_one or "en" not in existing:
        if "en" not in existing and not pick_one:
            existing.update({k: record[k] for k in TEXT_KEYS + ("affix",) if k in record})
        if section not in existing["sections"]:
            existing["sections"].append(section)
        if essence and essence not in existing["essences"]:
            existing["essences"].append(essence)
        return
    if essence and existing["en"] != record["en"]:
        # Essences such as "+# to Strength, Dexterity or Intelligence" show a pick-one line
        # for several mod IDs; keep that display text on the essence entry.
        essence = dict(essence, line={k: record[k] for k in ("en", "zh_hans", "zh_hant") if k in record})
        if essence not in existing["essences"]:
            existing["essences"].append(essence)
        return
    for key in ("en", "zh_hans", "zh_hant", "ranges", "family", "level"):
        if existing.get(key) != record.get(key):
            mismatches.append({"section": section, "id": ident, "problems": [
                f"repeated id differs in {key}: {existing.get(key)!r} vs {record.get(key)!r}"]})
            return
    if section not in existing["sections"]:
        existing["sections"].append(section)
    if essence and essence not in existing["essences"]:
        existing["essences"].append(essence)
    if "affix" in record and "affix" not in existing:
        existing["affix"] = record["affix"]


def pair_items(us_items, cn_items, kind, tw_items=None):
    """Pair items by slug; slugs missing from a side are reported, not paired."""
    pairs, mismatches = {}, []
    sides = [(lang, side, items) for (lang, side), items in zip(LANGS, (cn_items, tw_items)) if items is not None]
    for slug in sorted(set(us_items).union(*(items for _, _, items in sides))):
        us = us_items.get(slug)
        missing = [side for side, items in [("us", us_items)] + [(s, i) for _, s, i in sides] if slug not in items]
        if missing:
            mismatches.append({"kind": kind, "slug": slug, "problems": ["missing on " + "/".join(missing)]})
            continue
        entry = {"en": us["name"], **{lang: items[slug]["name"] for lang, _, items in sides}}
        if "base" in us:
            entry["base"] = {"en": us["base"], **{lang: items[slug]["base"] for lang, _, items in sides}}
        problems, dropped = [], set()
        for key in ("implicits", "explicits"):
            if key not in us:
                continue
            en_lines = us[key]
            entry[key] = [{"en": e} for e in en_lines]
            for lang, side, items in sides:
                zh_lines = items[slug][key]
                if [x.count("#") for x in en_lines] != [x.count("#") for x in zh_lines]:
                    problems.append(f"{key} differ: us={en_lines} {side}={zh_lines}")
                    dropped.add(lang)
                    continue
                for line, z in zip(entry[key], zh_lines):
                    line[lang] = z
        if problems:
            # A page that breaks a line differently (tw writes From Nothing's two lines as one) only
            # loses that language; the item is kept while the Simplified (Tencent) side agrees.
            kept = LANGS[0][0] not in dropped
            mismatches.append({"kind": kind, "slug": slug, "en": us["name"], "problems": problems,
                               **({"kept_without": sorted(dropped)} if kept else {})})
            if not kept:
                continue
            for key in ("implicits", "explicits"):
                for line in entry.get(key, []):
                    for lang in dropped:
                        line.pop(lang, None)
        pairs[slug] = entry
    return pairs, mismatches


# --- gems -------------------------------------------------------------------

# Gem links are coloured (gem_red/gem_green/gem_blue) or plain "gemitem" (gems without a colour,
# e.g. grenades, crossbow and most newer skills); both are gems, the colour is "" for the latter.
_GEM_LINK = re.compile(r'<a class="gem(?:_(\w+)|item)" data-hover="([^"]*)" href="/(?:us|cn|tw)/([^"]+)">([^<]+)</a>(.*?)'
                       r'(?=<a class="gem(?:_\w+|item)" data-hover="[^"]*" href="/(?:us|cn|tw)/[^"]+">[^<]+</a>|$)', re.S)
_GEM_TAGS = re.compile(r'<div class="(?:gem_tags small|default)">(.*?)</div>', re.S)
_KEYWORD = re.compile(r'<a data-keyword="(\w+)"[^>]*>([^<]*)</a>|<a class="GemTags KeywordPopups" href="(\w+)"[^>]*>([^<]*)</a>')


def parse_gems(page):
    """Gems keyed by href slug: colour, tags (keyword id -> text), description lines.

    Gem lists come as tables (name and tags) or cards (also a description), depending
    on page and language, so only name and tags are compared across languages."""
    gems = {}
    for colour, hover, href, name, rest in _GEM_LINK.findall(page):
        slug = urllib.parse.unquote(href)
        if slug in gems:
            continue
        tags_html = _GEM_TAGS.search(rest)
        tags = []
        if tags_html and tags_html.start() < 20:
            for m in _KEYWORD.finditer(tags_html.group(1)):
                tags.append([m.group(1) or m.group(3), link_text(m.group(2) or m.group(4))])
        effect = re.search(r"GemEffects%2F([^&\"]+)", hover)
        gem = {"name": html.unescape(name).strip(), "colour": colour, "tags": tags}
        if effect:
            gem["gem_effect"] = urllib.parse.unquote(effect.group(1))
        if tags_html and tags_html.start() < 20:
            desc = rest[tags_html.end():].split("</div>", 1)[0]
            lines = parse_mod_text(desc)[0] if "<tr" not in desc else []
            if lines:
                gem["description"] = lines
        gems[slug] = gem
    return gems


def pair_gems(us_gems, localized):
    """localized: {lang: gems}. Pair names and tag texts by slug and tag order."""
    pairs, mismatches = {}, []
    for slug in sorted(set(us_gems).union(*localized.values())):
        missing = [lang for lang, gems in [("en", us_gems)] + list(localized.items()) if slug not in gems]
        if missing:
            mismatches.append({"kind": "gem", "slug": slug, "problems": ["missing in " + "/".join(missing)]})
            continue
        us = us_gems[slug]
        entry = {"en": us["name"], **{lang: gems[slug]["name"] for lang, gems in localized.items()},
                 "colour": us["colour"], "tags": [{"id": k, "en": t} for k, t in us["tags"]]}
        if "gem_effect" in us:
            entry["gem_effect"] = us["gem_effect"]
        problems = []
        for lang, gems in localized.items():
            local = gems[slug]
            # Card layouts name tags by page link (Support) rather than keyword id (SupportGem).
            if len(local["tags"]) != len(us["tags"]):
                problems.append(f"tag count differs in {lang}: {us['tags']} vs {local['tags']}")
            for tag, (_, text) in zip(entry["tags"], local["tags"]):
                tag[lang] = text
            if "description" in local:
                entry.setdefault("description", {})[lang] = local["description"]
        if "description" in us:
            entry.setdefault("description", {})["en"] = us["description"]
        if problems:
            mismatches.append({"kind": "gem", "slug": slug, "en": us["name"], "problems": problems})
        pairs[slug] = entry
    return pairs, mismatches


def load_pob_gems(pob_root):
    """Gem string fields (name, baseTypeName, gameId, variantId, ...) from PoB src/Data/Gems.lua."""
    text = (Path(pob_root) / "src" / "Data" / "Gems.lua").read_text(encoding="utf-8")
    return [dict(re.findall(r'\n\t\t(\w+) = "((?:[^"\\]|\\.)*)"', block))
            for block in re.findall(r'\n\t\["[^"]+"\] = \{(.*?)\n\t\}', text, re.S)]


def fold_name(name):
    """Oisín's Oath -> oisin's oath: PoB names drop diacritics."""
    return "".join(c for c in unicodedata.normalize("NFKD", name) if not unicodedata.combining(c)).lower()


POB_GEM_KEYS = ("gameId", "variantId", "grantedEffectId")


def gem_pob_join(gems, pob_gems):
    """Join by PoB name, then diacritic-folded name, baseTypeName, then PoE2DB GemEffects ID = variantId."""
    lookups = {"name": {}, "folded_name": {}, "baseTypeName": {}, "variantId": {}}
    for fields in pob_gems:
        for key, value in (("name", fields.get("name")), ("folded_name", fold_name(fields.get("name", ""))),
                           ("baseTypeName", fields.get("baseTypeName")), ("variantId", fields.get("variantId"))):
            if value:
                lookups[key].setdefault(value, {k: fields[k] for k in POB_GEM_KEYS if k in fields})
    report = {"joined": 0, "joined_by": Counter(), "missing_in_pob": []}
    for slug, gem in gems.items():
        keys = {"name": gem["en"], "folded_name": fold_name(gem["en"]), "baseTypeName": gem["en"],
                "variantId": gem.get("gem_effect")}
        by = next((k for k, v in keys.items() if v and v in lookups[k]), None)
        if by is None:
            report["missing_in_pob"].append({"slug": slug, "en": gem["en"], "gem_effect": gem.get("gem_effect")})
            continue
        report["joined"] += 1
        report["joined_by"][by] += 1
        gem["pob"] = lookups[by][keys[by]]
    report["joined_by"] = dict(report["joined_by"])
    return report


# --- PoB join ---------------------------------------------------------------

_POB_MOD = re.compile(r'^\t\["([^"]+)"\] = \{ (?:type = "([^"]*)", )?affix = "((?:[^"\\]|\\.)*)", (.*?)statOrder', re.M)
_LUA_STR = re.compile(r'"((?:[^"\\]|\\.)*)"')


def load_pob_mods(pob_root):
    mods = {}
    for path in sorted((Path(pob_root) / "src" / "Data").glob("Mod*.lua")):
        for m in _POB_MOD.finditer(path.read_text(encoding="utf-8")):
            lines = [s.replace('\\"', '"') for s in _LUA_STR.findall(m.group(4))]
            level = re.search(r"\blevel = (\d+)", m.string[m.end():m.string.find("\n", m.end())])
            mods.setdefault(m.group(1), {"file": path.name, "type": m.group(2), "affix": m.group(3),
                                         "level": int(level.group(1)) if level else None, "lines": lines})
    return mods


def pob_id_resolver(pob_mods):
    """Mod ID from PoB by affix name, level and template, when exactly one PoB mod fits."""
    index = {}
    for ident, mod in pob_mods.items():
        key = (mod["affix"], mod["level"], tuple(number_key(x) for x in mod["lines"]))
        index.setdefault(key, []).append(ident)

    def resolve(entry, en_lines):
        found = index.get((entry.get("Name"), int(entry["Level"]), tuple(number_key(x) for x in en_lines)), [])
        return found[0] if len(found) == 1 else None
    return resolve


def number_key(text):
    """Template comparison key: every number or range becomes '#', signs and spacing dropped."""
    text = re.sub(r"\{\d+\}", "#", text)
    text = re.sub(r"\(-?\d+(?:\.\d+)?[-—]-?\d+(?:\.\d+)?\)|-?\d+(?:\.\d+)?", "#", text)
    text = re.sub(r"[+-]#", "#", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def pob_join(mods, pob_mods, id_scope):
    """Join page mods to PoB by ID. id_scope: PoB IDs that can roll on this item class."""
    report = {"joined": 0, "text_differs": [], "missing_in_pob": [], "missing_on_page": []}
    for ident, mod in sorted(mods.items()):
        pob = pob_mods.get(ident)
        if pob is None:
            report["missing_in_pob"].append({"id": ident, "en": mod.get("en"), "sections": mod["sections"]})
            continue
        report["joined"] += 1
        mod["pob_file"] = pob["file"]
        if "en" in mod and [number_key(x) for x in mod["en"]] != [number_key(x) for x in pob["lines"]]:
            report["text_differs"].append({"id": ident, "poe2db": mod["en"], "pob": pob["lines"]})
    report["missing_on_page"] = sorted(set(id_scope) - set(mods))
    return report


def load_pob_base_tags(pob_root):
    """PoB base name -> set of item tags, from src/Data/Bases/*.lua."""
    bases = {}
    for path in sorted((Path(pob_root) / "src" / "Data" / "Bases").glob("*.lua")):
        text = path.read_text(encoding="utf-8")
        for m in re.finditer(r'itemBases\["((?:[^"\\]|\\.)*)"\] = \{[^{}]*?\n\ttags = \{ (.*?)\}', text, re.S):
            bases[m.group(1)] = set(re.findall(r"(\w+) = true", m.group(2)))
    return bases


def pob_ids_for_tags(pob_root, tag_sets):
    """PoB mod IDs that can roll on an item with any of tag_sets.

    As in the game, the first weightKey the item has decides the weight."""
    ids = []
    for path in sorted((Path(pob_root) / "src" / "Data").glob("Mod*.lua")):
        for line in path.read_text(encoding="utf-8").splitlines():
            m = re.match(r'\t\["([^"]+)"\].*?weightKey = \{ (.*?)\}, weightVal = \{ (.*?) \}', line)
            if not m:
                continue
            keys = _LUA_STR.findall(m.group(2))
            vals = [v.strip() for v in m.group(3).split(",")]
            for tags in tag_sets:
                hit = next((i for i, k in enumerate(keys) if k in tags), None)
                if hit is not None and hit < len(vals) and vals[hit] not in ("0", ""):
                    ids.append(m.group(1))
                    break
    return ids


# --- PoeCharm cross-check --------------------------------------------------

def load_csv_pairs(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return [row for row in csv.reader(f) if len(row) == 2]


def zh_key(text):
    return re.sub(r"\s+", "", number_key(text))


def poecharm_check(mods, bases, uniques, poecharm_dir):
    root = Path(poecharm_dir)
    stats = {}
    for en, zh in load_csv_pairs(root / "statDescriptions.csv"):
        stats.setdefault(number_key(en), []).append(zh)
    names = {}
    for path in sorted(root.glob("Items_*.csv")) + sorted(root.glob("Uniques*.csv")):
        for en, zh in load_csv_pairs(path):
            names.setdefault(en, set()).add(zh)
    report = {"mod_lines": {"agree": 0, "differ": [], "absent": []},
              "names": {"agree": 0, "differ": [], "absent": []}}
    seen = set()
    for ident, mod in sorted(mods.items()):
        for en, zh in zip(mod.get("en", []), mod.get("zh_hans", [])):
            if en in seen:
                continue
            seen.add(en)
            candidates = stats.get(number_key(en))
            bucket = report["mod_lines"]
            if not candidates:
                bucket["absent"].append({"id": ident, "en": en, "poe2db": zh})
            elif any(zh_key(c) == zh_key(zh) for c in candidates):
                bucket["agree"] += 1
            else:
                bucket["differ"].append({"id": ident, "en": en, "poe2db": zh, "poecharm": candidates})
    name_pairs = [(v["en"], v["zh_hans"]) for v in bases.values()]
    name_pairs += [(v["en"], v["zh_hans"]) for v in uniques.values()]
    for en, zh in sorted(set(name_pairs)):
        bucket = report["names"]
        if en not in names:
            bucket["absent"].append({"en": en, "poe2db": zh})
        elif zh in names[en]:
            bucket["agree"] += 1
        else:
            bucket["differ"].append({"en": en, "poe2db": zh, "poecharm": sorted(names[en])})
    return report


# --- driver ----------------------------------------------------------------

GEM_PAGES = {"Skill_Gems", "Support_Gems", "Spirit_Gems", "Meta_Skill_Gem", "Lineage_Supports"}
_ATTRS = ("str", "dex", "int", "str_dex", "str_int", "dex_int")
# Class pages that list only items; their mod lists are on these sub-pages.
SUBPAGES = {
    "Body_Armours": [f"Body_Armours_{a}" for a in _ATTRS + ("str_dex_int",)],
    **{c: [f"{c}_{a}" for a in _ATTRS] for c in ("Helmets", "Gloves", "Boots")},
    "Shields": ["Shields_str", "Shields_str_dex", "Shields_str_int"],
    "Jewels": ["Ruby", "Emerald", "Sapphire", "Diamond", "Timeless_Jewel", "Basic_Jewel"],
    # Mods that only spawn on the "cannon" base (grenade cooldown suffixes) are on its own
    # base page, not on the class page.
    "Crossbows": ["Trarthan_Cannon"],
}
SIDES = ("us",) + tuple(side for _, side in LANGS)
CURRENCY_PAGES = {"Stackable_Currency"}
# Short currency ids used in "~b/o 5 exalted" price notes (PoE2 trade site), by page slug.
# Written by hand from the trade site's currency list; ids not listed here stay unknown.
TRADE_IDS = {
    "Orb_of_Transmutation": "transmute", "Greater_Orb_of_Transmutation": "greater-orb-of-transmutation",
    "Perfect_Orb_of_Transmutation": "perfect-orb-of-transmutation",
    "Orb_of_Augmentation": "aug", "Greater_Orb_of_Augmentation": "greater-orb-of-augmentation",
    "Perfect_Orb_of_Augmentation": "perfect-orb-of-augmentation",
    "Orb_of_Chance": "chance", "Orb_of_Alchemy": "alch",
    "Regal_Orb": "regal", "Greater_Regal_Orb": "greater-regal-orb", "Perfect_Regal_Orb": "perfect-regal-orb",
    "Exalted_Orb": "exalted", "Greater_Exalted_Orb": "greater-exalted-orb", "Perfect_Exalted_Orb": "perfect-exalted-orb",
    "Chaos_Orb": "chaos", "Greater_Chaos_Orb": "greater-chaos-orb", "Perfect_Chaos_Orb": "perfect-chaos-orb",
    "Vaal_Orb": "vaal", "Divine_Orb": "divine", "Orb_of_Annulment": "annul", "Mirror_of_Kalandra": "mirror",
    "Artificers_Orb": "artificers", "Scroll_of_Wisdom": "wisdom", "Armourers_Scrap": "scrap",
    "Blacksmiths_Whetstone": "whetstone", "Arcanists_Etcher": "etcher", "Glassblowers_Bauble": "bauble",
    "Gemcutters_Prism": "gcp", "Lesser_Jewellers_Orb": "lesser-jewellers-orb",
    "Greater_Jewellers_Orb": "greater-jewellers-orb", "Perfect_Jewellers_Orb": "perfect-jewellers-orb",
    "Fracturing_Orb": "fracturing-orb", "Hinekoras_Lock": "hinekoras-lock",
    "Transmutation_Shard": "transmutation-shard", "Chance_Shard": "chance-shard",
    "Regal_Shard": "regal-shard", "Artificers_Shard": "artificers-shard",
}
_CURRENCY_LINK = re.compile(r'<a class="item_currency[^"]*"[^>]*href="([^"]+)">(?:<img[^>]*>)?([^<]+)</a>')


def parse_currency(page):
    """Currency names keyed by href slug; returns (names, slugs listed twice with different names)."""
    names, clashes = {}, []
    for href, name in _CURRENCY_LINK.findall(page):
        slug, name = urllib.parse.unquote(href), html.unescape(name).strip()
        if names.setdefault(slug, name) != name:
            clashes.append(slug)
    return names, clashes


def pair_currency(us_names, localized):
    """localized: {lang: names}. Pair by slug; trade ids from TRADE_IDS."""
    pairs, mismatches = {}, []
    for slug in sorted(set(us_names).union(*localized.values())):
        missing = [lang for lang, names in [("en", us_names)] + list(localized.items()) if slug not in names]
        if missing:
            mismatches.append({"kind": "currency", "slug": slug, "problems": ["missing in " + "/".join(missing)]})
            continue
        entry = {"en": us_names[slug], **{lang: names[slug] for lang, names in localized.items()}}
        if slug in TRADE_IDS:
            entry["trade_id"] = TRADE_IDS[slug]
        pairs[slug] = entry
    for slug in sorted(set(TRADE_IDS) - set(pairs)):
        mismatches.append({"kind": "currency", "slug": slug, "problems": ["trade id slug not on page"]})
    return pairs, mismatches


def _metadata(item_class, sides, manifest, **extra):
    files = {f"{side}/{page}.html" for side in sides for page in [item_class] + SUBPAGES.get(item_class, [])}
    return {
        "version": TABLE_VERSION, "item_class": item_class,
        "site_version": manifest.get("site_version"),
        "sources": [p for p in manifest.get("pages", []) if p.get("file") in files],
        "license": LICENSE_NOTE, "manifest_license_note": manifest.get("license_note"),
        "languages": ["en"] + [lang for lang, side in LANGS if side in sides],
        **extra,
    }


def _fetcher(cache):
    key = (str(cache), FETCH)
    if key not in _FETCHERS:
        _FETCHERS[key] = poe2db_fetch.Fetcher(cache, offline=not FETCH, log=lambda m: print("fetch", m, flush=True))
    return _FETCHERS[key]


def _read_pages(cache, page):
    """Pages from the shared fetcher (cache/<side>/<page>.html or wherever the manifest says), or the
    flat test layout cache/<page>.<side>.html."""
    pages = {}
    for side in SIDES:
        flat = cache / f"{page}.{side}.html"
        text = _fetcher(cache).page(side, page)
        if text is None and flat.exists():
            text = flat.read_text(encoding="utf-8")
        if text is not None:
            pages[side] = text
    return pages


def _modsviews(pages):
    data = {}
    for side, page in pages.items():
        try:
            data[side] = extract_modsview(page)
        except ValueError:
            pass  # hub pages (armour, shields, jewels, runes) list items only
    return data


def build_class(cache, item_class, manifest, resolve_id=None):
    """Returns (table, mismatches, us ModsView data list). Missing tw pages are skipped.

    Mods of SUBPAGES are merged into their parent class table."""
    pages = _read_pages(cache, item_class)
    if item_class in CURRENCY_PAGES:
        parsed = {side: parse_currency(page) for side, page in pages.items()}
        currencies, mismatches = pair_currency(parsed["us"][0], {
            lang: parsed[side][0] for lang, side in LANGS if side in parsed})
        mismatches += [{"kind": "currency", "slug": slug, "side": side, "problems": ["listed twice with different names"]}
                       for side, (_, clashes) in parsed.items() for slug in clashes]
        meta = _metadata(item_class, pages, manifest,
                         currency_join="currencies pair by href slug; 'trade_id' is the short id used in "
                                       "'~b/o' / '~price' notes, written by hand for common currencies")
        return {"metadata": meta, "currencies": currencies}, mismatches, []
    if item_class in GEM_PAGES:
        gems, mismatches = pair_gems(parse_gems(pages["us"]), {
            lang: parse_gems(pages[side]) for lang, side in LANGS if side in pages})
        meta = _metadata(item_class, pages, manifest,
                         gem_join="gems pair by href slug; 'pob' holds PoB Data/Gems.lua ids joined by English name")
        return {"metadata": meta, "gems": gems}, mismatches, []
    mismatches, mods, socketables, us_data = [], {}, {}, []
    for page in [item_class] + SUBPAGES.get(item_class, []):
        data = _modsviews(pages if page == item_class else _read_pages(cache, page))
        if "us" not in data:
            continue
        _, page_mm = pair_mods(data["us"], data.get("cn"), data.get("tw"), socketables, mods, resolve_id)
        mismatches += [dict(m, page=page) for m in page_mm]
        us_data.append(data["us"])
    items = {side: parse_items(page) for side, page in pages.items()}
    bases, base_mm = pair_items(items["us"][0], items["cn"][0], "base", items.get("tw", (None,))[0])
    uniques, unique_mm = pair_items(items["us"][1], items["cn"][1], "unique", items.get("tw", (None, None))[1])
    meta = _metadata(item_class, pages, manifest,
                     item_class_code=us_data[0].get("opt", {}).get("ItemClassesCode") if us_data else None,
                     mods_source=("ModsView" if us_data else "none: page embeds no ModsView data"),
                     placeholders="'#' replaces each rolled value; ranges lists [min, max] per '#' in English order",
                     generation_types=GENERATION_TYPES)
    table = {"metadata": meta, "mods": mods, "socketables": socketables, "base_types": bases, "uniques": uniques}
    return table, mismatches + base_mm + unique_mm, us_data


def merge_mods(tables):
    """One reverse-matching index: mod ID -> texts plus the classes it appears on."""
    merged, conflicts = {}, []
    for item_class, table in tables.items():
        for ident, mod in table.get("mods", {}).items():
            entry = {k: mod[k] for k in TEXT_KEYS + ("family", "generation_type", "level", "affix") if k in mod}
            existing = merged.get(ident)
            if existing is None:
                merged[ident] = dict(entry, classes=[item_class], essences=[])
            elif "en" not in entry or "en" not in existing:
                for k, v in entry.items():
                    existing.setdefault(k, v)
                existing["classes"].append(item_class)
            elif any(existing.get(k) != entry.get(k) for k in ("en", "zh_hans", "zh_hant")):
                conflicts.append({"id": ident, "classes": existing["classes"] + [item_class],
                                  "first": {k: existing.get(k) for k in ("en", "zh_hans", "zh_hant")},
                                  "other": {k: entry.get(k) for k in ("en", "zh_hans", "zh_hant")}})
                existing["classes"].append(item_class)
            else:
                existing["classes"].append(item_class)
            for essence in mod.get("essences", []):
                if essence not in merged[ident]["essences"]:
                    merged[ident]["essences"].append(essence)
    return merged, conflicts


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cache", required=True, type=Path)
    parser.add_argument("--pob", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--fetch", action="store_true", help="fetch pages missing from the cache (4 s apart)")
    parser.add_argument("classes", nargs="+", help="page names, e.g. Rings Amulets Skill_Gems")
    args = parser.parse_args(argv)
    global FETCH
    FETCH = args.fetch
    manifest_path = args.cache / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    pob_mods = load_pob_mods(args.pob) if args.pob else None
    pob_bases = load_pob_base_tags(args.pob) if args.pob else None
    resolve_id = pob_id_resolver(pob_mods) if pob_mods else None
    pob_gems = load_pob_gems(args.pob) if args.pob and (args.pob / "src/Data/Gems.lua").exists() else None
    args.out.mkdir(parents=True, exist_ok=True)
    if args.evidence:
        args.evidence.mkdir(parents=True, exist_ok=True)
    tables, summaries = {}, {}
    for item_class in args.classes:
        table, mismatches, us_data = build_class(args.cache, item_class, manifest, resolve_id)
        slug = item_class.lower().replace(" ", "_")
        summary = {"mismatches": len(mismatches)}
        if "currencies" in table:
            summary.update(currencies=len(table["currencies"]),
                           trade_ids=sum("trade_id" in c for c in table["currencies"].values()))
        elif "gems" in table:
            summary["gems"] = len(table["gems"])
            if pob_gems is not None:
                report = gem_pob_join(table["gems"], pob_gems)
                summary.update(pob_joined=report["joined"], missing_in_pob=len(report["missing_in_pob"]))
                if args.evidence:
                    _write(args.evidence / f"{slug}-pob-join.json", report)
        else:
            summary.update(mods=len(table["mods"]), socketables=len(table["socketables"]), base_types=len(table["base_types"]),
                           uniques=len(table["uniques"]),
                           page_entries=sum(len(v) for data in us_data for _, v in mod_sections(data)))
        if pob_mods is not None and us_data:
            tag_sets = [pob_bases[b["en"]] for b in table["base_types"].values() if b["en"] in pob_bases]
            if not tag_sets:
                tag_sets = [{(us_data[0].get("opt", {}).get("ItemClassesCode") or "").lower(), "default"}]
            report = pob_join(table["mods"], pob_mods, pob_ids_for_tags(args.pob, tag_sets))
            summary.update(pob_joined=report["joined"], pob_text_differs=len(report["text_differs"]),
                           missing_in_pob=len(report["missing_in_pob"]),
                           pob_only=len(report["missing_on_page"]))
            if args.evidence:
                _write(args.evidence / f"{slug}-pob-join.json", report)
        poecharm = args.cache / "poecharm" / "zh-rCN"
        if poecharm.is_dir():
            if "currencies" in table:
                check = {}
            elif "gems" in table:
                check = poecharm_check({}, table["gems"], {}, poecharm)
            else:
                check = poecharm_check(table["mods"], table["base_types"], table["uniques"], poecharm)
            summary["poecharm"] = {k: {"agree": v["agree"], "differ": len(v["differ"]), "absent": len(v["absent"])}
                                   for k, v in check.items()}
            if args.evidence:
                _write(args.evidence / f"{slug}-poecharm-check.json", check)
        table["metadata"]["summary"] = summary
        _write(args.out / f"{slug}.json", table)
        if args.evidence:
            _write(args.evidence / f"{slug}-mismatches.json", mismatches)
        tables[item_class] = table
        summaries[item_class] = summary
        print(item_class, json.dumps(summary, ensure_ascii=False))
    if len(args.classes) > 1:
        merged, conflicts = merge_mods(tables)
        _write(args.out / "mods.json", {
            "metadata": {"version": TABLE_VERSION, "site_version": manifest.get("site_version"),
                         "license": LICENSE_NOTE, "classes": [c for c in args.classes if tables[c].get("mods")],
                         "layout": "mod ID -> en/zh_hans/zh_hant templates ('#' per value), ranges, classes, essences; "
                                   "an essence 'line' is a pick-one display text shared by several IDs, "
                                   "not the mod's own text (mods seen only that way have no en); "
                                   "per-class files hold the same mods plus base types, uniques and socketables",
                         "conflicts": len(conflicts)},
            "mods": dict(sorted(merged.items()))})
        if args.evidence:
            _write(args.evidence / "mods-merge-conflicts.json", conflicts)
            _write(args.evidence / "summary.json", summaries)
        print("merged mods", len(merged), "conflicts", len(conflicts))
    return 0


def _write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
