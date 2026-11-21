import http.client
import io
import json
from pathlib import Path
import socket
import unittest

from assistant_backend import Backend, PROTOCOL
from item_text import parse_item
from test_assistant_backend import TrialServer, metrics, slot
from web_preview import DEFAULT_PORT, WebPreview, allowed_origin, price_in_base

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/m09a"
CHROME = "chrome-extension://dbhocbceaidfohejkkcllnbbcaeaikkm"
FIREFOX = "moz-extension://3f1e2d4c-5b6a-4789-8abc-def012345678"
RATES = {"divine": {"name": "神圣石", "en": "Divine Orb", "divines": 1},
         "exalted": {"name": "崇高石", "en": "Exalted Orb", "divines": 0.002},
         "chaos": {"name": "混沌石", "en": "Chaos Orb", "divines": 0.01},
         "annul": {"name": "剥离石", "en": "Orb of Annulment"}}
GLOVES = (FIXTURES / "expected-rare-gloves.txt").read_text(encoding="utf-8")
# M09b: what the page script builds from a Tencent result row (English headers from the
# upstream exporter, Simplified Chinese names and modifiers). Synthetic, from a P05 sample.
TENCENT_BOOTS = (ROOT / "tests/fixtures/m09b/tencent-row-boots.synthetic.txt").read_text(encoding="utf-8")
TENCENT_RATES = {"divine": {"name": "神圣石", "en": "Divine Orb", "divines": 1},
                 "exalted": {"name": "崇高石", "en": "Exalted Orb", "divines": 1 / 400},
                 "chaos": {"name": "混沌石", "en": "Chaos Orb"}}


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def backend_with_trial():
    backend = Backend(None)
    before = metrics(dps=1000.0, ehp=2000.0)
    backend.server = TrialServer(before, [slot("Gloves", "Old Gloves", before, metrics(dps=1100.0, ehp=2300.0))])
    return backend


def stdio(backend, params):
    out = io.StringIO()
    backend.serve([json.dumps({"protocol": PROTOCOL, "id": 9, "method": "web-preview", "params": params})], out)
    return json.loads(out.getvalue())


class OriginTests(unittest.TestCase):
    def test_only_the_extension_origins_are_allowed(self):
        self.assertTrue(allowed_origin(CHROME))
        self.assertTrue(allowed_origin(FIREFOX))
        for origin in (None, "", "null", "https://www.pathofexile.com", "http://127.0.0.1:37428",
                       "chrome-extension://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", CHROME + ".evil.com",
                       "moz-extension://not-a-uuid", FIREFOX + "/x", "https://evil.com/" + CHROME):
            self.assertFalse(allowed_origin(origin), origin)


