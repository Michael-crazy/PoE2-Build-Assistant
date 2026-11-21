import io
import json
import os
from pathlib import Path
import unittest

from assistant_backend import Backend, PROTOCOL
from pob_server import LuaEngine

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "tests/fixtures/p05/real/tencent-gloves-advanced.txt"
BUILD = ROOT / "tests/fixtures/p02/real/build.xml"
ENGINE = Path(os.environ.get("POB_ENGINE", "/tmp/poe2-pob-source"))
CURRENCY = "物品类别: 通货\n稀有度: 通货\n崇高石\n--------\n堆叠数量: 1 / 20\n--------\n随机给一件稀有物品添加一条词缀\n"


class FakeServer:
    def __init__(self):
        self.requests = []

    def handle(self, request):
        self.requests.append(request)
        return {"build": {"name": "fake"}, "baseline": {"Life": 1}, "slots": [], "reloaded": False,
                "elapsed_ms": 1.0}


def metrics(dps=0.0, ehp=100.0, mana=50.0, fire=20, fire_total=20, fire_max=75, int_value=0, int_required=0):
    resists = {key: {"value": 0, "max": 75, "total": 0, "overcap": 0} for key in ("Fire", "Cold", "Lightning", "Chaos")}
    resists["Fire"] = {"value": fire, "max": fire_max, "total": fire_total, "overcap": max(0, fire_total - fire_max)}
    attributes = {key: {"value": 0, "required": 0, "gap": 0} for key in ("Str", "Dex")}
    attributes["Int"] = {"value": int_value, "required": int_required, "gap": max(0, int_required - int_value)}
    return {"DPS": dps, "CombinedDPS": dps, "TotalEHP": ehp, "Life": 50.0, "EnergyShield": 0.0, "Mana": mana,
            "FireResist": fire, "ColdResist": 0, "LightningResist": 0, "ChaosResist": 0,
            "resists": resists, "attributes": attributes}


def slot(name, replaced, before, after):
    keys = ("DPS", "CombinedDPS", "TotalEHP", "Life", "EnergyShield", "Mana",
            "FireResist", "ColdResist", "LightningResist", "ChaosResist")
    return {"slot": name, "replaced": replaced, "displaced": [], "metrics": after,
            "delta": {key: after[key] - before[key] for key in keys}}


class TrialServer(FakeServer):
    def __init__(self, baseline, slots):
        super().__init__()
        self.trial = {"build": {"name": "fake"}, "baseline": baseline, "slots": slots, "reloaded": False,
                      "skill": {"dps_source": "player", "main_skill": "Fireball", "minion_skill": None},
                      "elapsed_ms": 1.0}

    def handle(self, request):
        self.requests.append(request)
        return self.trial


def call(backend, params, method="evaluate-item"):
    out = io.StringIO()
    backend.serve([json.dumps({"protocol": PROTOCOL, "id": 3, "method": method, "params": params})], out)
    return json.loads(out.getvalue())


