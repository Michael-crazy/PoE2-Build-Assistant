#!/usr/bin/env python3
"""D02: Simplified Chinese gem tooltip table from PoE2DB gem pages, joined to PoB's gem stat lines.

  python3 -B scripts/pob_gem_tooltips.py --engine /tmp/poe2-pob-source --luajit <luajit> --lua-cpath '<cpath>' \
      [--cache <poe2db-cache>] [--terms data/terms/poe2db-1.0] [--localization data/terms/pob-localization] \
      [--out data/terms/pob-localization/gem_tooltips.json] [--report reports/gem-tooltips] \
      [--pob-lines /tmp/d02-pob-lines.json] [--build tests/fixtures/p02/real/build.xml]

1. PoB side: scripts/pob_gem_lines.lua on a clean copy of the pinned engine writes, per gem and granted
   effect, the English stat lines GemTooltip.lua shows (each statSet at the lowest level, level 20 and the
   highest level), the quality lines, the description and the statSet labels.
2. PoE2DB side: the us and cn gem pages (`/us|cn/<Gem>`, read through scripts/poe2db_fetch.py, offline
   unless --fetch). Each gem popup gives tags, header properties, description, the stat lines per section
   (hidden stats skipped) and the quality lines. us and cn lines pair by section and position.
3. Join: a gem's page is the D01 gem table entry whose `pob.gameId` is the PoB gem (else its name). A PoB
   line joins when a page line of that gem has the same number_key (P03, "(7—244)" ranges included) and
   every such page line gives the same Chinese template. Numbers become '#'; a written +/- sign stays;
   `order` lists the English value index per '#' when the Chinese reorders values.
4. Checks: coverage, unjoined lines, and a value check — the PoB lines of the gems in --build at their
   level, filled into the templates, against the numbers of the cn page's level table (0 differences
   expected).

Output (`gem_tooltips.json`, format poe2-gem-tooltips/1): see sources/pob-localization.md.
"""

import argparse
from collections import Counter, defaultdict
import html
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

import poe2db_fetch
from poe2db_terms import fold_name, number_key
from pob_localization import localize_line
from pob_worker import ROOT, prepare

FORMAT = "poe2-gem-tooltips/1"
GEM_TABLES = ("skill_gems", "support_gems", "spirit_gems", "meta_skill_gem", "lineage_supports")
# PoE2DB writes level ranges as "(7—244)"; PoB as "(7-244)" or a single value.
_PAGE_VALUE = re.compile(r"\([+-]?\d+(?:\.\d+)?[-—–][+-]?\d+(?:\.\d+)?\)|[+-]?\d+(?:\.\d+)?")
_LOCAL_VALUE = re.compile(r"\([+-]?\d+(?:\.\d+)?-[+-]?\d+(?:\.\d+)?\)|[+-]?\d+(?:\.\d+)?")
_POPUP = re.compile(r'<div class="newItemPopup GemPopup[^"]*"')
_LEAF = re.compile(r'<div class="(itemName(?: typeLine)?|property|hybridProperty|requirements|secDescrText|explicitMod|'
                   r'qualityMod|secondaryQualityMod|hybridHeader gemTabs|quality-text)">(.*?)</div>', re.S)
_TAG_LINK = re.compile(r'<a [^>]*?href="([^"]+)"[^>]*>([^<]*)</a>')


# --- text -------------------------------------------------------------------------------------------

def plain(markup):
    text = re.sub(r"<br\s*/?>", "\n", markup)
    text = html.unescape(re.sub(r"<[^>]+>", "", text))
    return "\n".join(re.sub(r"\s+", " ", line).strip() for line in text.split("\n")).strip()


def zh_template(zh_line):
    """PoE2DB zh line -> template with every number or range as '#', a written leading sign kept."""
    return _PAGE_VALUE.sub(lambda m: (m.group()[0] if m.group()[0] in "+-" else "") + "#", zh_line)


