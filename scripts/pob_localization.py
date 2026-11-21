#!/usr/bin/env python3
"""Build ID-keyed zh_hans/zh_hant display tables for PoB from the PoE2DB terms (D01).

Gems by PoB gem key (Gems.lua) and grantedEffectId, item mods by PoB mod ID with line
templates, bases and uniques by English name. Unmatched PoB entries stay English: they are
only counted in the coverage report, never translated here.

python3 -B scripts/pob_localization.py --terms data/terms/poe2db-1.0 --pob /tmp/poe2-pob-source \
    --out data/terms/pob-localization
"""
import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from index_pob_classes import parse_classes, parse_versions, table_at
from poe2db_terms import fold_name, load_pob_gems, number_key

FORMAT = "poe2-pob-localization/1"
LANGS = ("zh_hans", "zh_hant")
GEM_TABLES = ("skill_gems", "support_gems", "spirit_gems", "meta_skill_gem", "lineage_supports")
MOD_FILES = ("ModItem", "ModJewel", "ModCorrupted", "ModFlask", "ModCharm", "ModIncursionLimb",
             "ModVeiled", "ModItemExclusive")

_MOD_LINE = re.compile(r'^\t\["([^"]+)"\] = \{ (.*?)statOrder', re.M)
_FIELD = re.compile(r'\b\w+ = "(?:[^"\\]|\\.)*",?')
_LUA_STR = re.compile(r'"((?:[^"\\]|\\.)*)"')


# --- PoB side ---------------------------------------------------------------

def load_pob_gem_keys(pob_root):
    """PoB gem key (as used in Gems.lua / saved builds' gemId) -> string fields."""
    text = (Path(pob_root) / "src" / "Data" / "Gems.lua").read_text(encoding="utf-8")
    keys = re.findall(r'\n\t\["([^"]+)"\] = \{', text)
    return dict(zip(keys, load_pob_gems(pob_root)))


def load_pob_mod_lines(pob_root):
    """{file: {mod ID: [English lines]}} for the item mod files PoB loads into data.itemMods."""
    out = {}
    for name in MOD_FILES:
        text = (Path(pob_root) / "src" / "Data" / f"{name}.lua").read_text(encoding="utf-8")
        out[name] = {m.group(1): [s.replace('\\"', '"') for s in _LUA_STR.findall(_FIELD.sub("", m.group(2)))]
                     for m in _MOD_LINE.finditer(text)}
    return out


def load_pob_base_names(pob_root):
    names = set()
    for path in sorted((Path(pob_root) / "src" / "Data" / "Bases").glob("*.lua")):
        names.update(re.findall(r'itemBases\["((?:[^"\\]|\\.)*)"\]', path.read_text(encoding="utf-8")))
    return {n.replace('\\"', '"') for n in names}


def load_pob_unique_names(pob_root):
    """Unique names: first line of each [[...]] block in src/Data/Uniques/*.lua (not Special/)."""
    names = set()
    for path in sorted((Path(pob_root) / "src" / "Data" / "Uniques").glob("*.lua")):
        for block in re.findall(r"\[\[\n(.*?)\]\]", path.read_text(encoding="utf-8"), re.S):
            names.add(block.strip().splitlines()[0].strip())
    return names


# --- PoE2DB side ------------------------------------------------------------

def load_terms(terms_dir):
    terms_dir = Path(terms_dir)
    tables = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(terms_dir.glob("*.json"))}
    return tables


def _names(entry):
    return {lang: entry[lang] for lang in LANGS if entry.get(lang)}


def _collect(by_key, key, value):
    if value not in by_key[key]:
        by_key[key].append(value)


def _resolve(by_key):
    """Keys with exactly one distinct translation are matched; the rest are ambiguous."""
    matched, ambiguous = {}, {}
    for key, values in sorted(by_key.items()):
        if len(values) == 1:
            matched[key] = values[0]
        else:
            ambiguous[key] = values
    return matched, ambiguous


# --- builders ---------------------------------------------------------------

