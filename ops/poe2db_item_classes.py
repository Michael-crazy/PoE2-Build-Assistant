"""PoE2DB (编年史) item class names from the cached page titles, for PoB's item type names.

  python3 -B ops/poe2db_item_classes.py [--cache ~/.local/state/poe2-assistant/poe2db-cache]
      [--out data/terms/poe2db-1.0/names/item_classes.json]

Reads the class pages (us/cn/tw) through the shared PoE2DB fetcher (scripts/poe2db_fetch.py) offline:
only the cache, nothing is fetched (`poe2db_fetch.py pages <Class>` fills it). The class name is the page title before " - " (cn: "战弩 - 流亡2编年史, ..."). When the cn page
has no Chinese title (it shows the page id, e.g. "Body_Armours") the tw title is converted to Simplified
with OpenCC (`pip install opencc-python-reimplemented`) and marked `source: tw`. PoB's type names
(`type` and `type: subType` in Data/Bases) are mapped to pages in POB_PAGES; types with no page are listed
under `missing` and get no name (never translated by hand).
"""
import argparse
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import poe2db_fetch  # noqa: E402

DEFAULT_CACHE = Path.home() / ".local/state/poe2-assistant/poe2db-cache"
DEFAULT_OUT = ROOT / "data/terms/poe2db-1.0/names/item_classes.json"
TITLE = re.compile(r"<title>([^<]*?) - ")

# PoB item type (Data/Bases `type`, or `type: subType` where the subtype is its own class) -> page.
POB_PAGES = {
    "Amulet": "Amulets", "Belt": "Belts", "Body Armour": "Body_Armours", "Boots": "Boots", "Bow": "Bows",
    "Buckler": "Bucklers", "Charm": "Charms", "Claw": "Claws", "Crossbow": "Crossbows", "Dagger": "Daggers",
    "Flail": "Flails", "Flask: Life": "Life_Flasks", "Flask: Mana": "Mana_Flasks", "Focus": "Foci",
    "Gloves": "Gloves", "Helmet": "Helmets", "Jewel": "Jewels", "Jewel: Timeless": "Timeless_Jewel",
    "One Hand Axe": "One_Hand_Axes", "One Hand Mace": "One_Hand_Maces", "One Hand Sword": "One_Hand_Swords",
    "Quarterstaff": "Quarterstaves", "Staff: Warstaff": "Quarterstaves", "Quiver": "Quivers", "Ring": "Rings",
    "Sceptre": "Sceptres", "Shield": "Shields", "Spear": "Spears", "Staff": "Staves", "Talisman": "Talismans",
    "TrapTool": "Traps", "Two Hand Axe": "Two_Hand_Axes", "Two Hand Mace": "Two_Hand_Maces",
    "Two Hand Sword": "Two_Hand_Swords", "Wand": "Wands",
    # PoB types without a class page in the cache.
    "Fishing Rod": None, "Jewel: Radius": None, "Transcendent Limb": None,
    "Transcendent Limb: Transcendent Arm": None, "Transcendent Limb: Transcendent Leg": None,
}


def title(text):
    m = TITLE.search((text or "")[:4000])
    return m.group(1).strip() if m else None


def has_cjk(text):
    return bool(text) and re.search(r"[一-鿿]", text) is not None


def page_names(cache, page, to_simplified):
    fetcher = poe2db_fetch.Fetcher(cache, offline=True)
    us, cn, tw = (title(fetcher.page(lang, page)) for lang in ("us", "cn", "tw"))
    if has_cjk(cn):
        return {"en": us, "zh_hans": cn, "zh_hant": tw if has_cjk(tw) else None, "source": "cn"}
    if has_cjk(tw):
        return {"en": us, "zh_hans": to_simplified(tw), "zh_hant": tw, "source": "tw"}
    return None


def build(cache, to_simplified):
    pages = sorted({p for p in POB_PAGES.values() if p})
    names, missing = {}, []
    for page in pages:
        found = page_names(cache, page, to_simplified)
        if found:
            names[page] = found
        else:
            missing.append({"page": page, "why": "no Chinese title in the cn/tw cache"})
    pob = {}
    for pob_type, page in sorted(POB_PAGES.items()):
        if page and page in names:
            pob[pob_type] = dict(names[page], page=page)
        else:
            missing.append({"pob": pob_type, "page": page, "why": "no class page" if not page else "page has no name"})
    return {"metadata": {"version": "poe2db-1.0", "source": "poe2db-cache page titles (us/cn/tw)",
                         "script": "ops/poe2db_item_classes.py"},
            "pages": names, "pob": pob, "missing": missing}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    import opencc
    result = build(args.cache, opencc.OpenCC("t2s").convert)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"pages": len(result["pages"]), "pob": len(result["pob"]), "missing": result["missing"]},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