def _bare(value):
    return value.lstrip("+-").replace("—", "-").replace("–", "-")


def page_template(en_line, zh_line):
    """(zh template, order) when the zh line carries exactly the en line's values, else None.
    order[i] = index of the en value for the i-th '#' (None when the order is the same)."""
    en_values = [_bare(v) for v in _PAGE_VALUE.findall(en_line)]
    zh_values = [_bare(v) for v in _PAGE_VALUE.findall(zh_line)]
    if zh_values == en_values:
        return zh_template(zh_line), None
    if sorted(zh_values) == sorted(en_values) and len(set(en_values)) == len(en_values):
        return zh_template(zh_line), [en_values.index(v) for v in zh_values]
    return None


# --- PoE2DB pages -----------------------------------------------------------------------------------

def parse_popups(page):
    """Gem popups of a page, in order: name, type line, tags [(slug, text)], properties, requirements,
    description, sections [{'header', 'lines'}] and quality lines."""
    popups = []
    starts = [m.start() for m in _POPUP.finditer(page or "")]
    for start in starts:
        end = page.find('class="itemboximage"', start)
        segment = page[start:end if end > 0 else len(page)]
        popup = {"name": None, "type": None, "tags": [], "properties": [], "requirements": [],
                 "description": None, "sections": [{"header": None, "lines": []}], "quality": []}
        quality = False
        for kind, inner in _LEAF.findall(segment):
            if "secondary collapse" in inner:          # hidden stats ("Show hidden stats")
                continue
            text = plain(inner)
            if kind == "itemName":
                popup["name"] = popup["name"] or text
            elif kind == "itemName typeLine":
                popup["type"] = text
            elif kind == "property" and not popup["tags"] and not popup["properties"] and _TAG_LINK.search(inner) \
                    and ":" not in text:
                popup["tags"] = [(href.rsplit("/", 1)[-1], plain(name)) for href, name in _TAG_LINK.findall(inner)]
            elif kind in ("property", "hybridProperty"):
                popup["properties"].append(text)
            elif kind == "requirements":
                popup["requirements"].append(text)
            elif kind == "secDescrText":
                popup["description"] = text
            elif kind == "hybridHeader gemTabs":
                quality = False
                popup["sections"].append({"header": text, "lines": []})
            elif kind == "quality-text":
                quality = True
            elif kind in ("qualityMod", "secondaryQualityMod"):
                popup["quality"].append(text)
            elif kind == "explicitMod" and text:
                (popup["quality"] if quality else popup["sections"][-1]["lines"]).append(text)
        if not popup["sections"][0]["lines"] and len(popup["sections"]) > 1:
            popup["sections"].pop(0)
        popups.append(popup)
    return popups


def pair_popups(us, cn, simplified=lambda text: text):
    """(en, zh) pairs per kind for two parsed popups; parts whose sizes differ are left out and counted.
    A zh text that `simplified` changes (Traditional characters on a /cn/ page) is dropped and counted."""
    pairs = {"lines": [], "quality": [], "properties": [], "headers": [], "tags": [], "description": None}
    problems = []
    us_sections, cn_sections = us["sections"], cn["sections"]
    if len(us_sections) == len(cn_sections):
        for a, b in zip(us_sections, cn_sections):
            if len(a["lines"]) == len(b["lines"]):
                pairs["lines"] += list(zip(a["lines"], b["lines"]))
            else:
                problems.append(f"section {a['header']!r}: {len(a['lines'])} us lines, {len(b['lines'])} cn")
            if a["header"] and b["header"]:
                pairs["headers"].append((a["header"], b["header"]))
    else:
        problems.append(f"{len(us_sections)} us sections, {len(cn_sections)} cn")
    for kind in ("quality", "properties"):
        if len(us[kind]) == len(cn[kind]):
            pairs[kind] = list(zip(us[kind], cn[kind]))
        else:
            problems.append(f"{kind}: {len(us[kind])} us, {len(cn[kind])} cn")
    cn_tags = dict(cn["tags"])
    pairs["tags"] = [(text, cn_tags[slug]) for slug, text in us["tags"] if cn_tags.get(slug)]
    if us["description"] and cn["description"]:
        pairs["description"] = (us["description"], cn["description"])
    traditional = 0
    for kind in ("lines", "quality", "properties", "headers", "tags"):
        kept = [(en, zh) for en, zh in pairs[kind] if simplified(zh) == zh]
        traditional += len(pairs[kind]) - len(kept)
        pairs[kind] = kept
    if pairs["description"] and simplified(pairs["description"][1]) != pairs["description"][1]:
        pairs["description"] = None
        traditional += 1
    if traditional:
        problems.append(f"traditional: {traditional} cn texts with Traditional characters left out")
    return pairs, problems


