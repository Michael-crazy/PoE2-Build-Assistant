"""M04: PoB's Trader on the Tencent trade site (poe.game.qq.com), through the assistant.

The assistant forwards the Trader's requests in its logged-in Electron session (EE2
main/src/PobTrade.ts); this module does the two language steps around them:

- `translate_query`: the Tencent site only accepts Simplified Chinese item names in
  `query.name` / `query.type` (stat ids are shared), so English names become Chinese.
- `translate_items`: a fetch answer's items are in the official item layout with Chinese
  text, the same layout U07 converts (`wegame_import.convert_item`, P05 tables). Each item
  becomes the English item the Trader's own parser reads; items whose base is not in the
  tables are left out and counted, and the pseudo "Sum" line keeps its number.
"""

import re

from item_text import terms
from wegame_import import convert_item

LANG = "zh_hans"
NUMBER = re.compile(r"[-+]?\d+(?:\.\d+)?")
# Item flags the Trader reads that convert_item does not carry over.
FLAGS = ("mirrored", "doubleCorrupted", "sanctified", "identified", "duplicated")
# The Trader reads modifier lines as {"description", "flags"} objects, as the trade API sends them.
MOD_FIELDS = ("enchantMods", "runeMods", "implicitMods", "explicitMods")


def _local(kind, english):
    record = terms().names[kind].get(english)
    return record.get(LANG) if record else None


def translate_query(body):
    """Search body -> (body with Chinese names, [[English, Chinese]...], [names not found])."""
    query = body.get("query") if isinstance(body, dict) else None
    if not isinstance(query, dict):
        raise ValueError("search body has no query")
    names, missing = [], []
    for key, kind in (("name", "unique"), ("type", "base")):
        value = query.get(key)
        holder, field = (value, "option") if isinstance(value, dict) else (query, key)
        english = holder.get(field) if isinstance(holder, dict) else None
        if not isinstance(english, str) or not english:
            continue
        chinese = _local(kind, english) or (key == "type" and _local("unique", english)) or None
        if chinese:
            holder[field] = chinese
            names.append([english, chinese])
        else:
            missing.append(english)
    return body, names, missing


def _sum_line(item):
    for mod in item.get("pseudoMods") or []:
        text = mod if isinstance(mod, str) else (mod or {}).get("description") or ""
        numbers = NUMBER.findall(text)
        if numbers:
            return f"Sum: {numbers[-1]}"
    return None


def translate_items(entries):
    """Fetch answer `result` list -> {"result": [English entries], "report": {...}}."""
    report = {"items": 0, "names": 0, "lines": [], "items_skipped": []}
    out = []
    for number, entry in enumerate(entries):
        item = (entry or {}).get("item") if isinstance(entry, dict) else None
        if not isinstance(item, dict):
            continue
        converted = convert_item(item, report, f"fetch{number}")
        if converted is None:
            continue
        for flag in FLAGS:
            if item.get(flag):
                converted[flag] = item[flag]
        # A value-less first property is the item class ("护甲" reads as "Armour"); the Trader
        # would take it for the armour value.
        converted["properties"] = [p for p in converted["properties"] if p.get("values")]
        for field in MOD_FIELDS:
            if field in converted:
                converted[field] = [m if isinstance(m, dict) else {"description": m} for m in converted[field]]
        line = _sum_line(item)
        if line:
            converted["pseudoMods"] = [line]
        out.append({**entry, "item": converted})
    report["lines_unconverted"] = len(report["lines"])
    return {"result": out, "report": report}