def build_gems(tables, pob_gems):
    """Join on the D01 'pob' field (gameId), falling back to name / folded name."""
    by_game_id = {fields.get("gameId"): key for key, fields in pob_gems.items()}
    by_name = {}
    for key, fields in pob_gems.items():
        for name in (fields.get("name"), fields.get("baseTypeName")):
            if name:
                by_name.setdefault(fold_name(name), set()).add(key)
    found = defaultdict(list)
    poe2db_only = []
    for table in GEM_TABLES:
        for slug, gem in tables.get(table, {}).get("gems", {}).items():
            key = by_game_id.get(gem.get("pob", {}).get("gameId"))
            if key is None:
                keys = by_name.get(fold_name(gem["en"]), set())
                key = next(iter(keys)) if len(keys) == 1 else None
            if key is None:
                poe2db_only.append(gem["en"])
                continue
            _collect(found, key, _names(gem))
    matched, ambiguous = _resolve(found)
    gems = {key: {"en": pob_gems[key].get("name"), "grantedEffectId": pob_gems[key].get("grantedEffectId"), **names}
            for key, names in matched.items()}
    skills = defaultdict(list)
    for entry in gems.values():
        if entry["grantedEffectId"]:
            _collect(skills, entry["grantedEffectId"], {k: entry[k] for k in ("en",) + LANGS if k in entry})
    skills, skill_ambiguous = _resolve(skills)
    missing = sorted(set(pob_gems) - set(gems) - set(ambiguous))
    internal = [k for k in missing if "Ascendancy" in k or "PlayerDefault" in k]
    report = {"pob_total": len(pob_gems), "matched": len(gems), "missing": len(missing),
              "missing_ascendancy_or_default": len(internal),
              "ambiguous": len(ambiguous), "poe2db_only": len(poe2db_only),
              "skills_by_granted_effect": len(skills), "skills_ambiguous": len(skill_ambiguous),
              "missing_ids": missing, "ambiguous_ids": ambiguous, "poe2db_only_names": sorted(poe2db_only)}
    return {"gems": gems, "skills": skills}, report


def _line_template(pob_line, mod, index):
    """One PoB English line -> its zh templates, when PoE2DB has the same numeric template."""
    en = mod.get("en") or []
    if index >= len(en) or number_key(en[index]) != number_key(pob_line):
        return None
    out = {"key": number_key(pob_line)}
    for lang in LANGS:
        zh = mod.get(lang) or []
        if len(zh) != len(en) or zh[index].count("#") != en[index].count("#"):
            return None
        out[lang] = zh[index]
    return out


def build_mods(mods, pob_mods):
    """mods: merged PoE2DB mods.json 'mods'. pob_mods: {file: {id: lines}}."""
    table, report = {}, {"by_file": {}}
    for name, entries in pob_mods.items():
        stats = {"pob_total": len(entries), "matched": 0, "missing": 0, "ambiguous": 0}
        for ident, lines in entries.items():
            mod = mods.get(ident)
            if mod is None:
                stats["missing"] += 1
                continue
            templates = [_line_template(line, mod, i) for i, line in enumerate(lines)]
            if not lines or None in templates:
                stats["ambiguous"] += 1
                report.setdefault("ambiguous_ids", {})[ident] = {"pob": lines, "poe2db": mod.get("en")}
                continue
            stats["matched"] += 1
            table[ident] = {"file": name, "lines": templates}
            affix = mod.get("affix") or {}
            if affix.get("en"):
                table[ident]["affix"] = affix
        report["by_file"][name] = stats
    all_pob = set().union(*(set(e) for e in pob_mods.values()))
    # IDs can repeat across files; the totals count each ID once.
    report["pob_total"] = len(all_pob)
    report["matched"] = len(table)
    report["missing"] = len(all_pob - set(mods))
    report["ambiguous"] = len(set(report.get("ambiguous_ids", {})) - set(table))
    report["poe2db_only"] = len(set(mods) - all_pob)
    return table, report


_VALUE = re.compile(r"\([+-]?\d+(?:\.\d+)?-[+-]?\d+(?:\.\d+)?\)|[+-]?\d+(?:\.\d+)?")