def template_pool(pairs):
    """number_key -> set of (template, order) over (en, zh) line pairs (order as a tuple or None)."""
    pool = defaultdict(set)
    for en, zh in pairs:
        found = page_template(en, zh)
        if found:
            template, order = found
            pool[number_key(en)].add((template, tuple(order) if order else None))
    return pool


def join_line(line, pool):
    """{'key', 'zh_hans'[, 'order']} for a PoB line, or None (no page line, several translations, or the
    template's '#' count is not the line's value count)."""
    key = number_key(line)
    found = pool.get(key)
    if not found or len(found) != 1:
        return None
    template, order = next(iter(found))
    if template.count("#") != len(_LOCAL_VALUE.findall(line)):
        return None
    out = {"key": key, "zh_hans": template}
    if order:
        out["order"] = list(order)
    return out


def join_lines(pob_lines, en_lines, zh_lines):
    """PoB English lines -> zh templates against one block of page lines (en and zh in page order)."""
    if len(en_lines) != len(zh_lines):
        return [None] * len(pob_lines)
    pool = template_pool(zip(en_lines, zh_lines))
    return [join_line(line, pool) for line in pob_lines]


def label_pairs(pairs):
    """'Cost: (5.62—57.5) Mana per second' / '消耗: ...' -> (label, zh label), (value, zh value)."""
    labels, values = [], []
    for en, zh in pairs:
        en_match, zh_match = re.match(r"(.*?):(.*)", en), re.match(r"(.*?)[:：](.*)", zh)
        if not en_match or not zh_match:
            continue
        labels.append((en_match.group(1).strip(), zh_match.group(1).strip()))
        if re.search(r"\d", en_match.group(2)):
            values.append((en_match.group(2).strip(), zh_match.group(2).strip()))
    return labels, values


def level_table(page):
    """cn page level table: (header texts, rows of cell texts); the stat columns' headers are stat lines."""
    start = page.find('id="LevelEffect"') if page else -1
    if start < 0:
        start = (page or "").find("Level Effect")
    for match in re.finditer(r"<table[^>]*>(.*?)</table>", page[start:] if start >= 0 else "", re.S):
        head = re.search(r"<thead>(.*?)</thead>", match.group(1), re.S)
        if not head:
            continue
        headers = [plain(h) for h in re.findall(r"<th>(.*?)</th>", head.group(1), re.S)]
        if not headers or headers[0] not in ("等级", "Level"):
            continue
        rows = [[plain(c) for c in re.findall(r"<td>(.*?)</td>", row, re.S)]
                for row in re.findall(r"<tr>(.*?)</tr>", match.group(1).split("</thead>", 1)[-1], re.S)]
        return headers, rows
    return [], []


# --- PoB side ---------------------------------------------------------------------------------------