class BackendProtocolTests(unittest.TestCase):
    def setUp(self):
        self.backend = Backend(None)
        self.backend.server = FakeServer()

    def test_parses_tencent_text_and_sends_english_to_engine(self):
        reply = call(self.backend, {"item_text": SAMPLE.read_text(encoding="utf-8"),
                                    "game": {"realm": "pc-tencent", "language": "cmn-Hans"}})
        self.assertEqual(reply["id"], 3)
        result = reply["result"]
        self.assertEqual(result["item"]["language"], "zh_hans")
        sent = self.backend.server.requests[0]["item_text"]
        self.assertIn("to maximum Energy Shield", sent)
        self.assertEqual(sent, result["item"]["pob_text"])
        self.assertIsNone(result["item"]["price"])

    def test_translate_item_returns_english_text_without_the_engine(self):
        backend = Backend(None)  # no engine: price check only needs P05
        result = call(backend, {"item_text": SAMPLE.read_text(encoding="utf-8"),
                                "game": {"realm": "pc-tencent", "language": "cmn-Hans"}}, "translate-item")["result"]
        self.assertEqual(result["language"], "zh_hans")
        self.assertTrue(result["text"].startswith("Item Class: Gloves\nRarity: Rare\n"))
        self.assertIn("to maximum Energy Shield", result["text"])
        self.assertEqual(result["text"].split("\n")[2], result["name"])  # in-game rare name kept
        self.assertIn(["Grim Gloves", "冷酷手套"], result["names"])
        helmet = (ROOT / "tests/fixtures/p05/real/tencent-unique-helmet-runed-waystone-drop.txt").read_text(encoding="utf-8")
        names = call(backend, {"item_text": helmet}, "translate-item")["result"]["names"]
        self.assertEqual(names, [["The Smiling Knight", "笑面骑士"], ["Cowled Helm", "掩面之盔"]])
        self.assertEqual(call(backend, {"item_text": " "}, "translate-item")["error"]["code"], "bad-request")

    def test_market_copy_price_is_returned_and_not_sent(self):
        text = (ROOT / "tests/fixtures/p05/real/intl-zh-hant-market-spear.txt").read_text(encoding="utf-8")
        result = call(self.backend, {"item_text": text, "game": {"realm": "pc-ggg", "language": "cmn-Hant"}})["result"]
        self.assertEqual(result["item"]["price"]["currency_name"], "蛻變石")
        self.assertNotIn("~b/o", self.backend.server.requests[0]["item_text"])

    def test_errors_are_reported_with_codes(self):
        self.assertEqual(call(self.backend, {"item_text": " "})["error"]["code"], "bad-request")
        self.assertEqual(call(self.backend, {}, method="nope")["error"]["code"], "unknown-method")
        broken = Backend(None)
        broken.engine_error = "missing lua51.dll"
        reply = call(broken, {"item_text": SAMPLE.read_text(encoding="utf-8")})
        self.assertEqual(reply["error"]["code"], "engine-unavailable")
        class Exploding(FakeServer):
            def handle(self, request):
                raise KeyError("slot")
        self.backend.server = Exploding()
        reply = call(self.backend, {"item_text": SAMPLE.read_text(encoding="utf-8")})
        self.assertEqual(reply["error"]["code"], "internal")
        out = io.StringIO()
        self.backend.serve(["not json"], out)
        self.assertEqual(json.loads(out.getvalue())["error"]["code"], "bad-json")

    def test_items_that_cannot_be_equipped_get_a_plain_reason(self):
        reply = call(self.backend, {"item_text": CURRENCY, "game": {"language": "cmn-Hans"}})
        self.assertEqual(reply["error"], {"code": "not-equippable", "message": "这件物品不能装备，无法评估"})
        self.assertEqual(self.backend.server.requests, [])

        class Refusing(FakeServer):
            def handle(self, request):
                raise ValueError("E:/backend/scripts/pob_server.lua:158: no active slot accepts this item")
        self.backend.server = Refusing()
        reply = call(self.backend, {"item_text": SAMPLE.read_text(encoding="utf-8")})
        self.assertEqual(reply["error"]["code"], "no-slot")
        self.assertNotIn("pob_server.lua", reply["error"]["message"])

    def test_warm_loads_the_open_build_and_reports_failures_on_stderr(self):
        class Loader:
            loaded = (("cos.xml",), {"source": "settings", "path": "cos.xml"})

            def __init__(self, error=None):
                self.error, self.calls = error, 0

            def ensure_loaded(self):
                self.calls += 1
                if self.error:
                    raise ValueError(self.error)
                return True
        self.backend.server = Loader()
        self.backend.warm()
        self.assertEqual(self.backend.server.calls, 1)
        self.backend.server = Loader("未找到 PoB 当前或最近打开的 BD 文件")
        self.backend.warm()  # must not raise: the next request reports it
        self.assertEqual(self.backend.server.calls, 1)