def localize_line(line, template, order=None):
    """Reference for the display layer: put the values of a PoB English line into a zh template.

    A sign written in the template stays unless the English value carries the other sign (then the
    English sign replaces it); without one a negative value keeps its minus. order (passive lines)
    lists the English value index for each '#' when the zh text reorders them."""
    values = _VALUE.findall(line)
    if len(values) != template.count("#"):
        return line
    if order:
        values = [values[i] for i in order]
    parts = template.split("#")
    out = [parts[0]]
    for value, rest in zip(values, parts[1:]):
        if not value.startswith("("):
            if out[-1][-1:] in ("+", "-"):
                if value[:1] in ("+", "-") and value[:1] != out[-1][-1:]:
                    out[-1] = out[-1][:-1] + value[:1]
                value = value.lstrip("+-")
            else:
                value = value.lstrip("+")
        out += [value, rest]
    return "".join(out)


def _by_name(tables, section, pob_names):
    found = defaultdict(list)
    for data in tables.values():
        for entry in (data.get(section) or {}).values():
            if entry.get("en") in pob_names:
                _collect(found, entry["en"], _names(entry))
    matched, ambiguous = _resolve(found)
    poe2db_names = {e.get("en") for d in tables.values() for e in (d.get(section) or {}).values()}
    missing = sorted(pob_names - set(matched) - set(ambiguous))
    report = {"pob_total": len(pob_names), "matched": len(matched), "missing": len(missing),
              "ambiguous": len(ambiguous), "poe2db_only": len(poe2db_names - pob_names),
              "missing_names": missing, "ambiguous_names": ambiguous}
    return matched, report


def build_uniques(tables, pob_names):
    """Names plus per-unique line templates (PoB unique lines carry no mod ID)."""
    names, report = _by_name(tables, "uniques", pob_names)
    lines = defaultdict(dict)
    for data in tables.values():
        for entry in (data.get("uniques") or {}).values():
            if entry.get("en") not in names:
                continue
            for line in entry.get("implicits", []) + entry.get("explicits", []):
                if all(line.get(lang) for lang in LANGS):
                    lines[entry["en"]].setdefault(number_key(line["en"]), {lang: line[lang] for lang in LANGS})
    table = {name: {**zh, "lines": lines.get(name, {})} for name, zh in names.items()}
    return table, report


def build_line_index(mods):
    """Template key -> zh lines, for mod lines PoB shows without a mod ID (pasted or imported items)."""
    found = defaultdict(list)
    for mod in mods.values():
        for line in mod["lines"]:
            _collect(found, line["key"], {lang: line[lang] for lang in LANGS})
    return _resolve(found)


# --- passive tree -------------------------------------------------------------

_MARKUP = re.compile(r"\[(?:[^\]|]*\|)?([^\]]*)\]")
POE2DB_TREE_URL = "https://poe2db.tw/data/passive-skill-tree/4.5/data_{us,cn,tw}.json"
TREE_KINDS = ("ascendancy", "keystone", "notable", "jewel_socket", "small", "mastery", "class_start")


def pob_tree_version(pob_root):
    """latestTreeVersion: the tree PoB uses for new builds."""
    return parse_versions((Path(pob_root) / "src" / "GameVersions.lua").read_text(encoding="utf-8"))[-1]["tree_version"]


def load_pob_tree(pob_root, version):
    """PoB tree.lua (the file PassiveTree.lua loads): {skill id: node fields}, {ascendancy internalId: name}."""
    path = Path(pob_root) / "src" / "TreeData" / version / "tree.lua"
    text = path.read_text(encoding="utf-8")
    start = re.search(r"^\tnodes=(\{)", text, re.M).start(1)
    nodes = {}
    for key, node in table_at(text, start, path, escaped_strings=True)["fields"].items():
        fields = {k: v["fields"] if isinstance(v, dict) else v for k, v in node["fields"].items()}
        fields["stats"] = [fields["stats"][i] for i in sorted(fields.get("stats") or {})]
        nodes[str(key)] = fields
    ascendancies = {asc["internal_id"]: asc["name_en"] for cls in parse_classes(text, path) for asc in cls["ascendancies"]}
    return nodes, ascendancies


