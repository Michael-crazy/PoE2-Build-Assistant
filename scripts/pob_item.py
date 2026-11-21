#!/usr/bin/env python3
"""Ask the pinned PoB worker how it reads one English item text (pob-item/1)."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from pob_trial import PIN


def engine_item(raw_text, worker, timeout=120):
    if not raw_text.strip():
        raise ValueError("装备文本为空")
    request = {"protocol": "pob-item/1",
               "engine_commit": json.loads(PIN.read_text(encoding="utf-8"))["commit"],
               "raw_text": raw_text}
    payload = json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    with tempfile.TemporaryDirectory(prefix="pob-item-") as directory:
        result = subprocess.run(worker, input=payload, capture_output=True,
                                cwd=directory, timeout=timeout, shell=False)
    if result.returncode:
        raise ValueError("PoB worker 失败：" + result.stderr.decode("utf-8", errors="replace")[-2000:])
    response = json.loads(result.stdout)
    expected = {"protocol": request["protocol"], "engine_commit": request["engine_commit"],
                "request_sha256": hashlib.sha256(payload).hexdigest()}
    if not isinstance(response, dict) or any(response.get(k) != v for k, v in expected.items()):
        raise ValueError("PoB worker 协议、版本或输入摘要不匹配")
    return response


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--item", required=True, type=Path, help="英文装备文本")
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("worker", nargs=argparse.REMAINDER, help="-- 后给出 worker 的绝对路径命令")
    args = parser.parse_args()
    worker = args.worker[1:] if args.worker[:1] == ["--"] else args.worker
    if not worker:
        parser.error("需要 worker 命令")
    try:
        result = engine_item(args.item.read_text(encoding="utf-8"), worker, args.timeout)
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        parser.exit(1, f"引擎读取装备失败：{error}\n")
    sys.stdout.buffer.write((json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
