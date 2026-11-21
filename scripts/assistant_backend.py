#!/usr/bin/env python3
"""Assistant shell backend: assistant-shell/1 over stdio (sources/assistant-shell.md).

evaluate-item parses the copied item (P05, any client language) into PoB English
and evaluates it against the build open in PoB with the resident engine (P02).
"""

import argparse
import json
import os
from pathlib import Path
import sys
import threading
import time
import traceback

from item_text import PLACEHOLDER, parse_item, terms
import pob_command
from pob_server import LuaEngine, TrialServer
import tencent_trade
from web_preview import WebPreview

PROTOCOL = "assistant-shell/1"
LANGUAGE = {"cmn-Hans": "zh_hans", "cmn-Hant": "zh_hant", "en": "en"}

SLOT_LABELS = {"Weapon 1": "武器 1", "Weapon 2": "武器 2", "Weapon 1 Swap": "副武器组 1", "Weapon 2 Swap": "副武器组 2",
               "Helmet": "头部", "Body Armour": "胸甲", "Gloves": "手套", "Boots": "鞋子", "Amulet": "项链",
               "Ring 1": "戒指 1", "Ring 2": "戒指 2", "Ring 3": "戒指 3", "Belt": "腰带",
               "Charm 1": "护符 1", "Charm 2": "护符 2", "Charm 3": "护符 3", "Flask 1": "药剂 1", "Flask 2": "药剂 2"}
RESISTS = (("Fire", "火焰抗性", "火抗"), ("Cold", "冰霜抗性", "冰抗"),
           ("Lightning", "闪电抗性", "电抗"), ("Chaos", "混沌抗性", "混抗"))
ATTRIBUTES = (("Str", "力量"), ("Dex", "敏捷"), ("Int", "智慧"))
# Engine refusals the user can act on, keyed by the pob_server.lua assertion text.
ENGINE_REFUSALS = {
    "unrecognized item base": ("not-equippable", "这件物品不能装备，或 PoB 不认识它的基底，无法评估"),
    "no active slot accepts this item": ("no-slot", "当前 BD 没有能放这件装备的槽位，无法评估"),
}
WARM_INTERVAL = 5  # seconds between checks for the build PoB has open
# Changes the summary may mention after DPS, in this order.
SUMMARY_METRICS = (("TotalEHP", "有效生命"), ("Life", "生命"), ("EnergyShield", "能量护盾"), ("Mana", "魔力"),
                   *((f"{key}Resist", short) for key, _, short in RESISTS))


def local_name(kind, key, language):
    """Client-language name from the PoE2DB tables; English when the table lacks it."""
    if key is None:
        return None
    record = terms().names[kind].get(key)
    return record[language] if record and record.get(language) else (record["en"] if record else key)


def number(value):
    return f"{value:+.0f}" if abs(value) >= 1 or value == 0 else f"{value:+.1f}"


def slot_labels(slots):
    jewels = 0
    labels = {}
    for slot in slots:
        name = slot["slot"]
        if name.startswith("Jewel"):
            jewels += 1
            labels[name] = f"珠宝槽 {jewels}"
        else:
            labels[name] = SLOT_LABELS.get(name, name)
    return labels


def dps_change(baseline, after):
    absolute = after - baseline
    return {"before": baseline, "after": after, "absolute": absolute,
            "percent": round(absolute / baseline * 100, 1) if baseline else None}


def summarize(label, replaced, change, delta, gaps):
    """One line such as 比当前武器 1 弱：DPS -97.8%，魔力 +114."""
    shown = change["percent"] if change["percent"] is not None else change["absolute"]
    if round(shown, 1):
        verdict = "强" if shown > 0 else "弱"
        dps = f"DPS {shown:+.1f}%" if change["percent"] is not None else f"DPS {number(shown)}"
    else:  # Float noise or a non-damaging skill: judge by EHP.
        ehp = delta.get("TotalEHP", 0)
        verdict = "强" if ehp >= 0.5 else "弱" if ehp <= -0.5 else None
        dps = "DPS 不变"
    parts = [dps] + [f"{name} {number(delta[key])}" for key, name in SUMMARY_METRICS if round(delta.get(key, 0))][:2]
    # Only gaps this swap opens or widens; the build's existing gaps are shown per slot.
    wider = [f"{name} +{gap['after'] - gap['before']:.0f}" for key, name in ATTRIBUTES
             for gap in [gaps[key]] if gap["after"] > gap["before"]]
    if wider:
        parts.append("属性缺口 " + "、".join(wider))
    target = ("当前" if replaced else "空的") + label
    head = f"比{target}{' ' if label[-1].isdigit() else ''}{verdict}" if verdict else f"与{target}相当"
    return f"{head}：{'，'.join(parts)}"


