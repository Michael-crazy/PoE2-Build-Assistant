#!/usr/bin/env python3
"""Convert in-game item text (Simplified/Traditional Chinese or English) into
PoB-readable English using the PoE2DB tables in data/terms/poe2db-1.0.

Every line gets a result; lines that cannot be matched to the tables are kept
verbatim and listed in ``unrecognized``. Nothing is guessed.
"""

import argparse
import json
from pathlib import Path
import re
import sys

DATA = Path(__file__).resolve().parents[1] / "data/terms/poe2db-1.0"
LANGS = ("zh_hans", "zh_hant", "en")
SEPARATOR = "--------"

# Game UI words that are not item terms, so PoE2DB has no table for them.
# Simplified forms come from Tencent client copies; Traditional forms from the
# TWItemImporter plugin (PoeCharm2) that targets the international client.
SPECS = {
    "Item Class": ("物品类别", "物品類別", "物品種類", "物品种类"),
    "Rarity": ("稀有度",),
    "Quality": ("品质", "品質", "质量"),
    "Armour": ("护甲", "護甲", "护甲值", "護甲值"),
    "Evasion Rating": ("闪避值", "閃避值", "闪避", "閃避"),
    "Energy Shield": ("能量护盾", "能量護盾"),
    "Runic Ward": ("保護", "符文保護", "符文结界"),
    "Spirit": ("精魂",),
    "Block chance": ("格挡率", "格擋率", "格挡几率", "格擋機率"),
    "Physical Damage": ("物理伤害", "物理傷害"),
    "Elemental Damage": ("元素伤害", "元素傷害"),
    "Chaos Damage": ("混沌伤害", "混沌傷害"),
    "Fire Damage": ("火焰伤害", "火焰傷害"),
    "Cold Damage": ("冰霜伤害", "冰冷伤害", "冰冷傷害"),
    "Lightning Damage": ("闪电伤害", "閃電傷害"),
    "Critical Hit Chance": ("暴击率", "暴擊率", "暴击几率", "暴擊機率"),
    "Attacks per Second": ("每秒攻击次数", "每秒攻擊次數"),
    "Reload Time": ("装填时间", "重新装填时间", "重新裝填時間"),
    "Sockets": ("插槽",),
    "Item Level": ("物品等级", "物品等級"),
    "Charm Slots": ("护符栏位", "護符欄位"),
    "Radius": ("半径", "半徑"),
    "Limited to": ("限定",),
    "Requires": ("需求",),
}
SPEC_NAMES = {alias: english for english, aliases in SPECS.items() for alias in (english, *aliases)}
SPEC_NAMES["Requirements"] = "Requires"
RARITIES = {"普通": "Normal", "魔法": "Magic", "稀有": "Rare", "传奇": "Unique", "傳奇": "Unique",
            "Normal": "Normal", "Magic": "Magic", "Rare": "Rare", "Unique": "Unique"}
ATTRIBUTES = {"力量": "Str", "敏捷": "Dex", "智慧": "Int", "Str": "Str", "Dex": "Dex", "Int": "Int",
              "Strength": "Str", "Dexterity": "Dex", "Intelligence": "Int"}
LEVEL_WORDS = ("等级", "等級", "Level")
STATUS = {"被腐化": "Corrupted", "已腐化": "Corrupted", "已汙染": "Corrupted", "已污染": "Corrupted",
          "Corrupted": "Corrupted", "未鉴定": "Unidentified", "未鑑定": "Unidentified",
          "Unidentified": "Unidentified", "镜像": "Mirrored", "鏡像": "Mirrored", "Mirrored": "Mirrored"}