def load_pob_classes(pob_root, version):
    """PoB tree.lua classes: {class name: [ascendancy internalIds]} (the class dropdown shows these names)."""
    path = Path(pob_root) / "src" / "TreeData" / version / "tree.lua"
    return {cls["name_en"]: [asc["internal_id"] for asc in cls["ascendancies"]]
            for cls in parse_classes(path.read_text(encoding="utf-8"), path)}


def build_classes(pob_classes, db):
    """Class names: a PoB class joins the PoE2DB tree class with the same English name whose ascendancy
    ids include the PoB class's ascendancy ids; the localized names come from the class with those ids."""
    def find(data, asc_ids):
        for cls in data["classes"]:
            ids = {a["id"] for a in cls["ascendancies"]}
            if asc_ids and set(asc_ids) <= ids:
                return cls
    table, unjoined = {}, []
    for name, asc_ids in sorted(pob_classes.items()):
        found = {lang: find(data, asc_ids) for lang, data in db.items()}
        if None in found.values() or _plain(found["en"]["name"]) != name:
            unjoined.append(name)
            continue
        table[name] = {lang: _plain(found[lang]["name"]) for lang in LANGS}
    return table, {"pob_total": len(pob_classes), "matched": len(table), "unjoined": unjoined}


def load_poe2db_tree(tree_dir):
    """PoE2DB passive tree data (/data/passive-skill-tree/<ver>/data_<lang>.json) for us/cn/tw."""
    return {lang: json.loads((Path(tree_dir) / f"data_{code}.json").read_text(encoding="utf-8"))
            for lang, code in (("en", "us"), ("zh_hans", "cn"), ("zh_hant", "tw"))}


def tree_node_kind(node):
    if node.get("ascendancyName"):
        return "ascendancy"
    for flag, kind in (("isKeystone", "keystone"), ("isJewelSocket", "jewel_socket"), ("isNotable", "notable"),
                       ("isOnlyImage", "mastery"), ("classesStart", "class_start")):
        if node.get(flag):
            return kind
    return "small"


def _plain(text):
    return _MARKUP.sub(r"\1", text)


def _stat_lines(node):
    return [line for stat in node.get("stats", []) for line in _plain(stat).split("\n")]


def _zh_template(en_line, zh_line):
    """(zh template, order) or None. The zh line's numbers become '#' when they are the en line's
    numbers; order[i] is the en value index for the i-th '#' when the zh line reorders distinct
    values (None = same order)."""
    en_values = [v.lstrip("+-") for v in _VALUE.findall(en_line)]
    zh_values = [v.lstrip("+-") for v in _VALUE.findall(zh_line)]
    if zh_values == en_values:
        return _VALUE.sub("#", zh_line), None
    if sorted(zh_values) == sorted(en_values) and len(set(en_values)) == len(en_values):
        return _VALUE.sub("#", zh_line), [en_values.index(v) for v in zh_values]
    return _zh_template_words(en_line, zh_line)


_NUMBER_WORDS = {"a": "1", "an": "1", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
                 "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10", "zero": "0"}
_BULLET = re.compile(r"^\s*\u2022\s*")


def _unbullet(line):
    return _BULLET.sub("", line)


def loose_key(line):
    """Fallback key inside one node: PoE2DB writes '1 additional Projectiles' and '• 1 Helmet socket'
    where PoB writes 'an additional Projectile' and '1 Helmet socket'. Bullets go, number words
    become digits and a plural 's' is dropped from every word."""
    words = _unbullet(line).split(" ")
    words = [_NUMBER_WORDS.get(w.lower(), w) for w in words]
    return " ".join(w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w
                    for w in number_key(" ".join(words)).split(" "))