class RespondTests(unittest.TestCase):
    def setUp(self):
        self.backend = backend_with_trial()
        self.preview = self.backend.web_preview
        self.preview.port = DEFAULT_PORT
        self.preview.rates = RATES
        self.preview.rates_source = "poe.ninja"

    def post(self, body, origin=CHROME, host=f"127.0.0.1:{DEFAULT_PORT}", method="POST", path="/evaluate",
             content_type="application/json"):
        headers = {"Origin": origin, "Host": host, "Content-Type": content_type}
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        return self.preview.respond(method, path, {k: v for k, v in headers.items() if v is not None}, data)

    def test_web_pages_are_refused_before_anything_is_evaluated(self):
        for origin in ("https://www.pathofexile.com", "null", None, "chrome-extension://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"):
            status, reply = self.post({"item_text": GLOVES}, origin=origin)
            self.assertEqual((status, reply["code"]), (403, "forbidden-origin"), origin)
        self.assertEqual(self.backend.server.requests, [])

    def test_other_host_names_are_refused(self):  # DNS rebinding: evil.com resolving to 127.0.0.1
        status, reply = self.post({"item_text": GLOVES}, host=f"evil.com:{DEFAULT_PORT}")
        self.assertEqual((status, reply["code"]), (403, "forbidden-host"))
        self.assertEqual(self.post({"item_text": GLOVES}, host=f"localhost:{DEFAULT_PORT}")[0], 200)

    def test_only_post_json_to_evaluate(self):
        self.assertEqual(self.post({}, method="GET")[0], 405)
        self.assertEqual(self.post({}, method="OPTIONS")[0], 405)
        self.assertEqual(self.post({}, path="/config")[0], 404)
        self.assertEqual(self.post({"item_text": GLOVES}, content_type="text/plain")[0], 415)
        self.assertEqual(self.post(b"not json")[0], 400)
        self.assertEqual(self.post({"item_text": GLOVES, "price": {"amount": -1, "currency": "divine"}})[0], 400)
        self.assertEqual(self.post({"item_text": GLOVES, "price": {"amount": 1, "currency": "../x"}})[0], 400)

    def test_evaluates_like_the_overlay_and_counts_value_in_divines(self):
        status, reply = self.post({"item_text": GLOVES, "price": {"amount": 50, "currency": "exalted"}})
        self.assertEqual(status, 200)
        self.assertTrue(reply["ok"])
        sent = self.backend.server.requests[0]
        self.assertEqual(sent["cmd"], "evaluate")
        self.assertIn("Rarity: Rare", sent["item_text"])
        self.assertEqual(reply["slot"]["label"], "手套")
        self.assertEqual(reply["slot"]["dps_percent"], 10.0)
        self.assertEqual(reply["slot"]["ehp"], 300.0)
        self.assertTrue(reply["slot"]["summary"].startswith("比当前手套强"))
        value = reply["value"]  # 50 exalted = 0.1 divine
        self.assertAlmostEqual(value["price_in_base"], 0.1)
        self.assertAlmostEqual(value["price_in_divine"], 0.1)
        self.assertAlmostEqual(value["dps_percent"], 100.0)
        self.assertAlmostEqual(value["ehp"], 3000.0)
        self.assertEqual((value["base_name"], value["price_name"]), ("神圣石", "崇高石"))

    def test_missing_rates_explain_themselves(self):
        self.preview.rates_source = None  # poe.ninja still loading: names only
        self.preview.rates = {key: {"name": info["name"], "en": info["en"]} for key, info in RATES.items()}
        reply = self.post({"item_text": GLOVES, "price": {"amount": 3, "currency": "exalted"}})[1]
        self.assertEqual(reply["value"]["message"], "正在获取 poe.ninja 汇率…")
        self.preview.rates_source, self.preview.rates = "poe.ninja", RATES
        reply = self.post({"item_text": GLOVES, "price": {"amount": 3, "currency": "annul"}})[1]
        self.assertEqual(reply["value"]["message"], "poe.ninja 没有剥离石的价格")
        reply = self.post({"item_text": GLOVES, "price": {"amount": 2, "currency": "divine"}})[1]
        self.assertAlmostEqual(reply["value"]["ehp"], 150.0)  # same currency needs no rate
        self.assertIsNone(self.post({"item_text": GLOVES})[1]["value"])

    def test_price_given_by_english_name(self):
        reply = self.post({"item_text": GLOVES, "price": {"amount": 1, "currency_text": "chaos orb"}})[1]
        self.assertEqual(reply["price"]["currency"], "chaos")
        self.assertAlmostEqual(reply["value"]["price_in_base"], 0.01)
        reply = self.post({"item_text": GLOVES, "price": {"amount": 1, "currency_text": "Shiny Pebble"}})[1]
        self.assertEqual(reply["value"]["message"], "不认识的通货：Shiny Pebble")
        self.assertEqual(self.post({"item_text": GLOVES, "price": {"amount": 1}})[0], 400)

    def test_evaluation_errors_are_plain_chinese(self):
        currency = "Item Class: Stackable Currency\nRarity: Currency\nExalted Orb\n--------\nStack Size: 1/20\n"
        reply = self.post({"item_text": currency})[1]
        self.assertEqual((reply["ok"], reply["code"]), (False, "not-equippable"))
        self.assertEqual(self.post({"item_text": ""})[1]["code"], "bad-request")
        self.assertEqual(self.post({"item_text": GLOVES, "language": "de"})[1]["code"], "unsupported-language")