# Market price note: "Note: ~b/o 5 exalted" (Traditional "備註", Simplified "备注").
PRICE_NOTE = re.compile(r"^(?:Note|備註|备注)\s*[:：]\s*~(b/o|price)\s+(\d+(?:\.\d+)?(?:/\d+(?:\.\d+)?)?)\s+(\S.*?)\s*$")
PRICE_KINDS = {"b/o": "buyout", "price": "price"}
# Words inside "{ ... }" advanced-copy headers.
HEADER_WORDS = (
    (("腐化", "Corruption"), "Corruption"),
    (("强化", "強化", "Enhancement"), "Enhancement"),
    (("亵渎", "褻瀆", "Desecrated"), "Desecrated"),
    (("破裂", "Fractured"), "Fractured"),
    (("前缀", "前綴", "Prefix"), "Prefix"),
    (("后缀", "後綴", "Suffix"), "Suffix"),
    # "{ 基底属性 }" (Tencent 1.0) heads the base type's own lines, e.g. Trarthan Cannon's
    # "无法装填或发射弹药"; they match the base implicit table, as "{ Implicit Modifier }" does.
    (("隐性", "隱性", "固定", "基底", "Implicit"), "Implicit"),
    (("传奇", "傳奇", "Unique"), "Unique"),
)
LINE_FLAGS = re.compile(r"\s*\(([a-z]+)\)$")
UNSCALABLE = re.compile(r"\s*[—-]\s*(?:無法變動的值|无法变动的值|不可变动的值|数值不可调整|數值不可調整|Unscalable Value)$")
BONDED = re.compile(r"^(?:羁绊|羈絆|Bonded)\s*[:：]\s*")
GRANTED = re.compile(r"^(?:获得技能|賦予技能|Grants Skill)\s*[:：]\s*(?:(?:等级|等級|Level)\s*(\d+)\s+)?(.+)$")
PLACEHOLDER = {"Rare": "Unnamed Rare", "Unique": "Unknown Unique"}
DAMAGE_RANGE = re.compile(r"(\d)\s*(?:到|至|to)\s*(\d)")
# Usage text the client appends (jewels, flasks, ...); PoB has no use for it.
DESCRIPTION = re.compile(r"右鍵點擊|右键点击|Right click", re.I)
HEADER = re.compile(r'^\{\s*(?P<kind>[^"(—}]*?)\s*(?:"(?P<name>[^"]*)")?\s*(?:\((?P<tier>[^)]*)\))?'
                    r'\s*(?:[—-]\s*(?P<tags>[^}]*?))?\s*\}$')
NUMBER = re.compile(r"(?P<value>\d+(?:\.\d+)?|#)(?:\s*\((?P<lo>-?\d+(?:\.\d+)?)(?:-(?P<hi>-?\d+(?:\.\d+)?))?\))?")
PUNCTUATION = str.maketrans({"：": ":", "，": ",", "（": "(", "）": ")", "－": "-", "＋": "+", "％": "%"})
CJK = re.compile(r"[㐀-鿿]")
# Lines the client adds that are no modifier. "引路石掉落" closes Tencent copies of every rarity
# (meaning unconfirmed); "由<符文>铸造" heads the rune lines of an item a converting rune such as
# 奥杜尔之热情 (Passion of Aldur) went into, whose effect is already in the item's own lines.
MARKERS = re.compile(r"^(?:引路石掉落|由(?P<rune>\S+)铸造)$")
# Unique lines with a name slot: PoE2DB writes the slot as an English word in every language.
SLOTS = {"Passive Skill": "passive", "Specific Skill": "skill"}
PASSIVES = Path(__file__).resolve().parents[1] / "data/terms/pob-localization/passives.json"
# Uniques whose PoE2DB lines are one PoB line ("Passives in radius of X can be Allocated without
# being connected to your tree", PoB Data/Uniques/Special/Generated.lua).
JOINED_UNIQUES = {"From_Nothing"}


def tokens(text):
    """Split text into literal pieces and signed numbers ('#' counts as a number)."""
    result, last = [], 0
    for match in NUMBER.finditer(text):
        start = match.start()
        sign = ""
        if start > last and text[start - 1] in "+-":
            before = text[start - 2] if start >= 2 else ""
            if not (before.isdigit() or before in (")", "#")):
                sign, start = text[start - 1], start - 1
        result.append(text[last:start])
        lo, hi = match.group("lo"), match.group("hi")
        result.append({"sign": sign, "value": match.group("value"),
                       "range": None if lo is None else (lo, hi)})
        last = match.end()
    result.append(text[last:])
    return result


def skeleton(text):
    parts = tokens(text.translate(PUNCTUATION))
    return "".join("#" if isinstance(part, dict) else re.sub(r"\s+", "", part) for part in parts).casefold()


def numbers(parts):
    return [part for part in parts if isinstance(part, dict)]


