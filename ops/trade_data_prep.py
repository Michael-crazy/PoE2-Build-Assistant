"""M02/M03/M08b preprocessing: join the Tencent and international trade data by id.

Inputs are the public trade2 data files, fetched without login (2026-11-21):
  https://poe.game.qq.com/api/trade2/data/{leagues,stats,static}     (Tencent, Simplified)
  https://www.pathofexile.com/api/trade2/data/{stats,static}         (international, English)
Outputs in <out>:
  stats.json     {stat id: {"en", "zh", "type"}}: Simplified mod conditions for the price-check window (M02/M03)
  currency.json  [{"id", "en", "zh", "image"}] for the exchange categories: overlay price buttons (M08b)
  leagues.json   Tencent league ids, which are Chinese (M02)
  report.txt     counts and ids found on one server only
"""
import argparse
import json
from pathlib import Path

CURRENCY_GROUPS = ("Currency",)


def load(folder, name):
    return json.loads((folder / f"{name}.json").read_text(encoding="utf-8"))["result"]


def stat_entries(groups):
    return {entry["id"]: {"text": entry["text"], "type": entry.get("type", group["id"])}
            for group in groups for entry in group["entries"]}


def static_entries(groups, wanted):
    return {entry["id"]: entry for group in groups if group["id"] in wanted for entry in group["entries"]}


def build(tencent, intl):
    zh_stats, en_stats = stat_entries(load(tencent, "stats")), stat_entries(load(intl, "stats"))
    stats = {sid: {"en": en_stats[sid]["text"], "zh": zh["text"], "type": zh["type"]}
             for sid, zh in sorted(zh_stats.items()) if sid in en_stats}
    zh_static = static_entries(load(tencent, "static"), CURRENCY_GROUPS)
    en_static = static_entries(load(intl, "static"), CURRENCY_GROUPS)
    currency = [{"id": cid, "en": en_static[cid]["text"], "zh": zh["text"], "image": zh.get("image")}
                for cid, zh in zh_static.items() if cid in en_static]
    leagues = [league["id"] for league in load(tencent, "leagues")]
    only = {"stats_tencent_only": sorted(set(zh_stats) - set(en_stats)),
            "stats_intl_only": sorted(set(en_stats) - set(zh_stats)),
            "currency_tencent_only": sorted(set(zh_static) - set(en_static)),
            "currency_intl_only": sorted(set(en_static) - set(zh_static))}
    return stats, currency, leagues, only


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tencent", type=Path, required=True, help="folder with Tencent leagues/stats/static .json")
    parser.add_argument("--intl", type=Path, required=True, help="folder with international stats/static .json")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    stats, currency, leagues, only = build(args.tencent, args.intl)
    args.out.mkdir(parents=True, exist_ok=True)
    dump = lambda name, value: (args.out / name).write_text(json.dumps(value, ensure_ascii=False, indent=0) + "\n", encoding="utf-8")
    dump("stats.json", stats)
    dump("currency.json", currency)
    dump("leagues.json", leagues)
    counts = {"stats_joined": len(stats), "currency_joined": len(currency), "leagues": len(leagues),
              **{k: len(v) for k, v in only.items()}}
    lines = [json.dumps(counts, ensure_ascii=False)] + [f"{k}: {' '.join(v[:60])}" for k, v in only.items() if v]
    (args.out / "report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(counts, ensure_ascii=False))


if __name__ == "__main__":
    main()