class TradeWindowTests(unittest.TestCase):
    """M09b: the assistant's trade window asks over stdio (method trade-preview), no HTTP."""

    def setUp(self):
        self.backend = backend_with_trial()
        reply = stdio(self.backend, {"enabled": False, "currencies": RATES, "rates_source": "poe.ninja",
                                     "tencent_currencies": TENCENT_RATES})
        self.assertFalse(reply["result"]["listening"])  # the extension endpoint stays off

    def ask(self, params):
        out = io.StringIO()
        self.backend.serve([json.dumps({"protocol": PROTOCOL, "id": 3, "method": "trade-preview",
                                        "params": params})], out)
        return json.loads(out.getvalue())

    def test_tencent_rows_are_simplified_chinese_with_typed_rates(self):
        reply = self.ask({"item_text": TENCENT_BOOTS, "language": "zh_hans", "realm": "pc-tencent",
                          "price": {"amount": 100, "currency": "exalted", "currency_text": "崇高石"}})["result"]
        self.assertTrue(reply["ok"])
        sent = self.backend.server.requests[0]["item_text"]
        self.assertIn("Sekhema Sandals", sent)
        self.assertIn("+40% to Cold Resistance", sent)
        self.assertEqual(reply["item"]["unrecognized"], [])
        self.assertAlmostEqual(reply["value"]["price_in_base"], 0.25)  # 100 / 400, not poe.ninja's 0.2
        reply = self.ask({"item_text": TENCENT_BOOTS, "language": "zh_hans", "realm": "pc-tencent",
                          "price": {"amount": 1, "currency_text": "混沌石"}})["result"]
        self.assertEqual(reply["price"]["currency"], "chaos")  # matched by the Chinese name
        self.assertIn("腾讯服汇率", reply["value"]["message"])

    def test_missing_tencent_rates_name_the_currency_as_shown(self):
        self.backend.web_preview.tencent_rates = {}
        self.backend.web_preview.rates = {}
        reply = self.ask({"item_text": TENCENT_BOOTS, "language": "zh_hans", "realm": "pc-tencent",
                          "price": {"amount": 1, "currency": "exalted", "currency_text": "崇高石"}})["result"]
        self.assertTrue(reply["value"]["message"].startswith("没有崇高石的汇率"))

    def test_international_rows_use_poe_ninja(self):
        reply = self.ask({"item_text": GLOVES, "language": "en", "realm": "pc-ggg",
                          "price": {"amount": 100, "currency": "exalted"}})["result"]
        self.assertAlmostEqual(reply["value"]["price_in_base"], 0.2)

    def test_backend_errors_keep_their_code_when_the_backend_runs_as_a_script(self):
        class ScriptBackendError(Exception):  # stands in for __main__.BackendError
            code = "engine-unavailable"

        def refuse(params):
            raise ScriptBackendError("PoB 引擎未启动：x")

        self.backend.evaluate_item = refuse
        reply = self.ask({"item_text": GLOVES, "realm": "pc-ggg"})["result"]
        self.assertEqual((reply["code"], reply["message"]), ("engine-unavailable", "PoB 引擎未启动：x"))

    def test_bad_requests(self):
        for params in ({"item_text": GLOVES, "realm": "pc-garena"}, {"item_text": 5, "realm": "pc-ggg"},
                       {"item_text": "x" * 30000, "realm": "pc-ggg"},
                       {"item_text": GLOVES, "realm": "pc-ggg", "price": {"amount": "1"}}):
            self.assertEqual(self.ask(params)["error"]["code"], "bad-request")
        reply = self.ask({"item_text": GLOVES, "realm": "pc-ggg", "language": "de"})["result"]
        self.assertEqual(reply["code"], "unsupported-language")