class Terms:
    """Reverse index over PoE2DB templates: skeleton -> (entry, line index)."""

    def __init__(self, directory=DATA):
        directory = Path(directory)
        self.index = {lang: {} for lang in LANGS}
        self.bases, self.uniques, self.affixes = {}, {}, {lang: {} for lang in LANGS}
        self.entries, self.mod_affix, self.skills = [], {}, {}
        self.slotted = {lang: [] for lang in LANGS}  # (pattern on the skeleton, entry, slot word)
        self._passives = None
        # English base / unique key / English gem name -> names in every language.
        self.names = {"base": {}, "unique": {}, "skill": {}}
        # Price-note currency id (trade id, or a name in any language) -> names.
        self.currencies = {}
        mods = json.loads((directory / "mods.json").read_text(encoding="utf-8"))["mods"]
        for mod_id, mod in mods.items():
            if mod.get("en"):
                self.add("mod", mod_id, mod, mod["ranges"], set(mod["classes"]))
            for essence in mod.get("essences", []):
                if "line" in essence:  # Only pick-one essence texts carry their own line.
                    self.add("essence", mod_id, essence["line"], essence["line"]["ranges"], set(mod["classes"]),
                             gen=mod["generation_type"])
            if mod.get("affix"):
                self.mod_affix[mod_id] = mod["affix"]["en"]
            for lang in LANGS:
                if mod.get("affix"):
                    self.affixes[lang].setdefault(mod["affix"][lang], set()).add(mod["affix"]["en"])
        socketables = {}
        for path in sorted(directory.glob("*.json")):
            if path.name == "mods.json":
                continue
            table = json.loads(path.read_text(encoding="utf-8"))
            item_class = table["metadata"].get("item_class")
            for slug, currency in table.get("currencies", {}).items():
                record = {"slug": slug, **currency}
                for name in [currency.get("trade_id")] + [currency[lang] for lang in LANGS]:
                    if name:
                        self.currencies.setdefault(name.casefold(), record)
            for gem in table.get("gems", {}).values():
                for lang in LANGS:
                    self.skills.setdefault((lang, gem[lang]), gem["en"])
                self.names["skill"].setdefault(gem["en"], gem)
            for key, base in table.get("base_types", {}).items():
                record = {"key": key, "class": item_class, **{lang: base[lang] for lang in LANGS}}
                self.names["base"].setdefault(base["en"], record)
                for lang in LANGS:
                    self.bases.setdefault((lang, base[lang]), []).append(record)
                for number, implicit in enumerate(base["implicits"]):
                    self.add("implicit", f"{key}#{number}",
                             {lang: [implicit[lang]] for lang in LANGS if implicit.get(lang)}, [], {item_class})
            for key, unique in table.get("uniques", {}).items():
                record = {"key": key, "class": item_class, "base": unique["base"],
                          **{lang: unique[lang] for lang in LANGS}}
                self.names["unique"].setdefault(key, record)
                for lang in LANGS:
                    self.uniques.setdefault((lang, unique[lang]), []).append(record)
                for number, line in enumerate(unique["implicits"] + unique["explicits"]):
                    entry = self.add("unique", key, {lang: [line[lang]] for lang in LANGS if line.get(lang)},
                                     [], {item_class})
                    self.add_slotted(entry)
            for rune_id, rune in table.get("socketables", {}).items():
                for line in rune["lines"]:
                    key = (rune_id, line["section"], tuple(line["en"]))
                    if key in socketables:
                        socketables[key]["classes"].add(item_class)
                    else:
                        socketables[key] = self.add("socketable", rune_id, line, line["ranges"], {item_class},
                                                    section=line["section"])

    def add(self, kind, entry_id, texts, ranges, classes, gen=None, section=None):
        entry = {"kind": kind, "id": entry_id, "texts": {lang: list(texts.get(lang) or []) for lang in LANGS},
                 "ranges": [tuple(r) for r in ranges], "classes": classes,
                 "gen": gen or texts.get("generation_type"), "affix": texts.get("affix"),
                 "section": section}
        for lang in ("en", "zh_hant"):
            # Some rune lines are split in two on one page and not the other.
            if len(entry["texts"][lang]) > 1 and len(entry["texts"]["zh_hans"]) == 1:
                entry["texts"][lang] = [" ".join(entry["texts"][lang])]
        self.entries.append(entry)
        # Skills granted by bases and uniques that are not in the gem tables.
        for number, line in enumerate(entry["texts"]["en"]):
            english = GRANTED.match(line)
            for lang in LANGS:
                texts = entry["texts"][lang]
                local = GRANTED.match(texts[number]) if english and number < len(texts) else None
                if local:
                    self.skills.setdefault((lang, local.group(2).strip()), english.group(2).strip())
        for lang in LANGS:
            for number, line in enumerate(entry["texts"][lang]):
                self.index[lang].setdefault(skeleton(line), []).append((entry, number))
        return entry

    def add_slotted(self, entry):
        english = entry["texts"]["en"]
        for word in SLOTS:
            if len(english) != 1 or word not in english[0]:
                continue
            for lang in LANGS:
                local = entry["texts"][lang]
                if len(local) == 1 and word in local[0]:
                    parts = skeleton(local[0]).split(skeleton(word))
                    if len(parts) == 2:
                        pattern = re.compile(re.escape(parts[0]) + "(.+?)" + re.escape(parts[1]))
                        self.slotted[lang].append((pattern, entry, word))

    def slot_name(self, word, lang, key):
        """English name for the text in a slot (compared as skeletons), or None."""
        if SLOTS[word] == "skill":
            names = {english for (skill_lang, name), english in self.skills.items()
                     if skill_lang == lang and skeleton(name) == key}
        else:
            if self._passives is None:
                self._passives = {}
                if PASSIVES.exists():
                    for node in json.loads(PASSIVES.read_text(encoding="utf-8"))["nodes"].values():
                        for passive_lang in LANGS:
                            if node.get(passive_lang) and node.get("en"):
                                self._passives.setdefault((passive_lang, skeleton(node[passive_lang])),
                                                          set()).add(node["en"])
            names = self._passives.get((lang, key), set())
        return next(iter(names)) if len(names) == 1 else None