def _loose_template(pob_line, en_line, zh_line):
    """zh template for a PoB line joined by loose_key. A PoB line without digits (its numbers are
    words) gets the PoE2DB zh line as it is, once its numbers are checked against the en line."""
    en_line, zh_line = _unbullet(en_line), _unbullet(zh_line)
    zh = _zh_template(en_line, zh_line)
    if zh is None:
        return None
    if not _VALUE.findall(pob_line):
        words = " ".join(_NUMBER_WORDS.get(w.lower(), w) for w in pob_line.split(" "))
        en_values = [v.lstrip("+-") for v in _VALUE.findall(en_line)]
        if [v.lstrip("+-") for v in _VALUE.findall(words)] != en_values:
            return None
        return zh_line, None
    if len(_VALUE.findall(pob_line)) != len(_VALUE.findall(en_line)):
        return None
    return zh


def _word_values(en_line, articles):
    """[(value, fixed)] of an English line in order; number words ('eight', and 'a'/'an' when
    `articles`) are fixed values: PoB writes no digit for them, so the template keeps them literal."""
    words = [w for w in _NUMBER_WORDS if articles or w not in ("a", "an")]
    pattern = re.compile(_VALUE.pattern + r"|\b(" + "|".join(words) + r")\b", re.I)
    return [(_NUMBER_WORDS[m.group(1).lower()], True) if m.group(1) else (m.group(0).lstrip("+-"), False)
            for m in pattern.finditer(en_line)]


def _zh_template_words(en_line, zh_line):
    """_zh_template for an en line that writes some numbers as words (none if it writes none)."""
    zh_values = [v.lstrip("+-") for v in _VALUE.findall(zh_line)]
    for articles in (False, True):
        en = _word_values(en_line, articles)
        if not any(fixed for _, fixed in en) or sorted(zh_values) != sorted(v for v, _ in en):
            continue
        if [v for v, _ in en] != zh_values and len({v for v, _ in en}) != len(en):
            continue
        free = [i for i, (_, fixed) in enumerate(en) if not fixed]
        taken, order, parts = set(), [], []
        last = 0
        for m in _VALUE.finditer(zh_line):
            k = next(i for i, (v, _) in enumerate(en) if v == m.group(0).lstrip("+-") and i not in taken)
            taken.add(k)
            parts.append(zh_line[last:m.start()])
            if en[k][1]:
                parts.append(m.group(0))
            else:
                parts.append("#")
                order.append(free.index(k))
            last = m.end()
        parts.append(zh_line[last:])
        return "".join(parts), (None if order == sorted(order) else order)
    return None


def _join_node(name, pob_lines, found):
    """({en, zh names when the English names agree, lines}, problems) for one PoB node or option
    against its PoE2DB node in every language (found = {lang: node})."""
    problems = set()
    entry = {"en": name}
    if _plain(found["en"]["name"]) == name:
        entry.update({lang: _plain(found[lang]["name"]) for lang in LANGS})
    else:
        problems.add("name_differs")
    lines = {lang: _stat_lines(found[lang]) for lang in found}
    templates = [None] * len(pob_lines)
    if len({len(v) for v in lines.values()}) != 1:
        problems.add("zh_line_count_differs")
    else:
        index, loose = defaultdict(list), defaultdict(list)
        for i, line in enumerate(lines["en"]):
            index[number_key(line)].append(i)
            loose[loose_key(line)].append(i)
        for n, line in enumerate(pob_lines):
            hits = index.get(number_key(line), [])
            if len(hits) == 1:
                zh = {lang: _zh_template(lines["en"][hits[0]], lines[lang][hits[0]]) for lang in LANGS}
            else:
                hits = [] if hits else loose.get(loose_key(line), [])
                if len(hits) != 1:
                    problems.add("stat_lines_differ")
                    continue
                zh = {lang: _loose_template(line, lines["en"][hits[0]], lines[lang][hits[0]]) for lang in LANGS}
            if None in zh.values():
                problems.add("zh_numbers_differ")
                zh = {lang: t for lang, t in zh.items() if t is not None}
                if not zh:
                    continue
            templates[n] = {"key": number_key(line), **{lang: t for lang, (t, _) in zh.items()}}
            order = {lang: o for lang, (_, o) in zh.items() if o}
            if order:
                templates[n]["order"] = order
        _whole_stats(pob_lines, templates)
    entry["lines"] = templates
    return entry, problems