def dump_pob_lines(engine, luajit, lua_cpath, output):
    """Run scripts/pob_gem_lines.lua on a clean copy of the pinned engine; returns the parsed dump."""
    env = dict(os.environ, LUA_PATH="../runtime/lua/?.lua;../runtime/lua/?/init.lua;;", LUA_CPATH=lua_cpath)
    env.pop("CI", None)
    with tempfile.TemporaryDirectory(prefix="d02-engine-") as temporary:
        copy = Path(temporary)
        prepare(engine, copy)
        result = subprocess.run([str(Path(luajit).resolve(strict=True)), str(ROOT / "scripts/pob_gem_lines.lua"),
                                 str(Path(output).resolve())], cwd=copy / "src", env=env, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=900)
        if result.returncode:
            raise RuntimeError(result.stdout[-2000:])
    return json.loads(Path(output).read_text(encoding="utf-8"))


def effect_lines(effect):
    """All distinct English stat lines of an effect over its statSets and dumped levels, in order."""
    seen, out = set(), []
    for stat_set in effect.get("statSets") or []:
        by_level = stat_set.get("lines") or {}
        for level in sorted(by_level, key=int):
            for line in by_level[level] or []:
                if line not in seen:
                    seen.add(line)
                    out.append(line)
    return out


# --- build ------------------------------------------------------------------------------------------

def gem_pages(terms):
    """PoB gameId -> page slug and folded English name -> slug, from the D01 gem tables."""
    by_game_id, by_name = {}, {}
    for table in GEM_TABLES:
        path = Path(terms) / f"{table}.json"
        if not path.exists():
            continue
        for slug, gem in json.loads(path.read_text(encoding="utf-8")).get("gems", {}).items():
            game_id = (gem.get("pob") or {}).get("gameId")
            if game_id:
                by_game_id.setdefault(game_id, slug)
            by_name.setdefault(fold_name(gem["en"]), slug)
    return by_game_id, by_name


_CJK = re.compile(r"[㐀-鿿]")


def class_tags(terms):
    """(en, zh_hans) gem tag pairs from the D01 gem tables (PoE2DB's tag list of each gem)."""
    for table in GEM_TABLES:
        path = Path(terms) / f"{table}.json"
        if not path.exists():
            continue
        for gem in json.loads(path.read_text(encoding="utf-8")).get("gems", {}).values():
            for tag in gem.get("tags") or []:
                yield tag.get("en"), tag.get("zh_hans")


def _vote(table, en, zh):
    """Count one (en, zh) pair; a zh text without Chinese (left untranslated on the page) is not one."""
    if en and zh and _CJK.search(zh):
        table[en][zh] += 1


def _resolved(table):
    """en -> zh where every pair agrees (spacing aside: the most common spelling); the rest are conflicts."""
    names, conflicts = {}, {}
    for en, found in sorted(table.items()):
        if len({re.sub(r"\s+", "", zh) for zh in found}) == 1:
            names[en] = found.most_common(1)[0][0]
        else:
            conflicts[en] = dict(found)
    return names, conflicts