_TERMS = None


def terms():
    global _TERMS
    if _TERMS is None:
        _TERMS = Terms()
    return _TERMS


def render(template, values):
    """Put line values (sign, number, roll range) into an English template."""
    slots, out = iter(values), []
    for part in tokens(template):
        if not isinstance(part, dict):
            out.append(part)
        elif part["value"] != "#":
            out.append(part["sign"] + part["value"])
        else:
            value = next(slots)
            text = ("-" if value["sign"] == "-" else part["sign"]) + value["value"]
            if value["range"]:
                lo, hi = value["range"]
                text += f"({lo})" if hi is None else f"({lo}-{hi})"
            out.append(text)
    return "".join(out)


def fit(entry, number, lang, values):
    """Values for the template's '#' slots if the line's numbers fit it, else None."""
    template = numbers(tokens(entry["texts"][lang][number].translate(PUNCTUATION)))
    english = entry["texts"]["en"]
    if len(template) != len(values) or len(english) <= number:
        return None
    hashed = []
    for slot, value in zip(template, values):
        if slot["value"] == "#":
            hashed.append(value)
        elif slot["value"] != value["value"] or value["range"]:
            return None
    if sum(slot["value"] == "#" for slot in numbers(tokens(english[number]))) != len(hashed):
        return None
    return hashed


def signed(value):
    return float(value["value"]) * (-1 if value["sign"] == "-" else 1)


def shown_ranges_match(values, ranges):
    shown = [value["range"] for value in values]
    if not ranges or len(ranges) != len(values) or None in shown:
        return False
    return all(float(lo) == r[0] and float(hi if hi is not None else lo) == r[1]
               for (lo, hi), r in zip(shown, ranges))


def values_in_ranges(values, ranges):
    return len(ranges) == len(values) and all(
        min(lo, hi) <= signed(v) <= max(lo, hi) or min(lo, hi) <= abs(signed(v)) <= max(abs(lo), abs(hi))
        for v, (lo, hi) in zip(values, ranges))


def narrow(candidates, *tests):
    """Apply each preference only when it keeps at least one candidate."""
    for test in tests:
        kept = [c for c in candidates if test(c)]
        if kept:
            candidates = kept
    return candidates


KIND_ORDER = {
    "rune": ("socketable", "mod", "unique", "implicit", "essence"),
    "implicit": ("implicit", "mod", "unique", "essence", "socketable"),
    "unique": ("unique", "mod", "implicit", "essence", "socketable"),
    "corruption": ("mod", "implicit", "unique", "essence", "socketable"),
    None: ("mod", "essence", "implicit", "unique", "socketable"),
}