class PriceTests(unittest.TestCase):
    def test_same_as_m08b(self):
        self.assertEqual(price_in_base({"amount": 2, "currency": "divine"}, "divine", {}), {"ok": True, "value": 2})
        self.assertAlmostEqual(price_in_base({"amount": 200, "currency": "exalted"}, "chaos", RATES)["value"], 40)
        self.assertEqual(price_in_base({"amount": 1, "currency": "divine"}, "exalted", {}),
                         {"ok": False, "missing": "exalted"})


class ListenerTests(unittest.TestCase):
    def setUp(self):
        self.backend = backend_with_trial()
        self.port = free_port()

    def tearDown(self):
        self.backend.web_preview.close()

    def request(self, origin, body, port=None):
        connection = http.client.HTTPConnection("127.0.0.1", port or self.port, timeout=5)
        headers = {"Content-Type": "application/json"}
        if origin:
            headers["Origin"] = origin
        connection.request("POST", "/evaluate", json.dumps(body), headers)
        response = connection.getresponse()
        reply = (response.status, dict(response.getheaders()), json.loads(response.read()))
        connection.close()
        return reply

    def test_settings_over_stdio_start_move_and_stop_the_listener(self):
        reply = stdio(self.backend, {"enabled": True, "port": self.port, "value_currency": "divine",
                                     "currencies": RATES})
        self.assertEqual(reply["result"], {"listening": True, "port": self.port, "error": None})
        status, headers, body = self.request(CHROME, {"item_text": GLOVES, "price": {"amount": 1, "currency": "divine"}})
        self.assertEqual(status, 200)
        self.assertAlmostEqual(body["value"]["dps_percent"], 10.0)
        self.assertNotIn("Access-Control-Allow-Origin", headers)  # no CORS for pages
        status, headers, body = self.request("https://www.pathofexile.com", {"item_text": GLOVES})
        self.assertEqual((status, body["code"]), (403, "forbidden-origin"))
        self.assertNotIn("Access-Control-Allow-Origin", headers)
        self.assertEqual(self.request(None, {"item_text": GLOVES})[0], 403)

        moved = free_port()
        self.assertEqual(stdio(self.backend, {"enabled": True, "port": moved})["result"]["port"], moved)
        self.assertEqual(self.request(FIREFOX, {"item_text": GLOVES}, port=moved)[0], 200)
        with self.assertRaises(OSError):
            self.request(CHROME, {"item_text": GLOVES})  # old port closed

        self.assertEqual(stdio(self.backend, {"enabled": False})["result"], {"listening": False, "port": None,
                                                                             "error": None})
        with self.assertRaises(OSError):
            self.request(CHROME, {"item_text": GLOVES}, port=moved)

    def test_listens_on_loopback_only(self):
        stdio(self.backend, {"enabled": True, "port": self.port})
        self.assertEqual(self.backend.web_preview.httpd.server_address[0], "127.0.0.1")

    def test_busy_port_and_bad_settings_are_reported(self):
        with socket.socket() as taken:
            taken.bind(("127.0.0.1", self.port))
            taken.listen()
            result = stdio(self.backend, {"enabled": True, "port": self.port})["result"]
        self.assertFalse(result["listening"])
        self.assertIn(f"127.0.0.1:{self.port}", result["error"])
        self.assertEqual(stdio(self.backend, {"enabled": True, "port": 80})["error"]["code"], "bad-request")
        self.assertEqual(stdio(self.backend, {"enabled": True, "port": "37428"})["error"]["code"], "bad-request")


class ExtensionTextTests(unittest.TestCase):
    def test_extension_output_parses_without_unrecognized_lines(self):
        """The texts the extension builds from the saved result rows (tests/fixtures/m09a) parse as English."""
        for path in sorted(FIXTURES.glob("expected-*.txt")):
            parsed = parse_item(path.read_text(encoding="utf-8"), "en")
            self.assertEqual(parsed["unrecognized"], [], path.name)
            self.assertIsNotNone(parsed["base"], path.name)


if __name__ == "__main__":
    unittest.main()
