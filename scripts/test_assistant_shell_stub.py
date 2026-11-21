import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

STUB = Path(__file__).with_name("assistant_shell_stub.py")


class StubProtocolTest(unittest.TestCase):
    def test_evaluate_item_and_errors(self):
        requests = [
            {"protocol": "assistant-shell/1", "id": 1, "method": "evaluate-item",
             "params": {"item_text": "物品类别: 手套\n\n稀有度: 稀有\n", "game": {"realm": "pc-tencent", "language": "cmn-Hans"}}},
            {"protocol": "assistant-shell/1", "id": 2, "method": "nope", "params": {}},
            {"protocol": "other", "id": 3, "method": "evaluate-item", "params": {}},
        ]
        stdin = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in requests)
        out = subprocess.run([sys.executable, "-B", str(STUB)], input=stdin.encode("utf-8"),
                             capture_output=True, check=True, env={**os.environ, "PYTHONUTF8": "1"}).stdout
        replies = [json.loads(line) for line in out.decode("utf-8").splitlines()]
        self.assertEqual([r["id"] for r in replies], [1, 2, 3])
        self.assertEqual(replies[0]["result"]["first_lines"], ["物品类别: 手套", "稀有度: 稀有"])
        self.assertEqual(replies[0]["result"]["game"]["realm"], "pc-tencent")
        self.assertEqual(replies[1]["error"]["code"], "unknown-method")
        self.assertEqual(replies[2]["error"]["code"], "bad-protocol")


if __name__ == "__main__":
    unittest.main()