def match_line(body, flags, lang, context, header=None, block=None):
    """Match one modifier line; returns (english, ids, status, note)."""
    values = numbers(tokens(body.translate(PUNCTUATION)))
    found = terms().index[lang].get(skeleton(body), [])
    fitted = [(entry, number, slots) for entry, number in found
              for slots in [fit(entry, number, lang, values)] if slots is not None]
    if not fitted:
        if not found:
            slotted = match_slotted(body, lang, values, context)
            if slotted:
                return slotted
        return None, [], "unrecognized", "数值与模板不符" if found else "无对应模板"
    role = next((flag for flag in ("rune", "corruption", "implicit") if flag in flags),
                "unique" if context.get("unique") else None)
    for kind in KIND_ORDER[role]:
        group = [c for c in fitted if c[0]["kind"] == kind]
        if group:
            break
    header = header or {}
    group = narrow(
        group,
        lambda c: not block or (len(c[0]["texts"]["en"]) == block[1] and c[1] == block[0]),
        lambda c: c[0]["kind"] != "unique" or c[0]["id"] == context.get("unique"),
        lambda c: c[0]["kind"] != "implicit" or c[0]["id"].split("#")[0] == context.get("base_key"),
        lambda c: context.get("class") in c[0]["classes"],
        lambda c: c[0]["kind"] != "socketable"
        or c[0]["section"] == ("bonded" if context.get("bonded") else "socketable"),
        lambda c: header.get("gen") is not None and c[0]["gen"] == header["gen"],
        lambda c: bool(header.get("name")) and (c[0]["affix"] or {}).get(lang) == header["name"],
        lambda c: role is not None or c[0]["gen"] in ("1", "2"),
        lambda c: role != "corruption" or c[0]["gen"] in ("3", "5"),
        lambda c: shown_ranges_match(c[2], c[0]["ranges"]),
        lambda c: values_in_ranges(c[2], c[0]["ranges"]),
    )
    renders = {}
    for entry, number, slots in group:
        text = body if lang == "en" else render(entry["texts"]["en"][number], slots)
        renders.setdefault(text.casefold(), text)
    ids = sorted({f"{entry['kind']}:{entry['id']}" for entry, _, _ in group})
    if len(renders) > 1:
        return None, ids, "ambiguous", "候选英文不一致：" + " | ".join(renders.values())
    return next(iter(renders.values())), ids, "matched", None


def match_slotted(body, lang, values, context):
    """Unique lines with a name slot ("所有烈焰爆破技能等级 +2" -> "+2 to Level of all Flameblast Skills")."""
    key, hits, missing = skeleton(body), [], []
    for pattern, entry, word in terms().slotted[lang]:
        match = pattern.fullmatch(key)
        slots = match and fit(entry, 0, lang, values)
        if slots is None or not match:
            continue
        name = terms().slot_name(word, lang, match.group(1))
        if name is None:
            missing.append(match.group(1))
            continue
        hits.append((entry, render(entry["texts"]["en"][0], slots).replace(word, name)))
    hits = narrow(hits, lambda h: h[0]["id"] == context.get("unique"))
    renders = {text.casefold(): text for _, text in hits}
    ids = sorted({f"unique:{entry['id']}" for entry, _ in hits})
    if len(renders) == 1:
        return next(iter(renders.values())), ids, "matched", None
    if len(renders) > 1:
        return None, ids, "ambiguous", "候选英文不一致：" + " | ".join(renders.values())
    if missing:
        return None, [], "unrecognized", "名称不在编年史宝石表/天赋表中：" + "、".join(sorted(set(missing)))
    return None


def parse_header(text):
    match = HEADER.match(text)
    if not match:
        return None
    words = [english for aliases, english in HEADER_WORDS
             if any(alias in match.group("kind") for alias in aliases)]
    if not {"Prefix", "Suffix", "Implicit", "Unique", "Enhancement"} & set(words):
        return None
    tier = re.search(r"\d+", match.group("tier") or "")
    return {"words": words, "name": match.group("name"), "tier": tier.group() if tier else None,
            "gen": "1" if "Prefix" in words else "2" if "Suffix" in words else None,
            "tags": match.group("tags")}


def header_text(header, affix):
    if "Enhancement" in header["words"]:
        return "{ " + " ".join(header["words"]) + " }"  # e.g. "{ Corruption Enhancement }"
    text = "{ " + " ".join(header["words"]) + " Modifier"
    if affix:
        text += f' "{affix}"'
    if header["tier"]:
        text += f" (Tier: {header['tier']})"
    return text + " }"


def detect_language(lines):
    text = "\n".join(lines)
    # Header keys follow the client language; rare names and notes may not.
    if not CJK.search(text) or re.match(r"(Item Class|Rarity)\s*:", lines[0]):
        return "en"
    score = {"zh_hans": 0, "zh_hant": 0}
    for line in lines:
        key = skeleton(LINE_FLAGS.sub("", line))
        for lang in score:
            score[lang] += key in terms().index[lang]
    for hans, hant in (("类别", "類別"), ("种类", "種類"), ("等级", "等級"), ("品质", "品質"), ("护", "護")):
        score["zh_hans"] += hans in text
        score["zh_hant"] += hant in text
    return "zh_hant" if score["zh_hant"] > score["zh_hans"] else "zh_hans"


def translate_requirements(value):
    parts = []
    for piece in (piece.strip() for piece in value.split(",")):
        level = re.fullmatch(r"(?:%s)\s*:?\s*(\d.*)" % "|".join(LEVEL_WORDS), piece)
        attribute = re.fullmatch(r"(\d+(?:\s*\([a-z]+\))?)\s*(\S+)", piece)
        if level:
            parts.append("Level " + level.group(1))
        elif attribute and attribute.group(2) in ATTRIBUTES:
            parts.append(f"{attribute.group(1)} {ATTRIBUTES[attribute.group(2)]}")
        else:
            return None
    return "Requires: " + ", ".join(parts)