def overlay(result, language):
    """Derived values the overlay renders as is (sources/assistant-shell.md)."""
    baseline = result["baseline"]
    slots = result["slots"] or []
    labels = slot_labels(slots)
    for slot in slots:
        after = slot["metrics"]
        slot["label"] = labels[slot["slot"]]
        for other in slot["displaced"]:
            other["label"] = SLOT_LABELS.get(other["slot"], other["slot"])
        slot["dps"] = dps_change(baseline["DPS"], after["DPS"])
        slot["resists"] = {key: {"label": label, "before": baseline["resists"][key]["value"],
                                 "change": after["resists"][key]["value"] - baseline["resists"][key]["value"],
                                 **after["resists"][key]} for key, label, _ in RESISTS}
        slot["attribute_gaps"] = {key: {"label": label, "required": after["attributes"][key]["required"],
                                        "before": baseline["attributes"][key]["gap"],
                                        "after": after["attributes"][key]["gap"]} for key, label in ATTRIBUTES}
        slot["summary"] = summarize(slot["label"], slot["replaced"], slot["dps"], slot["delta"], slot["attribute_gaps"])
    # Largest DPS gain; ties (e.g. a ring with no damage) go to the larger EHP gain, then slot order.
    best = max(enumerate(slots), key=lambda pair: (pair[1]["delta"]["DPS"], pair[1]["delta"]["TotalEHP"], -pair[0]),
               default=None)
    result["default_slot"] = best[1]["slot"] if best else None
    skill = result.get("skill")
    if skill:
        skill["main_skill_name"] = local_name("skill", skill.get("main_skill"), language)
        skill["minion_skill_name"] = local_name("skill", skill.get("minion_skill"), language)
    return result


class BackendError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def parse_params(params):
    text = params.get("item_text")
    if not isinstance(text, str) or not text.strip():
        raise BackendError("bad-request", "没有收到装备文本")
    language = LANGUAGE.get((params.get("game") or {}).get("language"))
    try:
        return parse_item(text, language)
    except ValueError as error:
        raise BackendError("parse-failed", f"装备解析失败：{error}") from error


def pob_item_text(parsed):
    """P05's English text, with a rare item's in-game name in place of the placeholder (U06)."""
    name = next((line for line in parsed["lines"] if line["kind"] == "name"), None)
    lines = parsed["text"].split("\n")
    if parsed["rarity"] == "Rare" and name and name["status"] == "placeholder" and "Rarity: Rare" in lines:
        index = lines.index("Rarity: Rare") + 1
        if lines[index] == PLACEHOLDER["Rare"]:
            lines[index] = name["text"]
    return "\n".join(lines)


def trade_names(parsed):
    """[English, client text] for the unique and base names: the Tencent trade site
    searches names in Simplified Chinese (stat ids are shared)."""
    pairs = [[line["english"], line["text"]] for line in parsed["lines"]
             if line["kind"] == "name" and line["status"] == "matched" and line["english"] != line["text"]]
    base_name = local_name("base", parsed["base"], parsed["language"])
    if parsed["base"] and base_name and base_name != parsed["base"] and parsed["base"] not in (en for en, _ in pairs):
        pairs.append([parsed["base"], base_name])
    return pairs