def _whole_stats(pob_lines, templates):
    """A stat wrapped over several lines (continuations start lowercase) is used whole or not at all."""
    start = 0
    for n in range(1, len(pob_lines) + 1):
        if n == len(pob_lines) or not pob_lines[n][:1].islower():
            if None in templates[start:n]:
                templates[start:n] = [None] * (n - start)
            else:
                # A language missing on one line of the stat is dropped from the whole stat.
                missing = {lang for t in templates[start:n] for lang in LANGS if lang not in t}
                for i in range(start, n):
                    for lang in missing:
                        templates[i].pop(lang, None)
                        if templates[i].get("order"):
                            templates[i]["order"].pop(lang, None)
                    if not any(lang in templates[i] for lang in LANGS):
                        templates[i] = None
            start = n


def _unwrap(value):
    return {k: _unwrap(v) for k, v in value["fields"].items()} if isinstance(value, dict) and "fields" in value else value


def build_node_options(pob_nodes, db):
    """Switchable node alternatives (PoB node.options: attribute choices keyed 1..n, class/ascendancy
    variants keyed by name). Their ids are not PoE2DB node ids, so the name comes from the PoE2DB
    nodes with the same English name and each stat line from PoE2DB tree lines with the same
    number_key; either is used only when every PoE2DB occurrence gives the same zh text."""
    db_nodes = {lang: data["nodes"] for lang, data in db.items()}
    names, line_index = defaultdict(set), defaultdict(set)
    for ident, node in db_nodes["en"].items():
        found = {lang: nodes.get(ident) for lang, nodes in db_nodes.items()}
        if "name" not in node or None in found.values():
            continue
        names[_plain(node["name"])].add(tuple(_plain(found[lang]["name"]) for lang in LANGS))
        lines = {lang: _stat_lines(found[lang]) for lang in found}
        if len({len(v) for v in lines.values()}) != 1:
            continue
        for i, line in enumerate(lines["en"]):
            zh = {lang: _zh_template(line, lines[lang][i]) for lang in LANGS}
            if None in zh.values():
                continue
            template = {"key": number_key(line), **{lang: t for lang, (t, _) in zh.items()}}
            order = {lang: o for lang, (_, o) in zh.items() if o}
            if order:
                template["order"] = order
            line_index[template["key"]].add(json.dumps(template, ensure_ascii=False, sort_keys=True))
    hosts, options = {}, {}
    overlay_only = 0
    for host, node in sorted(pob_nodes.items(), key=lambda kv: int(kv[0])):
        if not node.get("options"):
            continue
        hosts[host] = {}
        for key, option in node["options"].items():
            option = _unwrap(option)
            if "id" not in option:  # frame overlay only: the host node's own text is shown
                overlay_only += 1
                continue
            hosts[host][str(key)] = str(option["id"])
            options.setdefault(str(option["id"]), option)
    table, unjoined = {}, {}
    lines_total = lines_matched = names_matched = 0
    for ident, option in sorted(options.items(), key=lambda kv: int(kv[0])):
        pob_lines = [line for i in sorted(option.get("stats") or {}) for line in option["stats"][i].split("\n")]
        entry = {"en": option["name"]}
        problems = []
        zh_names = names.get(option["name"], set())
        if len(zh_names) == 1:
            entry.update(zip(LANGS, next(iter(zh_names))))
            names_matched += 1
        else:
            problems.append("name_ambiguous" if zh_names else "name_not_in_poe2db")
        templates = []
        for line in pob_lines:
            hits = line_index.get(number_key(line), set())
            templates.append(json.loads(next(iter(hits))) if len(hits) == 1 else None)
        _whole_stats(pob_lines, templates)
        missing = [line for line, t in zip(pob_lines, templates) if t is None]
        if missing:
            problems.append("lines_unjoined")
        entry["lines"] = templates
        table[ident] = entry
        lines_total += len(pob_lines)
        lines_matched += len(pob_lines) - len(missing)
        if problems:
            unjoined[ident] = {"en": option["name"], "problems": problems, "lines": missing}
    report = {"hosts": len(hosts), "option_slots": sum(len(v) for v in hosts.values()), "overlay_only": overlay_only,
              "pob_total": len(options), "matched": len(options) - len(unjoined), "missing": len(unjoined),
              "name_matched": names_matched, "lines_total": lines_total, "lines_matched": lines_matched,
              "unjoined": unjoined}
    return {"hosts": {host: slots for host, slots in hosts.items() if slots}, "options": table}, report