def translate_names(names, lang, rarity):
    """Fill in the name/base lines; returns item context (class, base, unique key)."""
    context = {}
    if not names:
        return context
    if rarity in ("Rare", "Unique") and len(names) >= 2:
        name, base_line = names[:2]
        bases = terms().bases.get((lang, base_line["text"]), [])
        if bases:
            context.update({"class": bases[0]["class"], "base": bases[0]["en"], "base_key": bases[0]["key"]})
            base_line.update(english=bases[0]["en"], status="matched", ids=[f"base:{bases[0]['key']}"])
        if rarity == "Unique":
            named = terms().uniques.get((lang, name["text"]), [])
            # 1.0 adds base variants (e.g. Runemastered Shaman Mantle for Reverie's
            # Shaman Mantle); prefer an exact base, else accept the unique by name.
            uniques = [u for u in named if bases and u["base"]["en"] == bases[0]["en"]] or \
                [u for u in named if bases and u["base"]["en"] in bases[0]["en"]] or named
            if uniques:
                context["unique"] = uniques[0]["key"]
                context.setdefault("class", uniques[0]["class"])
                note = None
                if bases and uniques[0]["base"]["en"] != bases[0]["en"]:
                    note = f"表中该传奇的基底是 {uniques[0]['base']['en']}"
                name.update(english=uniques[0]["en"], status="matched", note=note,
                            ids=sorted({f"unique:{u['key']}" for u in uniques}))
        if name["status"] is None and lang == "en":
            name.update(english=name["text"], status="matched")
        elif name["status"] is None:
            # PoB turns every non-ASCII byte into "?", so a Chinese name cannot be kept.
            reason = "稀有名称没有对照表" if rarity == "Rare" else "传奇名不在编年史 1.0 表中（可能已改名或为国服独有）"
            # An unknown unique name is still reported; a rare name never has a table.
            name.update(english=PLACEHOLDER[rarity], note=reason + "，PoB 文本用占位名",
                        status="placeholder" if rarity == "Rare" else "unrecognized")
        return context
    line = names[0]
    best = max(((base_name, records[0]) for (base_lang, base_name), records in terms().bases.items()
                if base_lang == lang and base_name and base_name in line["text"]),
               key=lambda pair: len(pair[0]), default=None)
    if not best:
        return context
    base_name, base = best
    context.update({"class": base["class"], "base": base["en"], "base_key": base["key"]})
    prefix, suffix = (part.strip() for part in line["text"].split(base_name, 1))
    words, missing = [], []
    for part in (prefix, None, suffix):
        if part is None:
            words.append(base["en"])
        elif part:
            english = terms().affixes[lang].get(part, set())
            if len(english) == 1:
                words.append(next(iter(english)))
            else:
                missing.append(part)
    if missing:
        line.update(english=base["en"], status="kept", ids=[f"base:{base['key']}"],
                    note="名称词缀未识别：" + "、".join(missing) + "，只保留基底")
    else:
        line.update(english=" ".join(words), status="matched", ids=[f"base:{base['key']}"])
    return context


def granted_skill(match, lang):
    """'获得技能: 等级 19 恢复圣仪' -> 'Grants Skill: Level 19 Rite of Restoration'."""
    level, name = match.group(1), match.group(2).strip()
    english = name if lang == "en" else terms().skills.get((lang, name))
    if english is None:
        return None, [], "unrecognized", f"技能名“{name}”不在宝石表和固定词缀里"
    return f"Grants Skill: {'Level ' + level + ' ' if level else ''}{english}", [f"skill:{english}"], "matched", None


def split_spec(text):
    match = re.match(r"^([^:：]+?)\s*[:：]\s*(.*)$", text)
    return (SPEC_NAMES.get(match.group(1)), match.group(2)) if match else (None, None)