class Backend:
    def __init__(self, engine_dir, build=None, pob_user_dir=None, engine_factory=LuaEngine):
        self.engine_dir = engine_dir
        self.build = build
        self.pob_user_dir = pob_user_dir
        self.engine_factory = engine_factory
        self.server = None
        self.engine_error = None
        self.lock = threading.Lock()  # one Lua state: requests and warm-up take turns
        self.warm_error = None
        self.web_preview = WebPreview(self)  # M09a: trade-site extension endpoint

    def start(self):
        """Load term tables and start the engine once; engine failures are reported per request."""
        terms()
        try:
            self.server = TrialServer(self.engine_factory(self.engine_dir), self.build, self.pob_user_dir)
        except (OSError, ValueError, RuntimeError) as error:
            self.engine_error = str(error)

    def evaluate_item(self, params):
        started = time.perf_counter()
        parsed = parse_params(params)
        item = {key: parsed[key] for key in ("language", "rarity", "item_class", "base", "unique")}
        names = [line["text"] for line in parsed["lines"] if line["kind"] == "name"]
        item["name"] = names[0] if names else None
        item["base_name"] = local_name("base", parsed["base"], parsed["language"])
        item["unique_name"] = local_name("unique", parsed["unique"], parsed["language"])
        item["unrecognized"] = parsed["unrecognized"]
        item["pob_text"] = parsed["text"]
        item["price"] = parsed["price"]
        if parsed["rarity"] is None and parsed["base"] is None:  # currency, gems and other non-gear
            raise BackendError("not-equippable", "这件物品不能装备，无法评估")
        parse_ms = round((time.perf_counter() - started) * 1000, 1)
        if self.server is None:
            raise BackendError("engine-unavailable", f"PoB 引擎未启动：{self.engine_error}")
        try:
            with self.lock:
                trial = self.server.handle({"cmd": "evaluate", "item_text": parsed["text"]})
        except (OSError, ValueError, RuntimeError) as error:
            for reason, (code, message) in ENGINE_REFUSALS.items():
                if str(error).endswith(reason):
                    raise BackendError(code, message) from error
            raise BackendError("evaluate-failed", f"试算失败：{error}") from error
        return overlay({"item": item, "build": trial.get("build"), "skill": trial.get("skill"),
                        "baseline": trial.get("baseline"),
                        "slots": trial.get("slots"), "reloaded": trial.get("reloaded"),
                        "timing_ms": {"parse": parse_ms, "evaluate": trial.get("elapsed_ms")}},
                       parsed["language"])

    def add_to_pob(self, params):
        """Add the item to the item list of the build open in PoB (not equipped, not saved)."""
        parsed = parse_params(params)
        names = [line["text"] for line in parsed["lines"] if line["kind"] == "name"]
        name = names[0] if names else (local_name("base", parsed["base"], parsed["language"]) or "装备")
        if parsed["rarity"] is None and parsed["base"] is None:
            raise BackendError("not-equippable", "这件物品不能装备，无法加入 PoB")
        try:
            snapshot = pob_command.find_pob(self.pob_user_dir)
            result = pob_command.send(snapshot, {"command": "add-item", "item_text": pob_item_text(parsed)})
        except pob_command.CommandError as error:
            raise BackendError(error.code, str(error)) from error
        status = result.get("status")
        if status == "added":
            message = f"已加入 PoB：{name}"
        elif status == "exists":
            message = f"已存在：{name}"
        else:
            raise BackendError(result.get("code") or "pob-error", result.get("message") or "PoB 没能加入这件装备")
        return {"status": status, "name": name, "message": message, "pob_pid": snapshot["pid"],
                "item_id": result.get("itemId"), "unrecognized": parsed["unrecognized"]}

    def configure_web_preview(self, params):
        """M09a: on/off, port and exchange rates for the trade-site extension (sources/web-preview.md)."""
        try:
            return self.web_preview.configure(params)
        except ValueError as error:
            raise BackendError("bad-request", str(error)) from error

    def trade_preview(self, params):
        """M09b: evaluation for one result row of the assistant's trade window (sources/web-preview.md)."""
        try:
            return self.web_preview.trade_window(params)
        except ValueError as error:
            raise BackendError("bad-request", "请求格式不对") from error

    def translate_item(self, params):
        """P05's English game text for EE2's own parser (Tencent price check, M02); no engine involved."""
        parsed = parse_params(params)
        names = [line["text"] for line in parsed["lines"] if line["kind"] == "name"]
        return {"text": pob_item_text(parsed), "language": parsed["language"],
                "name": names[0] if names else None,
                "base_name": local_name("base", parsed["base"], parsed["language"]),
                "unique_name": local_name("unique", parsed["unique"], parsed["language"]),
                "names": trade_names(parsed),
                "unrecognized": parsed["unrecognized"]}

    def translate_trade_query(self, params):
        """M04: English item names in a Trader search body -> the Simplified Chinese the Tencent site wants."""
        try:
            body, names, missing = tencent_trade.translate_query(params.get("body"))
        except ValueError as error:
            raise BackendError("bad-request", str(error)) from error
        return {"body": body, "names": names, "missing": missing}

    def translate_trade_items(self, params):
        """M04: Tencent fetch answer (Chinese items) -> English items PoB's Trader reads."""
        result = params.get("result")
        if not isinstance(result, list):
            raise BackendError("bad-request", "没有收到市集取回结果")
        return tencent_trade.translate_items(result)

    def warm(self):
        """Load the build PoB has open now, so the next evaluation does not wait for it."""
        if self.server is None:
            return
        try:
            with self.lock:
                if self.server.ensure_loaded():
                    summary = self.server.loaded[1]
                    print(f"已预载 BD（{summary['source']}）：{summary['path'] or summary.get('build_name')}",
                          file=sys.stderr, flush=True)
            self.warm_error = None
        except (OSError, ValueError, RuntimeError) as error:
            if str(error) != self.warm_error:  # log once per distinct cause, not every poll
                print(f"预载 BD 跳过：{error}", file=sys.stderr, flush=True)
            self.warm_error = str(error)

    def keep_warm(self, interval=WARM_INTERVAL):
        while True:
            self.warm()
            time.sleep(interval)

    def handle(self, request):
        if request.get("protocol") != PROTOCOL:
            return {"error": {"code": "bad-protocol", "message": f"需要 {PROTOCOL}"}}
        methods = {"evaluate-item": self.evaluate_item, "add-to-pob": self.add_to_pob,
                   "web-preview": self.configure_web_preview, "trade-preview": self.trade_preview,
                   "translate-item": self.translate_item,
                   "translate-trade-query": self.translate_trade_query,
                   "translate-trade-items": self.translate_trade_items}
        method = methods.get(request.get("method"))
        if method is None:
            return {"error": {"code": "unknown-method", "message": f"未知方法 {request.get('method')}"}}
        try:
            return {"result": method(request.get("params") or {})}
        except BackendError as error:
            return {"error": {"code": error.code, "message": str(error)}}
        except Exception as error:  # keep serving; the overlay must always get an answer
            traceback.print_exc(file=sys.stderr)
            return {"error": {"code": "internal", "message": f"后端内部错误：{type(error).__name__}: {error}"}}

    def serve(self, lines, out):
        for line in lines:
            if not line.strip():
                continue
            try:
                request = json.loads(line)
                if not isinstance(request, dict):
                    raise ValueError
            except ValueError:
                reply = {"id": None, "error": {"code": "bad-json", "message": "请求不是 JSON 对象"}}
            else:
                reply = {"id": request.get("id"), **self.handle(request)}
            out.write(json.dumps(reply, ensure_ascii=False, allow_nan=False) + "\n")
            out.flush()


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--engine", required=True, type=Path, help="固定 PoB 引擎根目录（含 src、runtime）")
    parser.add_argument("--build", type=Path, help="固定 BD；省略时跟随 PoB 当前打开的 BD")
    parser.add_argument("--pob-user-dir", type=Path, help="含 Settings.xml 的 PoB 用户目录")
    args = parser.parse_args()
    # Protocol lines go to a private copy of stdout; engine prints land on stderr.
    out = os.fdopen(os.dup(1), "w", encoding="utf-8", newline="\n")
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    backend = Backend(args.engine.resolve(), args.build.resolve() if args.build else None,
                      args.pob_user_dir.resolve() if args.pob_user_dir else None)
    backend.start()
    threading.Thread(target=backend.keep_warm, daemon=True).start()
    stdin = open(sys.stdin.fileno(), encoding="utf-8", closefd=False)
    backend.serve(stdin, out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
