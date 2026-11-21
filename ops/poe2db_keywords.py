"""PoE2DB (编年史) names for buffs and states PoB's interface text names in English.

  python3 -B ops/poe2db_keywords.py [--fetch] [--cache ~/.local/state/poe2-assistant/poe2db-cache]
      [--out data/terms/poe2db-1.0/names/keywords.json] [--report report.md]

Order for every name in NAMES (buffs, debuffs, grounds and states named in PoB's Config tab text):
  1. the Keywords pages (`/us|cn|tw/Keywords`: `<a href="Onslaught" ...>猛攻</a>`),
  2. the PoE2DB tables the project already has (data/terms/poe2db-1.0, PoB poe2-assistant/terms),
  3. the name's own page (`/us|cn/<Name_With_Underscores>`, cn title "猛攻 - 流亡2编年史").
Pages come from the shared PoE2DB fetcher (scripts/poe2db_fetch.py): the cache only, or with --fetch
missing ones are fetched 4 s apart into the cache and its manifest (404s are recorded there, not retried). Names still missing are
looked up in PoB2-i18n zh_CN / zh_TW and PoeCharm for the report only - never used automatically.
"""
import argparse
import json
from pathlib import Path
import re
import sys

import ui_fallback_prep as prep

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import poe2db_fetch  # noqa: E402

STATE = Path.home() / ".local/state/poe2-assistant"
DEFAULT_CACHE = STATE / "poe2db-cache"
TERMS = ROOT / "data/terms/poe2db-1.0"
DEFAULT_OUT = TERMS / "names/keywords.json"
LINK = re.compile(r'<a href="([^"]+)" class="strong fontinSmallCaps">([^<]+)</a>')
TITLE = re.compile(r"<title>([^<]*?) - ")

# Buff, debuff, ground and state names PoB's Config tab and breakdown text keep in English.
NAMES = [
    "Adrenaline", "Alchemist's Genius", "Arcane Surge", "Chaotic Might", "Divinity", "Elusive",
    "Everlasting Sacrifice", "Fanaticism", "Onslaught", "Parry", "Quicksand Hourglass", "Unholy Might",
    "Brittle", "Sap", "Intimidate", "Critical Weakness", "Maim", "Withered", "Corrosion", "Crushed",
    "Covered in Ash", "Covered in Frost", "Profane Ground", "Consecrated Ground", "Fungal Ground",
    "Rampage", "Soul Eater", "Tailwind", "Rage", "Combo", "Faerie Fire", "Rupture", "Glorious Madness",
    "Steel Ward", "Slipstream", "Unravelling", "Fortification", "Blind", "Immobilised", "Pinned",
    "Heavy Stun", "Heavy Stunned", "Electrocute", "Electrocuted", "Freeze", "Frozen", "Maimed", "Valour",
    "Runic Ward", "Daze", "Hinder", "Exposure",
]
# Word forms PoB uses for a keyword PoE2DB lists under its base form (same Chinese name).
FORMS = {"Heavy Stunned": "Heavy Stun", "Electrocuted": "Electrocute", "Maimed": "Maim"}


def fetch(fetcher, lang, page):
    try:
        return fetcher.page(lang, page)
    except poe2db_fetch.FetchError:
        return None


def keyword_links(text):
    return {href: name.strip() for href, name in LINK.findall(text or "")}


def build(cache, terms, fetch_pages=False, i18n=None, poecharm=None):
    fetcher = poe2db_fetch.Fetcher(cache, offline=not fetch_pages)
    pages = {lang: keyword_links(fetch(fetcher, lang, "Keywords")) for lang in ("us", "cn", "tw")}
    keywords = {}
    for href, en in pages["us"].items():
        cn = pages["cn"].get(href)
        if cn and re.search(r"[一-鿿]", cn):
            keywords[en] = {"zh_hans": cn, "zh_hant": pages["tw"].get(href), "page": href}
    names, missing = {}, []
    by_lower = {k.lower(): (k, v) for k, v in keywords.items()}
    for name in NAMES:
        base = FORMS.get(name)
        if base in names:  # NAMES lists the base form first
            names[name] = {"zh_hans": names[base]["zh_hans"], "source": f"{names[base]['source']} ({base})"}
            continue
        if name.lower() in by_lower:
            names[name] = {"zh_hans": by_lower[name.lower()][1]["zh_hans"], "source": "Keywords"}
            continue
        if name.lower() in terms:
            names[name] = {"zh_hans": terms[name.lower()], "source": "poe2db tables"}
            continue
        page = name.replace(" ", "_").replace("'", "%27")
        us = fetch(fetcher, "us", page)
        cn = fetch(fetcher, "cn", page) if us else None
        title = TITLE.search(cn or "")
        if title and re.search(r"[一-鿿]", title.group(1)):
            names[name] = {"zh_hans": title.group(1).strip(), "source": f"page {page}"}
        else:
            gone = fetcher.is_missing(poe2db_fetch.page_url("us", page))
            why = "no Chinese title" if us else ("404" if gone else "not cached")
            entry = {"name": name, "page": page, "why": why}
            entry.update({"zh_CN": (i18n or {}).get("i18n-zh_CN", {}).get(name),
                          "zh_TW": (i18n or {}).get("i18n-zh_TW", {}).get(name),
                          "poecharm": (poecharm or {}).get(name)})
            missing.append(entry)
    return {"metadata": {"version": "poe2db-1.0", "source": "poe2db-cache Keywords and name pages",
                         "script": "ops/poe2db_keywords.py"},
            "keywords": keywords, "names": names, "missing": missing}, [f"{url} {status}" for url, status in fetcher.fetched]


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--fetch", action="store_true", help="fetch missing pages (4 s apart)")
    parser.add_argument("--terms", type=Path, default=TERMS, help="our PoE2DB tables (names/ included)")
    parser.add_argument("--pob-terms", type=Path, help="PoB poe2-assistant/terms (P03 tables)")
    args = parser.parse_args()
    dirs = [args.terms] + ([args.pob_terms] if args.pob_terms else [])
    terms = prep.game_terms(*[d for d in dirs if d.exists()])
    i18n = prep.i18n_tables(STATE / "i18n/PathOfBuilding-PoE2-i18n-portable.zip")
    poecharm = prep.poecharm_table(args.cache / "poecharm/zh-rCN")
    result, fetched = build(args.cache, terms, args.fetch, i18n, poecharm)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"keywords": len(result["keywords"]), "names": len(result["names"]),
                      "missing": [m["name"] for m in result["missing"]], "fetched": fetched}, ensure_ascii=False))


if __name__ == "__main__":
    main()