def parse_item(text, lang=None):
    """Return the English item text and a result for every non-blank input line."""
    raw = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    lines = [line.strip() for line in raw if line.strip()]
    if not lines:
        raise ValueError("装备文本为空")
    lang = lang or detect_language(lines)
    results, section = [], 0
    for number, line in enumerate(raw, 1):
        line = line.strip()
        if not line:
            continue
        section += line == SEPARATOR
        results.append({"line": number, "section": section, "text": line, "kind": None,
                        "english": None, "status": None, "ids": [], "note": None})

    # Pass 1: classify lines and group advanced-copy blocks.
    rarity, names, blocks, block = None, [], [], None
    for result in results:
        text = result["text"]
        key, value = split_spec(text)
        if text == SEPARATOR:
            result.update(kind="separator", english=text, status="matched")
            block = None
        elif PRICE_NOTE.match(text):
            result.update(kind="price", status="dropped", note="价格备注，不进 PoB")
        elif key == "Rarity" and result["section"] == 0:
            rarity = RARITIES.get(value)
            result["kind"] = "header"
            if rarity:
                result.update(english="Rarity: " + rarity, status="matched")
        elif key and result["section"] == 0:
            result["kind"] = "header"
        elif result["section"] == 0:
            result["kind"] = "name"
            names.append(result)
        elif key:
            result["kind"] = "property"
        elif text in STATUS:
            result.update(kind="status", english=STATUS[text], status="matched")
        elif text.startswith("{"):
            result["kind"] = "mod_header"
            header = parse_header(text)
            block = {"header": header, "result": result, "lines": []} if header else None
            if block:
                blocks.append(block)
        else:
            result.update(kind="modifier", block=block)
            if block:
                block["lines"].append(result)

    # Pass 2: translate with the item context (class, unique) known.
    context = translate_names(names, lang, rarity)
    for result in results:
        key, value = split_spec(result["text"])
        if result["kind"] == "header" and key == "Item Class":
            if context.get("class"):
                result.update(english="Item Class: " + context["class"].replace("_", " "), status="matched")
            elif lang == "en":
                result.update(english=result["text"], status="matched")
        elif result["kind"] == "property":
            value = value.translate(PUNCTUATION).strip()
            if key.endswith("Damage"):
                value = DAMAGE_RANGE.sub(r"\1-\2", value)
            english = translate_requirements(value) if key == "Requires" else f"{key}: {value}"
            if english and not CJK.search(english):
                result.update(english=english, status="matched")
        elif result["kind"] == "modifier":
            body, flags, unscalable = result["text"], [], False
            while True:
                flag, fixed = LINE_FLAGS.search(body), UNSCALABLE.search(body)
                if flag:
                    flags.insert(0, flag.group(1))
                    body = body[:flag.start()]
                elif fixed:
                    unscalable, body = True, body[:fixed.start()]
                else:
                    break
            block = result.pop("block")
            marker = MARKERS.match(body)
            if marker and (not marker.group("rune") or terms().bases.get((lang, marker.group("rune")))):
                result.update(kind="marker", status="dropped",
                              note="符文说明，效果已在物品词缀里，PoB 不需要" if marker.group("rune")
                              else "引路石掉落标记，不是词缀，PoB 不读取；含义未确认")
                continue
            position = (block["lines"].index(result), len(block["lines"])) if block else None
            header = block and block["header"]
            # Advanced copy marks implicits (and corruption enhancements) by header only.
            words = set(header["words"]) if header else set()
            role_flags = flags + ["corruption"] if "Enhancement" in words else \
                flags + ["implicit"] if "Implicit" in words else flags
            bonded = BONDED.match(body)
            granted = GRANTED.match(body)
            if bonded:
                body = body[bonded.end():]
            if granted:
                english, ids, status, note = granted_skill(granted, lang)
            else:
                line_context = dict(context, bonded=True) if bonded else context
                english, ids, status, note = match_line(body, role_flags, lang, line_context, header, position)
            result.update(ids=ids, status=status, note=note)
            if english is not None:
                result["english"] = (("Bonded: " if bonded else "") + english
                                     + (" — Unscalable Value" if unscalable else "")
                                     + "".join(f" ({flag})" for flag in flags))
    for block in blocks:
        header, result = block["header"], block["result"]
        affixes = {terms().mod_affix.get(entry_id.partition(":")[2])
                   for line in block["lines"] for entry_id in line["ids"] if entry_id.startswith("mod:")}
        affixes.discard(None)
        named = {"Prefix", "Suffix"} & set(header["words"])
        affix = next(iter(affixes)) if len(affixes) == 1 and named else None
        result["status"] = "matched"
        if lang == "en":
            result["english"] = result["text"]
            continue
        result["english"] = header_text(header, affix)
        notes = []
        if header["name"] and named and not affix:
            notes.append("词缀名未能确定，英文头部省略名称")
        if header["tags"]:
            notes.append("标签没有对照表，已省略")
        result["note"] = "；".join(notes) or None

    join_unique_lines(results)
    for result in results:
        if result["status"] is None:
            result.update(status="unrecognized", note=result["note"] or "无法识别")
    drop_descriptions(results, rarity)
    for result in results:
        if result["english"] is None and result["status"] != "dropped":
            result["english"] = result["text"]
    output = []
    for result in results:
        if result["status"] != "dropped" and not (result["english"] == SEPARATOR and output[-1:] == [SEPARATOR]):
            output.append(result["english"])
    while output and output[-1] == SEPARATOR:
        output.pop()
    prices = [price_note(r["text"], lang) for r in results if r["kind"] == "price"]
    return {
        "language": lang, "rarity": rarity, "item_class": context.get("class"),
        "base": context.get("base"), "unique": context.get("unique"),
        "price": prices[-1] if prices else None,
        "text": "\n".join(output) + "\n",
        "lines": results,
        "unrecognized": [{"line": r["line"], "text": r["text"], "status": r["status"], "note": r["note"]}
                         for r in results if r["status"] in ("unrecognized", "ambiguous")],
    }