def build_passives(pob_nodes, pob_ascendancies, db, pob_classes=None):
    """Join PoB tree nodes to PoE2DB nodes by skill id. Names only when the English names agree;
    stat lines by number_key within the node, so value changes between versions keep the template."""
    db_nodes = {lang: data["nodes"] for lang, data in db.items()}
    table = {}
    kinds = {k: {"pob_total": 0, "matched": 0, "name_matched": 0, "lines_total": 0, "lines_matched": 0}
             for k in TREE_KINDS}
    reasons = defaultdict(list)
    for ident, node in sorted(pob_nodes.items(), key=lambda kv: int(kv[0])):
        kind = tree_node_kind(node)
        stats = kinds[kind]
        stats["pob_total"] += 1
        pob_lines = node["stats"]
        stats["lines_total"] += len(pob_lines)
        found = {lang: nodes.get(ident) for lang, nodes in db_nodes.items()}
        if None in found.values():
            reasons["not_in_poe2db"].append(ident)
            continue
        entry, problems = _join_node(node.get("name", ""), pob_lines, found)
        entry = {"kind": kind, **entry}
        if "name_differs" not in problems:
            stats["name_matched"] += 1
        for problem in problems:
            reasons[problem].append(ident)
        table[ident] = entry
        stats["lines_matched"] += sum(t is not None for t in entry["lines"])
        if not problems:
            stats["matched"] += 1
    db_asc = {lang: {a["id"]: _plain(a["name"]) for c in data["classes"] for a in c["ascendancies"]}
              for lang, data in db.items()}
    ascendancies = {name: {lang: db_asc[lang][internal] for lang in LANGS}
                    for internal, name in pob_ascendancies.items()
                    if db_asc["en"].get(internal) == name and all(internal in db_asc[lang] for lang in LANGS)}
    node_options, option_report = build_node_options(pob_nodes, db)
    classes, class_report = build_classes(pob_classes or {}, db)
    report = {"pob_total": len(pob_nodes), "matched": sum(k["matched"] for k in kinds.values()),
              "missing": len(pob_nodes) - sum(k["matched"] for k in kinds.values()), "ambiguous": 0,
              "poe2db_only": len(set(db_nodes["en"]) - set(pob_nodes) - {"root"}),
              "by_kind": kinds, "reasons": {k: len(v) for k, v in sorted(reasons.items())},
              "reason_ids": dict(sorted(reasons.items())),
              "ascendancies": {"pob_total": len(pob_ascendancies), "matched": len(ascendancies)},
              "classes": class_report, "options": option_report}
    return {"nodes": table, "ascendancies": ascendancies, "classes": classes, "node_options": node_options}, report


def build(terms_dir, pob_root, pob_commit, tree_dir=None):
    tables = load_terms(terms_dir)
    mods_table = tables.pop("mods")["mods"]
    gems, gem_report = build_gems(tables, load_pob_gem_keys(pob_root))
    mods, mod_report = build_mods(mods_table, load_pob_mod_lines(pob_root))
    lines, line_conflicts = build_line_index(mods)
    mod_report["line_index"] = {"keys": len(lines), "ambiguous": len(line_conflicts)}
    bases, base_report = _by_name(tables, "base_types", load_pob_base_names(pob_root))
    uniques, unique_report = build_uniques(tables, load_pob_unique_names(pob_root))
    meta = {"format": FORMAT, "pob_commit": pob_commit, "terms_version": "poe2db-1.0", "languages": list(LANGS)}
    out = {"gems": {**meta, **gems}, "mods": {**meta, "mods": mods, "lines": lines},
           "bases": {**meta, "bases": bases}, "uniques": {**meta, "uniques": uniques}}
    coverage = {**meta, "gems": gem_report, "mods": mod_report, "bases": base_report, "uniques": unique_report}
    if tree_dir:
        version = pob_tree_version(pob_root)
        db = load_poe2db_tree(tree_dir)
        passives, passive_report = build_passives(*load_pob_tree(pob_root, version), db,
                                                  pob_classes=load_pob_classes(pob_root, version))
        tree_meta = {"pob_tree_version": version, "poe2db_tree": POE2DB_TREE_URL}
        out["passives"] = {**meta, **tree_meta, **passives}
        coverage["passives"] = {**tree_meta, **passive_report}
    return out, coverage


