#!/usr/bin/env python3
"""U07: Tencent-server character from a WeGame share link -> PoB character import data.

The WeGame helper share page (https://www.wegame.com.cn/helper/poe2/#/share/<code>) reads the
character with plain JSON POSTs to /api/v1/wegame.pallas.poe2.Profile/<Method>. The answers use
the official character API layout (equipment items with typeLine/explicitMods/..., the passive
tree as hashes + specialisations), with game text in Simplified Chinese.

`convert` turns such a bundle into the English `character` object PoB's own character import
(ImportTab:ImportPassiveTreeAndJewels / ImportItemsAndSkills) reads. Every Chinese line goes
through P05 (`item_text.parse_item`, PoE2DB tables); nothing is translated here. Lines that do
not convert are kept out of PoB and listed in `report`.

Commands:
  fetch <share link or code> [--out bundle.json]   six requests, the same ones the share page sends
  convert <bundle.json> [--out character.json]     bundle -> {"character": ..., "report": ...}
  anonymise <bundle.json> [--out fixture.json]     drop account, openid, names, share code
"""

import argparse
import json
from pathlib import Path
import re
import sys
import urllib.request

from item_text import ATTRIBUTES, LEVEL_WORDS, PUNCTUATION, SEPARATOR, SPEC_NAMES, match_line, parse_item, terms

API = "https://www.wegame.com.cn/api/v1/wegame.pallas.poe2.Profile/"
FROM_SRC = "poe2_helper"  # what the share page sends
SHARE = re.compile(r"(?:#/share/|^)([A-Za-z0-9_-]{16,})/?\s*$")
METHODS = {"equipments": "GetEquipments", "talent_tree": "GetTalentTree", "jewels": "GetJewels",
           "skills": "GetSkills"}
LANG = "zh_hans"
FRAME = {"Normal": 0, "Magic": 1, "Rare": 2, "Unique": 3, "Legend": 3, "Relic": 9}
RARITY_ZH = {"Normal": "普通", "Magic": "魔法", "Rare": "稀有", "Unique": "传奇", "Legend": "传奇"}
# *Mods arrays that hold explicit lines, and the PoB flag each one carries.
EXPLICIT_FLAGS = {"explicitMods": None, "fracturedMods": "fractured", "craftedMods": "crafted",
                  "desecratedMods": "desecrated", "mutatedMods": "mutated", "veiledMods": None}
PASSIVES = Path(__file__).resolve().parents[1] / "data/terms/pob-localization/passives.json"
ANOINT = re.compile(r"^配置\s*(.+)$")  # amulet enchant "配置 典范" = "Allocates Paragon"
_NOTABLES = None
# parse_item rows that stand for one written line each (kept in order to pair with `fields`).
ROW_KINDS = ("modifier", "description", "flavour", "trailer", "marker", "joined")
PRIVATE = ("openid", "account_name", "nick_name", "name", "share_code", "icon")


def share_code(text):
    match = SHARE.search(text.strip())
    if not match:
        raise ValueError("不是 WeGame 分享链接：应为 https://www.wegame.com.cn/helper/poe2/#/share/<分享码>")
    return match.group(1)


def request_body(role, code):
    """Body for the per-character methods, as the share page builds it."""
    return {"area": role.get("area", 0), "openid": role["openid"], "role_id": role["role_id"],
            "share_code": code, "from_src": FROM_SRC}