def join_unique_lines(results):
    """PoE2DB splits some unique lines in two that PoB reads as one (JOINED_UNIQUES)."""
    mods = [r for r in results if r["kind"] == "modifier"]
    for first, second in zip(mods, mods[1:]):
        ids = {f"unique:{key}" for key in JOINED_UNIQUES}
        if first["status"] == second["status"] == "matched" and first["ids"] == second["ids"] \
                and len(first["ids"]) == 1 and first["ids"][0] in ids and second["line"] == first["line"] + 1:
            first["english"] = first["english"] + " " + second["english"]
            second.update(kind="joined", status="dropped", note="与上一行合为一条 PoB 词缀")


def price_note(text, lang):
    """'~b/o 5 exalted' -> {kind, amount, currency, currency_name}; an unknown currency keeps its
    id and has no name."""
    kind, amount, currency = PRICE_NOTE.match(text).groups()
    numerator, _, denominator = amount.partition("/")
    value = float(numerator) / float(denominator) if denominator else float(numerator)
    record = terms().currencies.get(currency.casefold())
    return {"kind": PRICE_KINDS[kind], "amount": int(value) if value.is_integer() else value,
            "currency": (record.get("trade_id") or record["slug"]) if record else currency,
            "currency_name": record[lang] if record else None}


def drop_descriptions(results, rarity):
    """Mark usage text and a unique's flavour text; both stay out of the PoB text."""
    for result in results:
        if result["kind"] == "modifier" and result["status"] == "unrecognized" \
                and DESCRIPTION.search(result["text"]):
            result.update(kind="description", status="dropped", note="物品说明文字，不进 PoB")
    sections = {}
    for result in results:
        if result["kind"] != "separator":
            sections.setdefault(result["section"], []).append(result)

    def unmatched(lines):
        return all(r["kind"] in ("modifier", "description") and r["status"] in ("unrecognized", "dropped")
                   for r in lines)

    # Lines in sections after the status line (Corrupted, ...). PoB stops reading
    # modifiers there; the Tencent client's "引路石掉落" sits here. Meaning unconfirmed.
    status = max((r["section"] for r in results if r["kind"] == "status"), default=None)
    for number, lines in sections.items():
        if status is not None and number > status and unmatched(lines):
            for result in lines:
                if result["kind"] == "modifier":
                    result.update(kind="trailer", status="dropped",
                                  note="状态行之后的附注，PoB 不读取；含义未确认（疑为掉落来源）")
    # Flavour text: on a unique, a section after the last matched modifier where
    # nothing matched and no number appears (quotes and the "——name" signature).
    last_mod = max((r["section"] for r in results if r["kind"] == "modifier" and r["status"] == "matched"),
                   default=0)
    if rarity == "Unique":
        for number, lines in sections.items():
            if number > last_mod and unmatched(lines) and not any(re.search(r"\d", r["text"]) for r in lines):
                for result in lines:
                    if result["kind"] == "modifier":
                        result.update(kind="flavour", status="dropped", note="传奇风味文字，不进 PoB")


def add_parse_arguments(parser):
    parser.add_argument("input", nargs="?", default="-", help="装备文本文件，省略或 - 时读标准输入")
    parser.add_argument("--lang", choices=LANGS, help="默认自动识别")


def run_parse_command(parser, args):
    try:
        if args.input == "-":
            text = sys.stdin.buffer.read().decode("utf-8-sig")
        else:
            text = Path(args.input).read_text(encoding="utf-8-sig")
        result = parse_item(text, args.lang)
    except (OSError, UnicodeDecodeError, ValueError) as error:
        parser.exit(1, f"装备解析失败：{error}\n")
    sys.stdout.buffer.write((json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    add_parse_arguments(parser)
    return run_parse_command(parser, parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