def summary_lines(coverage):
    rows = [f"PoB {coverage['pob_commit'][:7]} vs {coverage['terms_version']}",
            "category  pob_total  matched  missing  ambiguous  poe2db_only"]
    for cat in ("gems", "mods", "bases", "uniques", "passives"):
        if cat not in coverage:
            continue
        r = coverage[cat]
        rows.append(f"{cat:<9} {r['pob_total']:>9}  {r['matched']:>7}  {r['missing']:>7}  {r['ambiguous']:>9}  "
                    f"{r['poe2db_only']:>11}")
    for name, r in coverage["mods"]["by_file"].items():
        rows.append(f"  {name:<17} {r['pob_total']:>6}  {r['matched']:>7}  {r['missing']:>7}  {r['ambiguous']:>9}")
    if "passives" in coverage:
        p = coverage["passives"]
        rows.append(f"passives: PoB tree {p['pob_tree_version']} vs {p['poe2db_tree']} "
                    "(matched = name and every stat line)")
        rows.append("  kind          pob_total  matched  name_matched  lines_total  lines_matched")
        for kind, r in p["by_kind"].items():
            rows.append(f"  {kind:<13} {r['pob_total']:>9}  {r['matched']:>7}  {r['name_matched']:>12}  "
                        f"{r['lines_total']:>11}  {r['lines_matched']:>13}")
        rows.append("  reasons: " + ", ".join(f"{k} {v}" for k, v in p["reasons"].items()))
        rows.append(f"  ascendancy names: {p['ascendancies']['matched']}/{p['ascendancies']['pob_total']}")
        if "classes" in p:
            rows.append(f"  class names: {p['classes']['matched']}/{p['classes']['pob_total']}"
                        + (f" (unjoined: {', '.join(p['classes']['unjoined'])})" if p["classes"]["unjoined"] else ""))
        o = p["options"]
        rows.append(f"  node options: {o['hosts']} host nodes, {o['option_slots']} slots ({o['overlay_only']} overlay-only); "
                    f"distinct options {o['matched']}/{o['pob_total']}, names {o['name_matched']}, "
                    f"lines {o['lines_matched']}/{o['lines_total']}")
        for ident, u in o["unjoined"].items():
            rows.append(f"    unjoined {ident} {u['en']} [{', '.join(u['problems'])}]" +
                        (": " + " / ".join(u["lines"]) if u["lines"] else ""))
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--terms", required=True)
    parser.add_argument("--pob", required=True)
    parser.add_argument("--pob-commit", default=None, help="defaults to sources/pob.json commit")
    parser.add_argument("--out", required=True)
    parser.add_argument("--tree", help="dir with PoE2DB data_us/cn/tw.json passive tree files")
    args = parser.parse_args(argv)
    commit = args.pob_commit or json.loads(
        (Path(__file__).resolve().parent.parent / "sources" / "pob.json").read_text(encoding="utf-8"))["commit"]
    out, coverage = build(args.terms, args.pob, commit, args.tree)
    dest = Path(args.out)
    dest.mkdir(parents=True, exist_ok=True)
    for name, data in {**out, "coverage": coverage}.items():
        (dest / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                                          encoding="utf-8")
    text = "\n".join(summary_lines(coverage)) + "\n"
    (dest / "coverage.txt").write_text(text, encoding="utf-8")
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
