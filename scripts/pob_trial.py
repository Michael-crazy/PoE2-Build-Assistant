#!/usr/bin/env python3
"""Offline trial process contract; requires an explicitly supplied PoB worker."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
import tempfile

PIN = Path(__file__).resolve().parents[1] / "sources/pob.json"
METRICS = ("CombinedDPS", "Life", "EnergyShield", "Armour", "Evasion")


def trial(build_path, item_path, slot, worker, timeout=30):
    if not slot.strip():
        raise ValueError("装备槽不能为空")
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("超时必须是正数")
    request = {
        "protocol": "pob-trial/1",
        "engine_commit": json.loads(PIN.read_text(encoding="utf-8"))["commit"],
        "build_xml": Path(build_path).read_text(encoding="utf-8"),
        "replacement": {"slot": slot, "raw_text": Path(item_path).read_text(encoding="utf-8")},
    }
    if not request["build_xml"].strip() or not request["replacement"]["raw_text"].strip():
        raise ValueError("BD 和候选装备不能为空")
    payload = json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    # No source path or save command crosses the boundary. Workers must use an
    # absolute executable/script path because their cwd is disposable.
    with tempfile.TemporaryDirectory(prefix="pob-trial-") as directory:
        result = subprocess.run(worker, input=payload, capture_output=True,
                                cwd=directory, timeout=timeout, shell=False)
    if result.returncode:
        raise ValueError(f"PoB worker 退出 {result.returncode}: " + result.stderr.decode("utf-8", errors="replace")[-2000:])
    response = json.loads(result.stdout)
    if not isinstance(response, dict) or any(response.get(key) != value for key, value in {
        "protocol": request["protocol"], "engine_commit": request["engine_commit"],
        "request_sha256": digest,
    }.items()):
        raise ValueError("PoB worker 协议、版本或输入摘要不匹配")
    for phase in ("baseline", "replacement"):
        metrics = response.get(phase)
        if not isinstance(metrics, dict):
            raise ValueError(f"缺少 {phase} 指标")
        for key in METRICS:
            value = metrics.get(key)
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise ValueError(f"无效指标 {phase}.{key}")
    return {**response, "delta": {key: response["replacement"][key] - response["baseline"][key]
                                  for key in METRICS}}


def add_trial_arguments(parser):
    parser.add_argument("--build", required=True, type=Path)
    parser.add_argument("--item", required=True, type=Path)
    parser.add_argument("--slot", required=True)
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("worker", nargs=argparse.REMAINDER, help="-- 后给出 worker 的绝对路径命令")


def run_trial_command(parser, args):
    worker = args.worker[1:] if args.worker[:1] == ["--"] else args.worker
    if not worker:
        parser.error("需要 worker 命令")
    try:
        output = trial(args.build, args.item, args.slot, worker, args.timeout)
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        parser.exit(1, f"试穿失败：{error}\n")
    print(json.dumps(output, ensure_ascii=False, allow_nan=False))
    return 0


def main():
    parser = argparse.ArgumentParser(description="离线 PoB 试穿进程契约（需另备真实 worker）")
    add_trial_arguments(parser)
    return run_trial_command(parser, parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
