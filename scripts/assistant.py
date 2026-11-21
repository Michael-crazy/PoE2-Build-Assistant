#!/usr/bin/env python3
"""Assistant entry point for PoB, item parsing, gear trials, build estimates and upgrade value."""

import argparse
import json
from pathlib import Path
import subprocess

from build_estimate import aggregate_quotes, estimate_file
from slot_quotes import assemble_file
from build_slots import engine_build, extract_build, selections_for_build
from item_text import add_parse_arguments, run_parse_command
from pob_current import locate
from pob_server import add_server_arguments, run_server_command
from pob_trial import add_trial_arguments, run_trial_command
from upgrade_value import add_value_arguments, run_value_command


def launch_pob(executable: Path) -> subprocess.Popen:
    executable = executable.expanduser().resolve(strict=True)
    if not executable.is_file() or executable.suffix.lower() != ".exe":
        raise ValueError("请选择 PoB 的 .exe 文件")
    return subprocess.Popen([str(executable)], cwd=executable.parent, shell=False)


def main() -> int:
    parser = argparse.ArgumentParser(description="PoE 2 助手")
    commands = parser.add_subparsers(dest="command", required=True)
    launch = commands.add_parser("launch-pob", help="启动选定的 PoB 安装")
    launch.add_argument("--pob-exe", required=True, type=Path, help="PoB 可执行文件路径")
    estimate = commands.add_parser("estimate-build", help="离线汇总逐槽参考报价及缺报价槽位")
    estimate.add_argument("input", type=Path, help="含 context 和完整目标 slots 的本地 JSON 文件")
    estimate.add_argument("--from-listings", action="store_true",
                          help="读取本地原始挂单及显式选槽清单")
    estimate.add_argument("worker", nargs=argparse.REMAINDER,
                          help="可选：-- 后给出 PoB worker 命令，按引擎生效装备重新核对选槽")
    inventory = commands.add_parser("build-selections", help="从本地 BD 生成完整活动选槽清单")
    inventory.add_argument("--build", type=Path, required=True)
    inventory.add_argument("--realm", choices=("international", "tencent"), required=True)
    inventory.add_argument("--league", required=True)
    inventory.add_argument("--response-file", type=Path, required=True)
    inventory.add_argument("worker", nargs=argparse.REMAINDER,
                           help="可选：-- 后给出 PoB worker 命令，读取引擎生效装备；省略时静态解析 XML")
    trial = commands.add_parser("trial", help="用指定的 PoB 计算进程试穿装备")
    add_trial_arguments(trial)
    server = commands.add_parser("trial-server", help="常驻 PoB 试算进程，stdio JSON 行协议")
    add_server_arguments(server)
    current = commands.add_parser("current-build", help="定位 PoB 当前或最近打开的 BD 文件")
    current.add_argument("--pob-user-dir", type=Path, help="含 Settings.xml 的 PoB 用户目录")
    value = commands.add_parser("value", help="计算候选装备的提升和每单位通货收益")
    add_value_arguments(value)
    parse = commands.add_parser("parse-item", help="把游戏复制的装备文本（简中、繁中、英文）转成 PoB 英文装备")
    add_parse_arguments(parse)
    args = parser.parse_args()
    if args.command == "parse-item":
        return run_parse_command(parse, args)
    if args.command == "trial":
        return run_trial_command(trial, args)
    if args.command == "trial-server":
        return run_server_command(args)
    if args.command == "current-build":
        try:
            print(json.dumps(locate(args.pob_user_dir), ensure_ascii=False))
        except (OSError, ValueError) as error:
            parser.exit(1, f"{error}\n")
        return 0
    if args.command == "value":
        return run_value_command(value, args)
    worker = getattr(args, "worker", [])
    worker = worker[1:] if worker[:1] == ["--"] else worker
    if args.command == "build-selections":
        try:
            build = engine_build(args.build, worker) if worker else extract_build(args.build)
            result = {"context": {"realm": args.realm, "league": args.league},
                      "build_file": str(args.build.resolve()),
                      "response_file": str(args.response_file.resolve()),
                      "build": build, "selections": selections_for_build(build)}
            output = json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2)
        except (OSError, ValueError, TypeError, subprocess.TimeoutExpired) as error:
            parser.exit(1, f"BD 选槽失败：{error}\n")
        print(output)
        return 0
    if args.command == "estimate-build":
        try:
            if args.from_listings:
                quotes = assemble_file(args.input, worker)
                result = aggregate_quotes(quotes["slots"], **quotes["context"])
                if "build" in quotes:
                    result["build"] = quotes["build"]
            else:
                result = estimate_file(args.input)
            output = json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2)
        except (OSError, ValueError, TypeError, OverflowError, subprocess.TimeoutExpired) as error:
            parser.exit(1, f"整套估价汇总失败：{error}\n")
        print(output)
        return 0
    try:
        process = launch_pob(args.pob_exe)
    except (OSError, ValueError) as error:
        parser.exit(1, f"无法启动 PoB：{error}\n")
    print(f"已请求启动 PoB（PID {process.pid}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