def _post(method, body):
    req = urllib.request.Request(API + method, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch(link):
    code = share_code(link)
    bundle = {"format": "wegame-poe2-share/1", "role_info": _post("GetRoleInfo", {
        "share_code": code, "area": 0, "from_src": FROM_SRC})}
    check(bundle["role_info"], "GetRoleInfo")
    body = request_body(bundle["role_info"]["role"], code)
    for key, method in METHODS.items():
        bundle[key] = _post(method, body)
    return bundle


def check(answer, method):
    result = (answer or {}).get("result") or {}
    if result.get("error_code") != 0:
        raise RuntimeError(f"{method} 失败：{result.get('error_code')} {result.get('error_message')}"
                           "（分享可能已过期，请重新生成分享链接）")


def anonymise(bundle):
    """Fixture copy of a bundle: no account, openid, role id/name, share code or league id; item ids
    renumbered (they are unique per item); icon URLs dropped. Game content is kept."""
    bundle = json.loads(json.dumps(bundle))
    info = bundle.get("role_info") or {}
    for key in ("nick_name", "share_code"):
        if key in info:
            info[key] = "<removed>"
    role = info.get("role") or {}
    for key in ("openid", "account_name", "name", "icon"):
        if key in role:
            role[key] = "<removed>"
    role.pop("league_id", None)
    if "role_id" in role:
        role["role_id"] = "1"
    ids = {}

    def walk(value):
        if isinstance(value, dict):
            out = {}
            for key, item in value.items():
                if key in ("icon", "gemSkill", "socketedIcon") or (isinstance(item, str) and item.startswith("https://")):
                    continue
                if key == "id" and isinstance(item, str) and len(item) >= 32:
                    item = ids.setdefault(item, f"item-{len(ids) + 1}")
                out[key] = walk(item)
            return out
        if isinstance(value, list):
            return [walk(item) for item in value]
        return value

    for key in ("equipments", "talent_tree", "skills"):
        if key in bundle:
            bundle[key] = walk(bundle[key])
    jewels = bundle.get("jewels") or {}
    if isinstance(jewels.get("jewel_data"), str):
        jewels["jewel_data"] = json.dumps(walk(json.loads(jewels["jewel_data"])), ensure_ascii=False)
    return bundle


# Items ---------------------------------------------------------------------------------------

def _lines(mods):
    out = []
    for mod in mods or []:
        text = mod if isinstance(mod, str) else (mod or {}).get("description") or ""
        out.extend(_clean(line) for line in text.split("\n") if line.strip())
    return out


def _clean(text):
    # Game markup such as "[Spirit|精魂]" or "<rgb>{...}" -> the shown words.
    text = re.sub(r"\[([^\]|]*)\|([^\]]*)\]", r"\2", text or "")
    text = re.sub(r"\[([^\]]*)\]", r"\1", text)
    return re.sub(r"<[^>]*>\{([^}]*)\}", r"\1", text).strip()


def _value(values):
    return _clean(str(values[0][0])) if values and values[0] else ""


def notable_name(name):
    """Chinese passive name -> English, from the P03 passive table (PoE2DB names)."""
    global _NOTABLES
    if _NOTABLES is None:
        _NOTABLES = {}
        if PASSIVES.exists():
            nodes = json.loads(PASSIVES.read_text(encoding="utf-8"))["nodes"]
            for node in nodes.values():
                if node.get(LANG) and node.get("en"):
                    _NOTABLES.setdefault(node[LANG], set()).add(node["en"])
    english = _NOTABLES.get(name, set())
    return next(iter(english)) if len(english) == 1 else None


def translate_property(prop):
    """{'name': '品质', 'values': [['+20%', 1]]} -> English property, or None."""
    name = _clean(prop.get("name", "")).rstrip(":：")
    english = SPEC_NAMES.get(name)
    if name in LEVEL_WORDS:
        english = "Level"
    if not english:
        return None
    values = [[_clean(str(v[0])).translate(PUNCTUATION).replace("到", "-").replace("至", "-"), *v[1:]]
              for v in prop.get("values") or []]
    return {**prop, "name": english, "values": values}


def translate_requirement(req):
    name = _clean(req.get("name", "")).rstrip(":：")
    if name in LEVEL_WORDS:
        return {**req, "name": "Level"}
    if name in ATTRIBUTES:
        return {**req, "name": {"Str": "Str", "Dex": "Dex", "Int": "Int"}[ATTRIBUTES[name]]}
    return None


def convert_item(item, report, where):
    """WeGame item (Chinese) -> English item in the character API layout, or None."""
    rarity = item.get("rarity") or {0: "Normal", 1: "Magic", 2: "Rare", 3: "Unique"}.get(item.get("frameType"))
    if rarity not in FRAME:
        report["items_skipped"].append({"where": where, "text": item.get("typeLine"), "note": f"未知稀有度 {rarity}"})
        return None
    name, type_line = _clean(item.get("name")), _clean(item.get("typeLine") or item.get("baseType"))
    text = [f"稀有度: {RARITY_ZH[rarity]}"] + ([name] if name else []) + [type_line, SEPARATOR]
    fields = []  # (field, flag) for each modifier line written, in order

    def section(field, lines, flag=None, suffix=""):
        if lines:
            for line in lines:
                text.append(line + suffix)
                fields.append((field, flag))
            text.append(SEPARATOR)

    enchants = []
    for line in _lines(item.get("enchantMods")):
        anoint = ANOINT.match(line)
        english = anoint and notable_name(anoint.group(1).strip())
        if english:
            enchants.append(f"Allocates {english}")
        else:
            text.append(line + " (enchant)")
            fields.append(("enchantMods", None))
    if fields:
        text.append(SEPARATOR)
    section("runeMods", _lines(item.get("runeMods")), suffix=" (rune)")
    section("implicitMods", _lines(item.get("implicitMods")), suffix=" (implicit)")
    for key, flag in EXPLICIT_FLAGS.items():
        section("explicitMods", _lines(item.get(key)), flag)
    parsed = parse_item("\n".join(text), lang=LANG)
    rows = [r for r in parsed["lines"] if r["kind"] in ROW_KINDS]
    names = [r for r in parsed["lines"] if r["kind"] == "name"]
    english = {"enchantMods": [], "runeMods": [], "implicitMods": [], "explicitMods": []}
    for row, (field, flag) in zip(rows, fields):
        if row["status"] in ("matched",) and row["english"]:
            line = re.sub(r"\s*\((?:enchant|rune|implicit)\)$", "", row["english"])
            english[field].append({"description": line, "flags": {flag: True}} if flag else line)
        elif row["status"] == "dropped" and row["kind"] in ("marker", "joined"):
            # Not a modifier of its own (rune note, second half of a joined line): nothing is lost.
            report.setdefault("dropped", []).append({"where": where, "item": type_line, "field": field,
                                                     "text": row["text"], "note": row["note"]})
        else:
            report["lines"].append({"where": where, "item": type_line, "field": field, "text": row["text"],
                                    "status": row["status"], "note": row["note"]})
    if not parsed["base"]:
        report["items_skipped"].append({"where": where, "text": type_line, "note": "基底不在编年史表中"})
        return None
    out = {
        "id": item.get("id") or f"wegame-{where}",
        "inventoryId": item.get("inventoryId"), "x": item.get("x", 0), "y": item.get("y", 0),
        "frameType": FRAME[rarity], "rarity": rarity, "ilvl": int(item.get("ilvl") or item.get("itemLevel") or 0),
        "name": "", "typeLine": parsed["base"], "baseType": parsed["base"],
        "corrupted": bool(item.get("corrupted")), "properties": [], "requirements": [],
    }
    if rarity in ("Rare", "Unique"):
        out["name"] = names[0]["english"] if names and names[0]["english"] else "Unknown"
        if rarity == "Rare" and names and names[0]["status"] != "matched":
            # Rare names have no table; keep the in-game Chinese name, as U06 does (PoB shows CJK).
            out["name"] = names[0]["text"]
            report["names"] += 1
    elif names and names[0]["english"]:
        out["typeLine"] = names[0]["english"]  # magic: "<prefix> Base <suffix>"
    for key in ("properties", "requirements"):
        translate = translate_property if key == "properties" else translate_requirement
        out[key] = [p for p in (translate(p) for p in item.get(key) or []) if p]
    english["enchantMods"] = enchants + english["enchantMods"]
    out.update({k: v for k, v in english.items() if v})
    if item.get("sockets"):
        out["sockets"] = item["sockets"]
    sockets = []
    for number, socketed in enumerate(item.get("socketedItems") or []):
        if socketed.get("frameTypeId") == "Gem" or socketed.get("frameType") == 4:
            continue  # skills granted by the item; GetSkills lists them with their supports
        converted = convert_socketable(socketed, report, f"{where}/socket{number}")
        if converted:
            sockets.append(converted)
    if sockets:
        out["socketedItems"] = sockets
    # grantedSkills is not passed on: the same skill is in the implicit lines ("Grants Skill: ..."),
    # which P05 already translates, and PoB would otherwise add it twice.
    report["items"] += 1
    return out


def convert_socketable(item, report, where):
    """Runes, soul cores and talismans: PoB only needs the English base name."""
    name = _clean(item.get("typeLine") or item.get("baseType"))
    records = terms().bases.get((LANG, name)) or []
    if not records:
        # Jewels socketed in an item (Diamond/Emerald/...) are full items.
        if item.get("explicitMods") or item.get("rarity") in ("Magic", "Rare", "Unique"):
            converted = convert_item(item, report, where)
            if converted:
                converted["socket"] = item.get("socket", 0)
            return converted
        report["lines"].append({"where": where, "item": name, "field": "socketedItems", "text": name,
                                "status": "unrecognized", "note": "符文/镶嵌物不在编年史表中"})
        return None
    return {"baseType": records[0]["en"], "typeLine": records[0]["en"], "socket": item.get("socket", 0)}


# Skills --------------------------------------------------------------------------------------

def gem_name(name):
    """Chinese gem/skill name -> English, from the PoE2DB gem tables."""
    name = _clean(name)
    english = terms().skills.get((LANG, name))
    if english is None and name.endswith("（辅助）"):
        english = terms().skills.get((LANG, name[:-4]))
    return english


def convert_gem(gem, report, where):
    english = gem_name(gem.get("typeLine") or gem.get("baseType") or "")
    if english is None:
        report["gems_missing"].append({"where": where, "text": gem.get("typeLine") or gem.get("baseType")})
        return None
    props = []
    for prop in gem.get("properties") or []:
        gem_level = GEM_LEVEL.search(_value(prop.get("values")))
        if gem_level and not _clean(prop.get("name")):
            props.append({"name": "", "values": [[f"{gem_level.group(1)} Levels from Gem", 0]]})
            continue
        translated = translate_property(prop)
        if translated:
            props.append(translated)
    report["gems"] += 1
    out = {"typeLine": english, "baseType": english, "properties": props,
           "support": bool(gem.get("support")), "corrupted": bool(gem.get("corrupted"))}
    if gem.get("socketedItems"):
        out["socketedItems"] = [g for g in (convert_gem(s, report, f"{where}/{n}")
                                            for n, s in enumerate(gem["socketedItems"])) if g]
    return out


# Passive tree --------------------------------------------------------------------------------

GEM_LEVEL = re.compile(r"技能石等级(?:（最大）|\(最大\))?\s*(\d+)")
ATTRIBUTE_EN = {"Str": "Strength", "Dex": "Dexterity", "Int": "Intelligence"}


BOSS_FACES = re.compile(r"^(\d+)\s*个毁面首领$")  # PoB reads "# broken boss faces"


def convert_quest_stats(lines, report):
    """Quest rewards ("+100 精魂") -> English stat lines for PoB's ImportQuestRewardConfig."""
    out = []
    for line in lines or []:
        text = _clean(line)
        faces = BOSS_FACES.match(text)
        english = f"{faces.group(1)} Broken Boss Faces" if faces else match_line(text, [], LANG, {})[0]
        if english:
            out.append(english)
        else:
            report["lines"].append({"where": "quest", "item": "", "field": "quest_stats", "text": text,
                                    "status": "unrecognized", "note": "任务奖励行无对应模板"})
    return out


def convert_tree(tree, report):
    overrides = {}
    for node, info in (tree.get("skill_overrides") or {}).items():
        short = ATTRIBUTES.get(_clean((info or {}).get("name", "")))
        if short:
            overrides[str(node)] = {**info, "name": ATTRIBUTE_EN[short]}
    return {
        "hashes": [int(h) for h in tree.get("hashes") or []],
        "specialisations": {k: [int(h) for h in v or []] for k, v in (tree.get("specialisations") or {}).items()},
        "skill_overrides": overrides,
        "jewel_data": tree.get("jewel_data") or {},
        "mastery_effects": tree.get("mastery_effects") or {},
        "alternate_ascendancy": tree.get("alternate_ascendancy"),
        "quest_stats": convert_quest_stats(tree.get("quest_stats"), report),
    }


def _jewel_item(entry):
    """GetJewels entry -> item in the equipment layout. The share page reads `jewel.name` (base),
    `display_name`, `rarity` (0-3) and the lines in `mod_descriptions[].values[0]`."""
    jewel = entry["jewel"]
    if jewel.get("typeLine"):
        return jewel
    lines = []
    for mod in jewel.get("mod_descriptions") or []:
        values = mod.get("values") or []
        if values and values[0]:
            lines.extend(line for line in str(values[0]).split("\n") if line.strip())
    rarity = {0: "Normal", 1: "Magic", 2: "Rare", 3: "Unique"}.get(jewel.get("rarity") or 0, "Normal")
    return {"id": jewel.get("id") or f"jewel-{entry.get('socket_id')}", "rarity": rarity, "typeLine": jewel.get("name"),
            "name": jewel.get("display_name") if rarity in ("Rare", "Unique") else "", "explicitMods": lines,
            "ilvl": jewel.get("ilvl") or jewel.get("level") or 0}


# talent_tree.jewel_data[x].radius is in game units: PoB's radius (Data.lua jewelRadii "outer") times
# PassiveTreeJewelDistanceMultiplier (1.2, Data/Misc.lua). PoB reads the jewel's radius only from a
# "Radius" property; a radius jewel without one (From Nothing) stops PoB in PassiveSpec.
JEWEL_RADII = {round(outer * 1.2): label for outer, label in
               ((1000, "Small"), (1150, "Medium"), (1300, "Large"), (1500, "Very Large"))}


def jewel_radius(tree, x, report, where):
    """'Radius' property for the jewel in tree slot x, or None when the slot has no radius."""
    radius = ((tree.get("jewel_data") or {}).get(str(x)) or {}).get("radius")
    if radius is None:
        return None
    label = JEWEL_RADII.get(int(radius))
    if label is None:
        report["lines"].append({"where": where, "item": "", "field": "radius", "text": str(radius),
                                "status": "unrecognized", "note": "珠宝半径不在 PoB 半径表中"})
        return None
    return {"displayMode": 0, "name": "Radius", "values": [[label, 0]]}


def _jewel_entries(answer):
    data = answer.get("jewel_data") or []
    if isinstance(data, str):
        data = json.loads(data)
    if isinstance(data, dict):
        data = list(data.values())
    return [d for d in data if isinstance(d, dict) and d.get("jewel")]


# Whole character -----------------------------------------------------------------------------

def convert(bundle):
    for key, method in (("role_info", "GetRoleInfo"), ("equipments", "GetEquipments"),
                        ("talent_tree", "GetTalentTree")):
        check(bundle.get(key), method)
    role = bundle["role_info"]["role"]
    report = {"items": 0, "items_skipped": [], "lines": [], "dropped": [], "names": 0, "gems": 0,
              "gems_missing": [], "jewels": 0}
    equipment = []
    for number, item in enumerate(bundle["equipments"].get("equipments") or []):
        converted = convert_item(item, report, f"{item.get('inventoryId')}#{number}")
        if converted:
            equipment.append(converted)
    tree = convert_tree(bundle["talent_tree"].get("talent_tree") or {}, report)
    jewels = []
    if (bundle.get("jewels") or {}).get("result", {}).get("error_code") == 0:
        for entry in _jewel_entries(bundle["jewels"]):
            jewel = _jewel_item(entry)
            converted = convert_item(jewel, report, f"jewel@{entry.get('socket_id')}")
            if converted:
                converted["inventoryId"] = "PassiveJewels"
                # "PassiveJewel_11": index 11 into the tree's jewel slots, the same key as
                # talent_tree.jewel_data (the character API's `x`).
                socket = re.fullmatch(r"PassiveJewel_(\d+)", str(entry.get("socket_id") or ""))
                if socket:
                    converted["x"] = int(socket.group(1))
                    radius = jewel_radius(bundle["talent_tree"].get("talent_tree") or {}, converted["x"], report,
                                          f"jewel@{entry.get('socket_id')}")
                    if radius and not any(p.get("name") == "Radius" for p in converted["properties"]):
                        converted["properties"].append(radius)
                elif str(entry.get("socket_id") or "").isdigit():
                    converted["socketNodeId"] = int(entry["socket_id"])
                jewels.append(converted)
                report["jewels"] += 1
    skills = []
    if (bundle.get("skills") or {}).get("result", {}).get("error_code") == 0:
        answer = bundle["skills"]
        for number, skill in enumerate(answer.get("skills") or answer.get("gemSkill") or []):
            converted = convert_gem(skill, report, f"skill{number}")
            if converted:
                skills.append(converted)
    character = {
        "name": "WeGame", "class": role.get("class_name"), "level": int(role.get("level") or 1),
        "league": "国服", "equipment": equipment, "jewels": jewels, "skills": skills, "passives": tree,
    }
    report["equipment"] = len(equipment)
    report["lines_unconverted"] = len(report["lines"])
    return {"character": character, "report": report}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("fetch", "convert", "anonymise"):
        cmd = sub.add_parser(name)
        cmd.add_argument("input")
        cmd.add_argument("--out")
    args = parser.parse_args(argv)
    try:
        if args.command == "fetch":
            result = fetch(args.input)
        else:
            bundle = json.loads(Path(args.input).read_text(encoding="utf-8"))
            result = convert(bundle) if args.command == "convert" else anonymise(bundle)
    except (ValueError, RuntimeError, OSError) as error:
        result = {"error": str(error)}
    text = json.dumps(result, ensure_ascii=False, indent=1)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text + "\n")
    return 1 if "error" in result else 0


if __name__ == "__main__":
    sys.exit(main())
