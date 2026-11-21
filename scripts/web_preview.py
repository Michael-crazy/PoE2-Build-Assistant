"""M09a: local HTTP endpoint for the trade-site browser extension (sources/web-preview.md).

The assistant overlay (EE2) sends `web-preview` over the stdio protocol with the on/off
setting, the port and the poe.ninja exchange rates; this module then listens on
127.0.0.1 only and answers POST /evaluate with the same evaluation as the in-game
overlay (Backend.evaluate_item: U02 live build, M06 metrics) plus M08b's value for money.

Any web page can send requests to localhost, so every request must come from the
extension itself: its Origin is chrome-extension://<pinned id> or moz-extension://<uuid>.
No CORS headers are sent (extension background scripts do not need them), and the
endpoint only evaluates: nothing changes the build.

M09b: the assistant's own trade window (EE2 TradeWindow) runs the same page script and
asks over stdio (method trade-preview, Backend.trade_preview) instead of HTTP; that path
also serves the Tencent trade site, whose items are Simplified Chinese (P05) and whose
value for money uses the rates typed in the settings (M08b), sent along as
`tencent_currencies`.
"""

from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import re
import sys
import threading

DEFAULT_PORT = 37428
# Chrome derives the id from the public key pinned in the extension's manifest.json ("key").
CHROME_EXTENSION_IDS = frozenset({"dbhocbceaidfohejkkcllnbbcaeaikkm"})
# Firefox gives every installation its own random UUID, so any moz-extension origin is accepted.
MOZ_ORIGIN = re.compile(r"^moz-extension://[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
MAX_BODY = 64 * 1024
REQUEST_TIMEOUT = 5  # seconds a client may take to send its request
# Trade site language -> game.language (assistant_backend.LANGUAGE). The page script sends
# "zh_hans" on poe.game.qq.com: English section headers with Simplified Chinese names and
# modifiers, which P05 reads when told the language.
LANGUAGES = {"en": "en", "zh_hans": "cmn-Hans"}
REALMS = ("pc-ggg", "pc-tencent")
MAX_ITEM_TEXT = 20_000
BASE_CURRENCIES = ("divine", "exalted", "chaos")


def allowed_origin(origin):
    if not isinstance(origin, str):
        return False
    if origin.startswith("chrome-extension://"):
        return origin[len("chrome-extension://"):] in CHROME_EXTENSION_IDS
    return bool(MOZ_ORIGIN.match(origin))


def price_in_base(price, base, rates):
    """Same as M08b priceInBase: rates are Divine Orbs per unit."""
    if price["currency"] == base:
        return {"ok": True, "value": price["amount"]}

    def divines(currency):
        return 1 if currency == "divine" else (rates.get(currency) or {}).get("divines")

    unit = divines(price["currency"])
    if not (isinstance(unit, (int, float)) and unit > 0):
        return {"ok": False, "missing": price["currency"]}
    base_unit = divines(base)
    if not (isinstance(base_unit, (int, float)) and base_unit > 0):
        return {"ok": False, "missing": base}
    return {"ok": True, "value": price["amount"] * unit / base_unit}


def parse_price(value, rates):
    """{amount, currency (trade id, or None when unknown), text}; the page sends the icon's
    id when it has one and the currency's English name as shown."""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("price")
    amount, currency, text = value.get("amount"), value.get("currency"), value.get("currency_text")
    if isinstance(amount, bool) or not isinstance(amount, (int, float)) or not 0 < amount < 1e9:
        raise ValueError("price")
    if currency is not None and (not isinstance(currency, str) or not re.fullmatch(r"[a-z0-9-]{1,40}", currency)):
        raise ValueError("price")
    if text is not None and (not isinstance(text, str) or len(text) > 80):
        raise ValueError("price")
    if currency is None and text:
        # English name on the international site, Simplified Chinese on the Tencent one.
        wanted = text.strip().casefold()
        currency = next((key for key, info in rates.items()
                         if wanted in (str(info.get("en", "")).casefold(), str(info.get("name", "")).casefold())), None)
    if currency is None and not text:
        raise ValueError("price")
    return {"amount": amount, "currency": currency, "text": text or currency}


class WebPreview:
    def __init__(self, backend):
        self.backend = backend
        self.lock = threading.Lock()  # guards the listener and the settings
        self.httpd = None
        self.port = None
        self.base = "divine"
        self.rates = {}  # trade id -> {"name": 简中名, "en": English name, "divines": value in Divine Orbs}
        self.rates_source = None
        self.tencent_rates = {}  # same shape, from the rates typed in the settings (M08b)
        self.error = None

    # ---- settings from the overlay (stdio method web-preview) ----

    def configure(self, params):
        enabled = params.get("enabled") is True
        port = params.get("port", DEFAULT_PORT)
        if isinstance(port, bool) or not isinstance(port, int) or not 1024 <= port <= 65535:
            raise ValueError(f"网页预览端口无效：{port!r}（应为 1024–65535）")
        base = params.get("value_currency")
        rates = params.get("currencies") or {}
        tencent = params.get("tencent_currencies") or {}
        if not isinstance(rates, dict) or not isinstance(tencent, dict):
            raise ValueError("currencies 应为对象")
        with self.lock:
            self.base = base if base in BASE_CURRENCIES else "divine"
            self.rates = {key: value for key, value in rates.items() if isinstance(value, dict)}
            self.rates_source = params.get("rates_source")
            self.tencent_rates = {key: value for key, value in tencent.items() if isinstance(value, dict)}
            if not enabled:
                self._stop()
                self.error = None
            elif self.httpd is None or self.port != port:
                self._stop()
                self._start(port)
            return {"listening": self.httpd is not None, "port": self.port if self.httpd else None,
                    "error": self.error}

    def _start(self, port):
        try:
            httpd = HTTPServer(("127.0.0.1", port), self._handler_class())
        except OSError as error:
            message = f"网页预览无法监听 127.0.0.1:{port}：{error.strerror or error}"
            if message != self.error:
                print(message, file=sys.stderr, flush=True)
            self.error = message
            return
        self.httpd, self.port, self.error = httpd, port, None
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        print(f"网页预览已监听 127.0.0.1:{port}", file=sys.stderr, flush=True)

    def _stop(self):
        if self.httpd is not None:
            self.httpd.shutdown()
            self.httpd.server_close()
            print(f"网页预览已停止（127.0.0.1:{self.port}）", file=sys.stderr, flush=True)
        self.httpd = None
        self.port = None

    def close(self):
        with self.lock:
            self._stop()

    # ---- HTTP ----

    def respond(self, method, path, headers, body):
        """(status, JSON reply) for one request; pure so tests need no sockets."""
        origin = headers.get("Origin")
        if not allowed_origin(origin):
            return 403, {"ok": False, "code": "forbidden-origin", "message": "只接受助手浏览器扩展的请求"}
        port = self.port
        if headers.get("Host") not in {f"127.0.0.1:{port}", f"localhost:{port}"}:
            return 403, {"ok": False, "code": "forbidden-host", "message": "请求的主机名不对"}
        if path != "/evaluate":
            return 404, {"ok": False, "code": "not-found", "message": f"没有 {path}"}
        if method != "POST":
            return 405, {"ok": False, "code": "method-not-allowed", "message": "只接受 POST"}
        if (headers.get("Content-Type") or "").split(";")[0].strip() != "application/json":
            return 415, {"ok": False, "code": "bad-content-type", "message": "需要 application/json"}
        try:
            request = json.loads(body.decode("utf-8"))
            if not isinstance(request, dict):
                raise ValueError("not an object")
            price = parse_price(request.get("price"), self.rates)
        except ValueError:
            return 400, {"ok": False, "code": "bad-request", "message": "请求格式不对"}
        return 200, self.evaluate(request, price)

    def rates_for(self, realm):
        return self.tencent_rates if realm == "pc-tencent" else self.rates

    def trade_window(self, params):
        """M09b: one row of the assistant's trade window (stdio, no HTTP). Same reply as /evaluate."""
        realm = params.get("realm")
        if realm not in REALMS:
            raise ValueError("realm")
        text = params.get("item_text")
        if not isinstance(text, str) or len(text) > MAX_ITEM_TEXT:
            raise ValueError("item_text")
        price = parse_price(params.get("price"), self.rates_for(realm))
        return self.evaluate(params, price, realm)

    def evaluate(self, request, price, realm="pc-ggg"):
        language = LANGUAGES.get(request.get("language") or "en")
        if language is None:
            return {"ok": False, "code": "unsupported-language", "message": "只支持英文和国服简中的市集页面"}
        params = {"item_text": request.get("item_text"), "game": {"realm": realm, "language": language}}
        try:
            result = self.backend.evaluate_item(params)
        except Exception as error:  # keep serving; the page shows the reason
            # BackendError by its code: when assistant_backend.py runs as a script its class is
            # __main__.BackendError, not the one an import here would give (seen in M09b).
            if isinstance(getattr(error, "code", None), str):
                return {"ok": False, "code": error.code, "message": str(error)}
            return {"ok": False, "code": "internal", "message": f"后端内部错误：{type(error).__name__}: {error}"}
        return self.preview(result, price, realm)

    def preview(self, result, price, realm="pc-ggg"):
        """The few fields a result row shows, from the overlay's evaluation result."""
        slots = result.get("slots") or []
        chosen = next((s for s in slots if s["slot"] == result.get("default_slot")), slots[0] if slots else None)

        def brief(slot):
            return {"slot": slot["slot"], "label": slot["label"], "summary": slot["summary"],
                    "dps_percent": slot["dps"]["percent"], "dps_absolute": slot["dps"]["absolute"],
                    "ehp": slot["delta"].get("TotalEHP", 0)}

        build = result.get("build") or {}
        reply = {"ok": True,
                 "item": {key: result["item"].get(key) for key in ("name", "base_name", "unique_name", "unrecognized")},
                 "build": {key: build.get(key) for key in ("name", "source", "unsaved")},
                 "slot": brief(chosen) if chosen else None,
                 "slots": [brief(slot) for slot in slots],
                 "price": price, "value": None}
        if price and chosen:
            reply["value"] = self.value(chosen, price, realm)
        return reply

    def name(self, currency):
        return (self.rates.get(currency) or self.tencent_rates.get(currency) or {}).get("name") or currency

    def value(self, slot, price, realm="pc-ggg"):
        base = self.base
        rates = self.rates_for(realm)
        if price["currency"] is None:
            return {"base": base, "base_name": self.name(base), "price_name": price["text"],
                    "message": f"不认识的通货：{price['text']}"}
        reply = {"base": base, "base_name": self.name(base), "price_name": self.name(price["currency"])}
        converted = price_in_base(price, base, rates)
        if not converted["ok"]:
            missing = converted["missing"]
            # Before any rates arrived only the page's own currency text names it.
            missing_name = (price["text"] if missing == price["currency"] and self.name(missing) == missing
                            else self.name(missing))
            if realm == "pc-tencent":
                reply["message"] = (f"没有{missing_name}的汇率：请在 PoB 选项“游戏内助手”"
                                    "或助手设置里填写腾讯服汇率")
            elif self.rates_source is None:
                reply["message"] = "正在获取 poe.ninja 汇率…"
            else:
                reply["message"] = f"poe.ninja 没有{self.name(converted['missing'])}的价格"
            return reply
        amount = converted["value"]
        reply["price_in_base"] = amount
        percent = slot["dps"]["percent"]
        reply["dps_percent"] = None if percent is None else percent / amount
        reply["ehp"] = slot["delta"].get("TotalEHP", 0) / amount
        return reply

    def _handler_class(self):
        preview = self

        class Handler(BaseHTTPRequestHandler):
            timeout = REQUEST_TIMEOUT
            server_version = "PoE2Assistant"
            sys_version = ""

            def handle_any(self):
                length = self.headers.get("Content-Length")
                try:
                    size = int(length) if length is not None else 0
                except ValueError:
                    size = -1
                if not 0 <= size <= MAX_BODY:
                    status, reply = 413, {"ok": False, "code": "too-large", "message": "请求太大"}
                else:
                    body = self.rfile.read(size) if size else b""
                    status, reply = preview.respond(self.command, self.path, self.headers, body)
                data = json.dumps(reply, ensure_ascii=False, allow_nan=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = do_OPTIONS = do_PUT = do_DELETE = do_HEAD = handle_any

            def log_message(self, format, *args):  # noqa: A002 - stdlib signature
                pass  # stdout belongs to the protocol; per-request logs would flood stderr

        return Handler
