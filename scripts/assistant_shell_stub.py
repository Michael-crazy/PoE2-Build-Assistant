#!/usr/bin/env python3
"""Stub backend for the assistant shell (sources/assistant-shell.md).

Reads one JSON request per line on stdin and answers one JSON line on stdout.
evaluate-item echoes what it received so the overlay path can be tested
before P05/P02/M06 are wired in.
"""

import json
import sys

PROTOCOL = "assistant-shell/1"


def evaluate_item(params: dict) -> dict:
    lines = [line for line in params["item_text"].splitlines() if line.strip()]
    return {
        "stub": True,
        "game": params.get("game"),
        "line_count": len(lines),
        "first_lines": lines[:3],
    }


METHODS = {"evaluate-item": evaluate_item}


def handle(request: dict) -> dict:
    if request.get("protocol") != PROTOCOL:
        return {"error": {"code": "bad-protocol", "message": f"需要 {PROTOCOL}"}}
    method = METHODS.get(request.get("method"))
    if method is None:
        return {"error": {"code": "unknown-method", "message": f"未知方法 {request.get('method')}"}}
    return {"result": method(request.get("params") or {})}


def main() -> int:
    for line in sys.stdin:
        if not line.strip():
            continue
        request = json.loads(line)
        reply = {"id": request.get("id"), **handle(request)}
        sys.stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