class OverlayFieldTests(unittest.TestCase):
    def evaluate(self, baseline, slots, text=None, language="cmn-Hans"):
        backend = Backend(None)
        backend.server = TrialServer(baseline, slots)
        reply = call(backend, {"item_text": text or SAMPLE.read_text(encoding="utf-8"),
                               "game": {"language": language}})
        return reply["result"]

    def test_two_ring_slots_pick_largest_dps_gain_and_summarize(self):
        base = metrics(dps=200.0, fire=75, fire_total=90)
        ring1 = metrics(dps=210.0, mana=164.0, fire=75, fire_total=80)
        ring2 = metrics(dps=4.4, mana=164.0, fire=60, fire_total=60, int_required=30)
        result = self.evaluate(base, [slot("Ring 1", "Old A", base, ring1), slot("Ring 2", "Old B", base, ring2)])
        self.assertEqual(result["default_slot"], "Ring 1")
        first, second = result["slots"]
        self.assertEqual([first["label"], second["label"]], ["戒指 1", "戒指 2"])
        self.assertEqual(first["dps"], {"before": 200.0, "after": 210.0, "absolute": 10.0, "percent": 5.0})
        self.assertEqual(second["summary"], "比当前戒指 2 弱：DPS -97.8%，魔力 +114，火抗 -15，属性缺口 智慧 +30")
        self.assertEqual(first["summary"], "比当前戒指 1 强：DPS +5.0%，魔力 +114")
        fire = first["resists"]["Fire"]
        self.assertEqual((fire["value"], fire["max"], fire["overcap"], fire["change"]), (75, 75, 5, 0))
        self.assertEqual(second["attribute_gaps"]["Int"], {"label": "智慧", "required": 30, "before": 0, "after": 30})
        self.assertEqual(result["skill"]["main_skill_name"], "火球")
        self.assertEqual(result["item"]["base_name"], "冷酷手套")
        self.assertEqual(result["item"]["name"], "精魂 护指")
        self.assertIsNone(result["item"]["unique_name"])

    def test_replaced_item_name_in_client_language(self):
        # V10 (#23): rare random name kept, base from PoE2DB; uniques by their PoE2DB name.
        base = metrics(dps=100.0)
        weapon = slot("Weapon 1", "Hate Chant, Chiming Staff", base, metrics(dps=110.0))
        weapon.update(replaced_title="Hate Chant", replaced_base="Chiming Staff", replaced_rarity="RARE")
        weapon["displaced"] = [{"slot": "Weapon 2", "name": "Shavronne's Satchel, Fine Belt",
                                "title": "Shavronne's Satchel", "base": "Fine Belt", "rarity": "UNIQUE"}]
        result = self.evaluate(base, [weapon])
        self.assertEqual(result["slots"][0]["replaced"], "Hate Chant 鸣谐长杖")
        self.assertEqual(result["slots"][0]["displaced"][0]["name"], "薛朗的背包")

    def test_zero_baseline_dps_has_no_percent(self):
        base = metrics(dps=0.0)
        after = metrics(dps=35.5, ehp=90.0)
        weapon = slot("Weapon 1", None, base, after)
        weapon["displaced"] = [{"slot": "Weapon 2", "name": "Old Shield"}]
        result = self.evaluate(base, [weapon])
        self.assertEqual(result["slots"][0]["displaced"], [{"slot": "Weapon 2", "name": "Old Shield", "label": "武器 2"}])
        change = result["slots"][0]["dps"]
        self.assertEqual((change["absolute"], change["percent"]), (35.5, None))
        self.assertEqual(result["slots"][0]["summary"], "比空的武器 1 强：DPS +36，有效生命 -10")
        same = self.evaluate(base, [slot("Gloves", "Old", base, metrics(dps=0.0))])["slots"][0]
        self.assertEqual((same["dps"]["percent"], same["summary"]), (None, "与当前手套相当：DPS 不变"))

    def test_unrecognized_lines_are_kept_with_localized_names(self):
        text = (ROOT / "tests/fixtures/p05/real/tencent-unique-body-armour-advanced.txt").read_text(encoding="utf-8")
        text = text.replace("--------\n", "--------\n这是一行无法识别的词缀\n", 3)
        base = metrics()
        result = self.evaluate(base, [slot("Body Armour", "Old", base, metrics(ehp=150.0))], text)
        self.assertIn("这是一行无法识别的词缀", [line["text"] for line in result["item"]["unrecognized"]])
        self.assertEqual((result["item"]["unique_name"], result["item"]["base_name"]), ("幻梦曲", "符文师匠萨满斗篷"))
        self.assertEqual(result["slots"][0]["summary"], "比当前胸甲强：DPS 不变，有效生命 +50")
        english = self.evaluate(base, [], text, language="en")
        self.assertIsNone(english["default_slot"])


@unittest.skipUnless((ENGINE / "src").is_dir(), "pinned engine required")
class BackendEngineTests(unittest.TestCase):
    def test_real_engine_evaluates_tencent_gloves(self):
        cwd = os.getcwd()
        try:
            backend = Backend(ENGINE, BUILD)
            backend.start()
            self.assertIsNone(backend.engine_error)
            reply = call(backend, {"item_text": SAMPLE.read_text(encoding="utf-8"),
                                   "game": {"realm": "pc-tencent", "language": "cmn-Hans"}})
        finally:
            os.chdir(cwd)
        result = reply["result"]
        self.assertEqual([slot["slot"] for slot in result["slots"]], ["Gloves"])
        self.assertEqual(result["skill"]["dps_source"], "player")
        gloves = result["slots"][0]
        self.assertGreater(gloves["metrics"]["EnergyShield"], result["baseline"]["EnergyShield"])
        self.assertEqual((result["default_slot"], gloves["label"], result["skill"]["main_skill_name"]),
                         ("Gloves", "手套", "火球"))
        fire = gloves["resists"]["Fire"]
        self.assertEqual(fire["change"], 39)
        self.assertEqual(fire["value"], min(fire["total"], fire["max"]))
        self.assertTrue(gloves["summary"].startswith("比空的手套强：DPS 不变，"))


if __name__ == "__main__":
    unittest.main()
