"""Synthetic protocol worker. Does not load or calculate PoB."""
import hashlib
import json
from pathlib import Path
import sys
import time

payload = sys.stdin.buffer.read()
request = json.loads(payload)
# Verify the adapter transports the selected input unchanged, including UTF-8.
fixture = Path(__file__).parent
assert request["build_xml"] == (fixture / "build.xml").read_text(encoding="utf-8")
assert request["replacement"] == {
    "slot": "Weapon 1", "raw_text": (fixture / "item.txt").read_text(encoding="utf-8")}
mode = sys.argv[1] if len(sys.argv) > 1 else "ok"
if mode == "timeout":
    time.sleep(5)
if mode == "exit":
    sys.exit(7)
if mode == "malformed":
    print("not json")
    sys.exit()
response = json.loads(Path(__file__).with_name("result.json").read_text())
response.update(protocol=request["protocol"], engine_commit=request["engine_commit"],
                request_sha256=hashlib.sha256(payload).hexdigest())
if mode == "digest":
    response["request_sha256"] = "wrong"
if mode == "version":
    response["engine_commit"] = "wrong"
if mode == "missing":
    del response["replacement"]["Life"]
if mode == "nan":
    response["baseline"]["CombinedDPS"] = float("nan")
if mode == "boolean":
    response["baseline"]["Life"] = True
print(json.dumps(response))