def build(pob_gems, terms, fetcher, simplified=lambda text: text):
    by_game_id, by_name = gem_pages(terms)
    effects, report = {}, {"gems": len(pob_gems), "gems_with_page": 0, "pages_without_popup": [],
                           "pairing_problems": {}, "no_page": [], "unjoined": {}, "description_differs": []}
    tags, labels, values, headers = (defaultdict(Counter) for _ in range(4))
    totals = Counter()
    for gem_id, gem in sorted(pob_gems.items()):
        slug = by_game_id.get(gem.get("gameId")) or by_game_id.get(gem_id) or by_name.get(fold_name(gem.get("name") or ""))
        us = cn = None
        if slug:
            us, cn = fetcher.page("us", slug), fetcher.page("cn", slug)
        if not us or not cn:
            report["no_page"].append(gem.get("name") or gem_id)
            continue
        us_popups, cn_popups = parse_popups(us), parse_popups(cn)
        if not us_popups or len(us_popups) != len(cn_popups):
            report["pages_without_popup"].append(slug)
            continue
        report["gems_with_page"] += 1
        line_pairs, quality_pairs, description = [], [], None
        for index, (a, b) in enumerate(zip(us_popups, cn_popups)):
            pairs, problems = pair_popups(a, b, simplified)
            if problems:
                report["pairing_problems"][f"{slug}#{index}"] = problems
            line_pairs += pairs["lines"]
            quality_pairs += pairs["quality"]
            description = description or pairs["description"]
            for en, zh in pairs["tags"]:
                _vote(tags, en, zh)
            found_labels, found_values = label_pairs(pairs["properties"])
            for en, zh in found_labels:
                _vote(labels, en, zh)
            for en, zh in found_values:
                found = page_template(en, zh)
                if found and not found[1]:
                    _vote(values, number_key(en), found[0])
            for en, zh in pairs["headers"]:
                _vote(headers, en, zh)
            if a["type"] and b["type"] and simplified(b["type"]) == b["type"]:
                _vote(tags, a["type"], b["type"])
        lines_pool, quality_pool = template_pool(line_pairs), template_pool(quality_pairs)
        for number, effect in enumerate(gem.get("effects") or []):
            entry = {"gem": gem_id, "page": slug, "lines": {}, "quality": {}}
            for line in effect_lines(effect):
                joined = join_line(line, lines_pool)
                totals["lines"] += 1
                if joined:
                    totals["lines_joined"] += 1
                    entry["lines"][joined.pop("key")] = joined
                else:
                    report["unjoined"].setdefault(effect["id"], []).append(line)
            for line in effect.get("quality") or []:
                joined = join_line(line, quality_pool)
                totals["quality"] += 1
                if joined:
                    totals["quality_joined"] += 1
                    entry["quality"][joined.pop("key")] = joined
                else:
                    report["unjoined"].setdefault(effect["id"], []).append("[quality] " + line)
            if number == 0 and description:
                entry["description"] = {"en": description[0], "zh_hans": description[1]}
                totals["descriptions"] += 1
                if plain(effect.get("description") or "") != description[0]:
                    report["description_differs"].append(effect["id"])
            totals["effects"] += 1
            if effect["id"] in effects:          # the same granted effect on two gems: keep agreeing lines
                old = effects[effect["id"]]
                for kind in ("lines", "quality"):
                    for key in list(old[kind]):
                        if key in entry[kind] and entry[kind][key] != old[kind][key]:
                            del old[kind][key]
                continue
            entry["lines"], entry["quality"] = dict(sorted(entry["lines"].items())), dict(sorted(entry["quality"].items()))
            effects[effect["id"]] = entry
    # The popups link only some tags; the common ones (Lightning, AoE, Duration ...) come from the gem tables.
    for en, zh in class_tags(terms):
        _vote(tags, en, zh)
    tags, tag_conflicts = _resolved(tags)
    labels, label_conflicts = _resolved(labels)
    values, value_conflicts = _resolved(values)
    headers, header_conflicts = _resolved(headers)
    report["conflicts"] = {"tags": tag_conflicts, "labels": label_conflicts, "values": value_conflicts,
                           "statset_labels": header_conflicts}
    report["totals"] = dict(totals)
    table = {"format": FORMAT, "languages": ["zh_hans"], "effects": dict(sorted(effects.items())),
             "tags": tags, "labels": labels, "values": {k: {"zh_hans": v} for k, v in values.items()},
             "statset_labels": headers}
    return table, report


# --- value check ------------------------------------------------------------------------------------

def build_gems(build_xml):
    """[(gemId, skillId, level)] of the enabled gems of a PoB build."""
    text = Path(build_xml).read_text(encoding="utf-8")
    out = []
    for attrs in re.findall(r"<Gem ([^>]*)/?>", text):
        fields = dict(re.findall(r'(\w+)="([^"]*)"', attrs))
        if fields.get("enabled", "true") == "true":
            out.append((fields.get("gemId"), fields.get("skillId"), int(fields.get("level", "1"))))
    return out


def compare_numbers(ours, page):
    """'same' when the page's level-table values are the shown values (or, as the table lists only the
    values that change with level, appear among them in order); 'rounding' when they differ only in the
    last shown digit; else 'value'."""
    if ours == page:
        return "same"
    short, long = (page, ours) if len(page) < len(ours) else (ours, page)
    it = iter(long)
    if short and len(short) < len(long) and all(any(v == o for o in it) for v in short):
        return "same"
    if len(ours) == len(page) and all(abs(a - b) <= max(0.1, 0.006 * abs(b)) for a, b in zip(ours, page)):
        return "rounding"
    return "value"


def all_effects(pob_gems, levels=(1, 20)):
    """[(gemId, effect id, level)] for every effect at the given levels (the wider, informative check)."""
    return [(gem_id, effect["id"], level) for gem_id, gem in sorted(pob_gems.items())
            for effect in gem.get("effects") or [] for level in levels
            if any(str(level) in (s.get("lines") or {}) for s in effect.get("statSets") or [])]


def check_values(gems, pob_gems, table, fetcher):
    """Fill the zh templates with PoB's values at each (gemId, skillId, level) and compare every number with
    the cn level table row of that level (columns whose header line has the same template)."""
    by_effect = {e["id"]: (gem_id, e) for gem_id, gem in pob_gems.items() for e in gem.get("effects") or []}
    result = {"gems": [], "compared_values": 0, "differences": []}
    for gem_id, skill_id, level in gems:
        found = by_effect.get(skill_id)
        entry = table["effects"].get(skill_id)
        if not found or not entry:
            result["gems"].append({"gemId": gem_id, "skillId": skill_id, "level": level, "status": "no table entry"})
            continue
        _, effect = found
        headers, rows = level_table(fetcher.page("cn", entry["page"]) or "")
        row = next((r for r in rows if r and r[0] == str(level)), None)
        columns = defaultdict(list)
        for i, header in enumerate(headers):
            columns[re.sub(r"\s+", "", zh_template(header))].append(i)
        compared = 0
        for stat_set in effect.get("statSets") or []:
            for line in (stat_set.get("lines") or {}).get(str(level)) or []:
                joined = entry["lines"].get(number_key(line))
                if not joined or row is None:
                    continue
                cells = [row[i] for i in columns.get(re.sub(r"\s+", "", joined["zh_hans"]), []) if i < len(row)]
                if not cells:
                    continue
                shown = localize_line(line, joined["zh_hans"], joined.get("order"))
                ours = [float(_bare(v)) for v in _LOCAL_VALUE.findall(shown)]
                kinds = []
                for cell in cells:     # several stat sets can share a column template: any one may match
                    page = [float(v.strip().lstrip("+")) for v in cell.split(",") if v.strip()]
                    kinds.append(compare_numbers(ours, page))
                compared += len(ours)
                kind = "same" if "same" in kinds else "rounding" if "rounding" in kinds else "value"
                if kind != "same":
                    result["differences"].append({"skillId": skill_id, "level": level, "kind": kind, "line": line,
                                                  "shown": shown, "page": cells})
        result["compared_values"] += compared
        result["gems"].append({"gemId": gem_id, "skillId": skill_id, "level": level, "values_compared": compared})
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--luajit", type=Path)
    parser.add_argument("--lua-cpath", default="")
    parser.add_argument("--pob-lines", type=Path, help="PoB English line dump: reused when it exists and "
                                                       "--luajit is not given, else (re)written")
    parser.add_argument("--cache", type=Path, default=poe2db_fetch.DEFAULT_CACHE)
    parser.add_argument("--fetch", action="store_true", help="fetch gem pages missing from the cache (4 s apart)")
    parser.add_argument("--terms", type=Path, default=ROOT / "data/terms/poe2db-1.0")
    parser.add_argument("--localization", type=Path, default=ROOT / "data/terms/pob-localization")
    parser.add_argument("--out", type=Path, default=ROOT / "data/terms/pob-localization/gem_tooltips.json")
    parser.add_argument("--report", type=Path, help="folder for coverage.json, unjoined.json, value-check.json")
    parser.add_argument("--build", type=Path, default=ROOT / "tests/fixtures/p02/real/build.xml")
    args = parser.parse_args(argv)
    if args.luajit:
        output = args.pob_lines or Path(tempfile.mkdtemp(prefix="d02-")) / "pob-lines.json"
        pob_gems = dump_pob_lines(args.engine, args.luajit, args.lua_cpath, output)
    elif args.pob_lines and args.pob_lines.exists():
        pob_gems = json.loads(args.pob_lines.read_text(encoding="utf-8"))
    else:
        parser.error("give --luajit (to dump PoB's lines) or an existing --pob-lines")
    fetcher = poe2db_fetch.Fetcher(args.cache, offline=not args.fetch)
    import opencc  # generation only (pip install opencc-python-reimplemented): spot Traditional text on /cn/
    t2s = opencc.OpenCC("t2s").convert
    table, report = build(pob_gems, args.terms, fetcher, t2s)
    pob_commit = json.loads((ROOT / "sources/pob.json").read_text(encoding="utf-8"))["commit"]
    table = {"format": FORMAT, "pob_commit": pob_commit, "terms_version": "poe2db-1.0",
             **{k: v for k, v in table.items() if k != "format"}}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(table, ensure_ascii=False, indent=1, sort_keys=False) + "\n", encoding="utf-8")
    check = check_values(build_gems(args.build), pob_gems, table, fetcher)         if args.build and args.build.exists() else None
    wide = check_values(all_effects(pob_gems), pob_gems, table, fetcher)
    totals = report["totals"]
    coverage = {"gems": report["gems"], "gems_with_page": report["gems_with_page"],
                "effects": totals.get("effects", 0), "effects_in_table": len(table["effects"]),
                "lines": totals.get("lines", 0), "lines_joined": totals.get("lines_joined", 0),
                "quality": totals.get("quality", 0), "quality_joined": totals.get("quality_joined", 0),
                "descriptions": totals.get("descriptions", 0),
                "description_differs_from_pob": len(report["description_differs"]),
                "no_page": len(report["no_page"]), "pages_without_popup": len(report["pages_without_popup"]),
                "pairing_problems": len(report["pairing_problems"]),
                "tags": len(table["tags"]), "labels": len(table["labels"]), "values": len(table["values"]),
                "statset_labels": len(table["statset_labels"]),
                "value_check": None if check is None else {"compared_values": check["compared_values"],
                                                           "differences": len(check["differences"])},
                "value_check_all_gems_level_1_20": {"compared_values": wide["compared_values"], **Counter(
                    d["kind"] for d in wide["differences"])}}
    if args.report:
        args.report.mkdir(parents=True, exist_ok=True)
        (args.report / "coverage.json").write_text(json.dumps(coverage, ensure_ascii=False, indent=1) + "\n",
                                                   encoding="utf-8")
        (args.report / "unjoined.json").write_text(json.dumps(
            {k: report[k] for k in ("no_page", "pages_without_popup", "pairing_problems", "unjoined",
                                    "description_differs", "conflicts")}, ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8")
        (args.report / "value-check-all.json").write_text(json.dumps(
            {"compared_values": wide["compared_values"], "differences": wide["differences"]},
            ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        if check is not None:
            (args.report / "value-check.json").write_text(json.dumps(check, ensure_ascii=False, indent=1) + "\n",
                                                          encoding="utf-8")
    print(json.dumps(coverage, ensure_ascii=False))
    return 1 if check and check["differences"] else 0


if __name__ == "__main__":
    sys.exit(main())
