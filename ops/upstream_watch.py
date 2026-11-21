#!/usr/bin/env python3
"""U05/R03: follow upstream PoB-PoE2 / EE2 release tags, refresh PoE2DB and trade data, publish when all checks pass.

  python3 -B ops/upstream_watch.py check   [--config F] [--retry] [--season] [--data]  daily (systemd timer)
  python3 -B ops/upstream_watch.py release [--config F]     push a run held by the "hold" switch
  python3 -B ops/upstream_watch.py status  [--config F]
  python3 -B ops/upstream_watch.py notify-test [--config F]  print (dry-run) or send a test notification

`check` decides what to do:
  - a PoB or EE2 upstream tag `v0.x.y` (PoB's PoE1 `v2.x` tags are ignored) whose commit has the current
    base as an ancestor and is not the base itself; the highest version wins;
  - R03 season: a new Tencent trade league id (one request a day) starts a season; the PoE2DB cache is
    refetched completely then, and again every `season_every` days during `season_days` days;
  - otherwise nothing (exit 0).
A run lives in <state>/runs/<id>/ (run.json lists finished steps; an interrupted run continues at the next
`check`). Steps: prepare (clone the private repo) -> rebase (ops/rebase_check.py, full checks) -> engine
-> data (ops/poe2db_update.py, sources/pob-*.json indexes, trade data) -> commit (data into the private repo and the rebased PoB
branch, new pins) -> recheck (PoB checks again on the data commit) -> export (export_public.py +
check_public.py) -> [hold] -> publish (forks, Linux bare repos, private main, public main).
Nothing is pushed before every check has passed. A conflict or failed step stops the run, writes
report.md and notifies through OpenClaw (`notify`: "dry-run" prints the command, "send" runs it);
the same failed tag is not retried (or notified) again until a newer tag appears or --retry is given.
Publishing is idempotent: a branch already at its target is skipped, so a failed push resumes.

Config (JSON, every key optional): see DEFAULTS. Drills point `project_home`, `public_remote`, `forks`
and `overrides` (pin fields such as home/upstream) at local scratch repositories.
"""
import argparse
from contextlib import contextmanager
import copy
from datetime import datetime, timedelta, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import urllib.request

CST = timezone(timedelta(hours=8))
HOME = Path.home()
STATE = HOME / ".local/state/poe2-assistant"
CONFIG = HOME / ".config/poe2-assistant/upstream-watch.json"
IDENTITY = {"GIT_AUTHOR_NAME": "Claude", "GIT_AUTHOR_EMAIL": "noreply@anthropic.com",
            "GIT_COMMITTER_NAME": "Claude", "GIT_COMMITTER_EMAIL": "noreply@anthropic.com"}
TRAILER = "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
TAG = re.compile(r"^v0\.(\d+)\.(\d+)(?:\.(\d+))?$")
PINS = {"pob": "pob-branch.json", "ee2": "ee2.json"}
INDEXES = (("skills", "pob-skills.en.json"), ("nodes", "pob-nodes.en.json"), ("classes", "pob-classes.en.json"),
           ("gems", "pob-gems.json"))
POB_DATA = ("poe2-assistant/terms", "src/Modules/AssistantUiFallback.lua")
CHECK_STEPS = ["prepare", "rebase", "engine", "data", "commit", "recheck", "export"]
PUBLISH_STEPS = ["push_forks", "push_homes", "push_private", "push_public"]
TRADE_URLS = {
    "tencent": {name: f"https://poe.game.qq.com/api/trade2/data/{name}" for name in ("leagues", "stats", "static")},
    "intl": {name: f"https://www.pathofexile.com/api/trade2/data/{name}" for name in ("stats", "static")},
}
DEFAULTS = {
    "state": str(STATE / "upstream-watch"),
    "project_home": "~/git/PoE2-Build-Assistant.git",
    "project_branch": "main",
    "public_remote": "git@github-poe2-main:Michael-crazy/PoE2-Build-Assistant.git",
    "public_branch": "main",
    "public_terms": "~/workspaces/PoE2-Build-Assistant/ops/public-check-terms.txt",
    "forks": {"pob": "git@github-poe2-pob:Michael-crazy/PathOfBuilding-PoE2.git",
              "ee2": "git@github-poe2-ee2:Michael-crazy/Exiled-Exchange-2.git"},
    "overrides": {"pob": {}, "ee2": {}},  # pin fields replaced for this watcher only (drills)
    "hold": False,                        # observation switch: stop before publishing, wait for `release`
    "notify": "dry-run",                  # "dry-run" | "send" | "off"
    "openclaw": {"node_bin": "~/.nvm/versions/node/v24.22.1/bin", "cli": "~/.npm-global/bin/openclaw",
                 "agent": "main"},
    "fetch": True,                        # PoE2DB network (False: poe2db_update --offline)
    "trade_fetch": True,                  # Tencent/intl trade data (False: use trade_cache)
    "trade_cache": {"tencent": str(STATE / "tencent-trade"), "intl": str(STATE / "intl-trade")},
    "index_max_age": 1,                   # days: index pages refetched on a tag run (new gems/items)
    "season_days": 14, "season_every": 7,
    "luajit": str(STATE / "p02-runtime/LuaJIT/src/luajit"),
    "lua_cpath": str(STATE / "p02-runtime/?.so;;"),
    "timeouts": {"rebase": 3 * 3600, "data": 4 * 3600, "default": 1800},
}


class StepFailed(RuntimeError):
    def __init__(self, message, files=(), log=None):
        super().__init__(message)
        self.files, self.log = list(files), log


def now():
    return datetime.now(CST)


def stamp(when=None):
    return (when or now()).isoformat(timespec="seconds")


def expand(path):
    return Path(os.path.expanduser(str(path)))


def load_config(path):
    config = copy.deepcopy(DEFAULTS)
    path = expand(path)
    if path.exists():
        for key, value in json.loads(path.read_text(encoding="utf-8")).items():
            if isinstance(value, dict) and isinstance(config.get(key), dict):
                config[key] = {**config[key], **value}
            else:
                config[key] = value
    return config


def read_json(path, default=None):
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


# -- tags -----------------------------------------------------------------------------------------
def version(tag):
    match = TAG.match(tag)
    return tuple(int(x or 0) for x in match.groups()) if match else None


def parse_ls_remote(text):
    """`git ls-remote --tags` output -> {tag: commit} (peeled ^{} wins), v0.x.y tags only."""
    tags = {}
    for line in text.splitlines():
        sha, _, ref = line.partition("\t")
        if not ref.startswith("refs/tags/"):
            continue
        name = ref[len("refs/tags/"):]
        peeled = name.endswith("^{}")
        name = name[:-3] if peeled else name
        if version(name) is None:
            continue
        if peeled or name not in tags:
            tags[name] = sha
    return tags


def select_tag(tags, base, is_descendant):
    """Highest v0.x.y tag whose commit is newer than base (base is an ancestor, commit != base)."""
    best = None
    for name, sha in tags.items():
        if version(name) is None or sha == base or not is_descendant(sha):
            continue
        if best is None or version(name) > version(best[0]):
            best = (name, sha)
    return {"tag": best[0], "sha": best[1]} if best else None


# -- notification ---------------------------------------------------------------------------------
def notify_command(config, text):
    claw = config["openclaw"]
    return [str(expand(claw["cli"])), "agent", "--agent", claw["agent"], "--message", text, "--deliver"]


def say(message):
    print(message, flush=True)


def notify(config, text, log=say):
    """Send `text` through OpenClaw (mode "send"), or only print the command (mode "dry-run")."""
    mode = config.get("notify", "dry-run")
    command = notify_command(config, text)
    if mode == "off":
        return {"mode": mode}
    if mode != "send":
        log(f"[通知 dry-run] {shlex.join(command)}")
        log(f"[通知文案] {text}")
        return {"mode": "dry-run", "command": command, "text": text}
    env = dict(os.environ, PATH=f"{expand(config['openclaw']['node_bin'])}:{os.environ.get('PATH', '')}")
    result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=600)
    log(f"[通知] exit {result.returncode}")
    return {"mode": "send", "returncode": result.returncode, "output": (result.stdout + result.stderr)[-2000:]}


def describe(targets):
    names = {"pob": "PoB", "ee2": "EE2"}
    parts = [f"{names[k]} {v['tag']}" for k, v in targets.items() if v]
    return "、".join(parts) or "数据刷新"


# -- the watcher ----------------------------------------------------------------------------------
class Watcher:
    def __init__(self, config, log=say):
        self.config, self.log = config, log
        self.state_dir = expand(config["state"])
        self.state_path = self.state_dir / "state.json"

    # state ------------------------------------------------------------------
    def state(self):
        return read_json(self.state_path, {"handled": {}, "season": {}, "current": None})

    def save_state(self, state):
        write_json(self.state_path, state)

    @contextmanager
    def locked(self):
        self.state_dir.mkdir(parents=True, exist_ok=True)
        with open(self.state_dir / ".lock", "a+") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise SystemExit("another upstream_watch run is active")
            yield

    # commands ---------------------------------------------------------------
    def sh(self, cmd, cwd=None, log=None, env=None, check=True, timeout=None):
        """Run a command; output appended to `log` (a Path) when given."""
        result = subprocess.run([str(c) for c in cmd], cwd=cwd, text=True, capture_output=True,
                                env={**os.environ, **IDENTITY, **(env or {})},
                                timeout=timeout or self.config["timeouts"]["default"])
        if log:
            Path(log).parent.mkdir(parents=True, exist_ok=True)
            with open(log, "a", encoding="utf-8") as handle:
                handle.write(f"$ {shlex.join(str(c) for c in cmd)}\n{result.stdout}{result.stderr}"
                             f"[exit {result.returncode}]\n")
        if check and result.returncode:
            tail = (result.stdout + result.stderr).strip().splitlines()[-5:]
            raise StepFailed(f"{shlex.join(str(c) for c in cmd[:4])} … exit {result.returncode}: "
                             + " | ".join(tail), log=log)
        return result

    def git(self, repo, *args, log=None, check=True):
        return self.sh(["git", "-C", repo, *args], log=log, check=check)

    def home_file(self, path):
        """A file of the private repo's branch (project_home), not of whatever checkout runs this."""
        return self.git(expand(self.config["project_home"]), "show",
                        f"{self.config['project_branch']}:{path}").stdout

    def pins(self, root=None):
        """Pins (with the config overrides) of a checkout, or of the private repo's branch by default."""
        pins = {}
        for key, name in PINS.items():
            data = read_json(Path(root) / "sources" / name) if root else json.loads(self.home_file(f"sources/{name}"))
            pins[key] = {**data, **self.config["overrides"].get(key, {})}
        return pins

    # decision ----------------------------------------------------------------
    def find_tag(self, key, pin, log=None):
        """Newest upstream release tag for pin; fetches the v0 tags into the home repo."""
        home = expand(pin["home"])
        listing = self.git(home, "ls-remote", "--tags", pin["upstream"], log=log).stdout
        tags = parse_ls_remote(listing)
        if not tags:
            return None
        self.git(home, "fetch", "-q", "--no-tags", pin["upstream"],
                 *[f"+refs/tags/{t}:refs/remotes/upstream/release/{t}" for t in tags], log=log)

        def newer(sha):
            return self.git(home, "merge-base", "--is-ancestor", pin["base"], sha, check=False).returncode == 0
        return select_tag(tags, pin["base"], newer)

    def trade_leagues(self, folder=None):
        if folder is None and self.config["trade_fetch"]:
            request = urllib.request.Request(TRADE_URLS["tencent"]["leagues"],
                                             headers={"User-Agent": "poe2-assistant upstream-watch"})
            with urllib.request.urlopen(request, timeout=60) as response:
                data = json.loads(response.read())
        else:
            data = read_json(Path(folder or self.config["trade_cache"]["tencent"]) / "leagues.json", {})
        return [league["id"] for league in data.get("result", [])]

    def season_due(self, state, leagues, force=False):
        """R03: (mode, reason) for the PoE2DB refresh, or (None, None). Updates state['season']."""
        season = state.setdefault("season", {})
        known = season.get("leagues")
        if known is None:
            known = json.loads(self.home_file("data/trade/leagues.json"))
        new = [lid for lid in leagues if lid not in known]
        if leagues:
            season["leagues"] = sorted(set(known) | set(leagues))
        if new or force:
            season["started"] = stamp()
            season["refreshes"], season["attempts"] = [], []
            season["new_leagues"] = new
            return "season", f"新赛季 {'、'.join(new) or '(手动)'}"
        started = season.get("started")
        if started:
            begun = datetime.fromisoformat(started)
            done = [datetime.fromisoformat(s) for s in season.get("refreshes", []) + season.get("attempts", [])]
            in_window = now() - begun < timedelta(days=self.config["season_days"])
            if in_window and (not done or now() - max(done) >= timedelta(days=self.config["season_every"])):
                return "season", "赛季更新后每周补跑"
        return None, None

    def check(self, retry=False, force_season=False, force_data=False):
        with self.locked():
            state = self.state()
            current = state.get("current")
            if current:
                run = read_json(self.state_dir / "runs" / current / "run.json")
                if run and run["status"] in ("running", "publish-failed"):
                    self.log(f"继续未完成的运行 {current}")
                    return self.execute(run, state)
                if run and run["status"] == "held":
                    self.log(f"运行 {current} 等待放行（release）")
                    return 0
            pins = self.pins()
            targets = {}
            for key, pin in pins.items():
                found = self.find_tag(key, pin)
                handled = state["handled"].get(key, {})
                if found and handled.get("tag") == found["tag"] and handled.get("result") == "failed" and not retry:
                    self.log(f"{key}: {found['tag']} 上次失败，未重试（--retry 可重试）")
                    found = None
                targets[key] = found
            try:
                leagues = self.trade_leagues()
            except Exception as error:  # the daily season check must not block tag runs
                self.log(f"赛季列表读取失败：{error}")
                leagues = []
            mode, reason = self.season_due(state, leagues, force_season)
            if mode is None and any(targets.values()):
                mode, reason = "index", "上游新版本"
            if mode is None and force_data:
                mode, reason = "index", "手动数据刷新"
            if mode is None:
                self.save_state(state)
                self.log("上游无新发布、无赛季刷新：无事可做")
                return 0
            run_id = now().strftime("%Y%m%d-%H%M%S")
            run = {"id": run_id, "created": stamp(), "status": "running", "targets": targets,
                   "data": {"mode": mode, "reason": reason, "refresh_before": stamp()}, "steps": {},
                   "old": {key: {"base": pin["base"], "head": pin["head"]} for key, pin in pins.items()}}
            state["current"] = run_id
            self.save_state(state)
            self.log(f"开始运行 {run_id}：{describe(targets)}（{reason}）")
            return self.execute(run, state)

    def release(self):
        with self.locked():
            state = self.state()
            run = read_json(self.state_dir / "runs" / str(state.get("current")) / "run.json")
            if not run or run["status"] != "held":
                self.log("没有等待放行的运行")
                return 1
            run["status"] = "running"
            run["released"] = stamp()
            return self.execute(run, state)

    # running -----------------------------------------------------------------
    def run_dir(self, run):
        return self.state_dir / "runs" / run["id"]

    def save_run(self, run):
        write_json(self.run_dir(run) / "run.json", run)

    def execute(self, run, state):
        steps = CHECK_STEPS + ["hold"] + PUBLISH_STEPS
        self.paths(run)["logs"].mkdir(parents=True, exist_ok=True)
        self.save_run(run)
        for name in steps:
            if name in run["steps"]:
                continue
            if name == "hold":
                if self.config["hold"] and not run.get("released"):
                    run["status"] = "held"
                    self.save_run(run)
                    self.write_report(run, None)
                    self.notify_once(run, "held", f"PoE2 助手：{describe(run['targets'])} 已通过全部检查，"
                                     f"观察期开关打开，等待放行（upstream_watch.py release）。报告：{self.report_path(run)}")
                    return 0
                run["steps"]["hold"] = {"done": stamp()}
                continue
            self.log(f"== {name}")
            try:
                detail = getattr(self, f"step_{name}")(run) or ""
            except (StepFailed, subprocess.TimeoutExpired, OSError, ValueError, KeyError) as error:
                return self.fail(run, state, name, error)
            run["steps"][name] = {"done": stamp(), "detail": detail}
            self.save_run(run)
            if run.get("nothing"):
                break
        run["status"] = "published" if not run.get("nothing") else "unchanged"
        run["finished"] = stamp()
        self.save_run(run)
        self.write_report(run, None)
        for key, target in run["targets"].items():
            if target:
                state["handled"][key] = {**target, "result": run["status"], "run": run["id"]}
        if run["data"]["mode"] == "season":
            state.setdefault("season", {}).setdefault("refreshes", []).append(run["data"]["refresh_before"])
        state["current"] = None
        self.save_state(state)
        self.log(f"完成：{run['status']}，报告 {self.report_path(run)}")
        return 0

    def fail(self, run, state, step, error):
        publishing = step in PUBLISH_STEPS
        run["status"] = "publish-failed" if publishing else "failed"
        run["failure"] = {"step": step, "error": str(error)[-3000:], "files": getattr(error, "files", []),
                          "log": str(getattr(error, "log", "") or "")}
        self.save_run(run)
        self.write_report(run, run["failure"])
        if not publishing:  # nothing was pushed; the run is over
            for key, target in run["targets"].items():
                if target:
                    state["handled"][key] = {**target, "result": "failed", "run": run["id"]}
            if run["data"]["mode"] == "season":  # next weekly slot, not every day
                state.setdefault("season", {}).setdefault("attempts", []).append(run["data"]["refresh_before"])
            state["current"] = None
            self.save_state(state)
        files = "，".join(run["failure"]["files"][:3])
        what = "冲突" if run["failure"]["files"] else "失败"
        pushed = "部分推送已完成，下次运行会续推" if publishing else "未推送任何内容"
        self.notify_once(run, f"fail:{step}", f"PoE2 助手自动跟随上游{what}：{describe(run['targets'])}，"
                         f"步骤 {step}{'（' + files + '）' if files else ''}。{pushed}。报告：{self.report_path(run)}")
        self.log(f"失败：{step}：{str(error)[-500:]}")
        return 1

    def notify_once(self, run, key, text):
        sent = run.setdefault("notified", [])
        if key in sent:
            return
        result = notify(self.config, text, self.log)
        sent.append(key)
        run.setdefault("notifications", []).append({"key": key, "text": text, **result})
        self.save_run(run)

    def report_path(self, run):
        return self.run_dir(run) / "report.md"

    def write_report(self, run, failure):
        lines = [f"# upstream_watch 运行 {run['id']}", "",
                 f"- 状态：{run['status']}", f"- 目标：{describe(run['targets'])}",
                 f"- 数据：{run['data']['mode']}（{run['data']['reason']}）"]
        for key, target in run["targets"].items():
            if target:
                lines.append(f"- {key}: {run['old'][key]['base'][:10]} → {target['tag']} {target['sha'][:10]}")
        if failure:
            lines += ["", "## 失败", f"- 步骤：{failure['step']}", f"- 文件：{', '.join(failure['files']) or '无'}",
                      f"- 日志：{failure['log'] or self.run_dir(run) / 'logs'}", "", "```", failure["error"], "```"]
        lines += ["", "## 步骤"] + [f"- {k}: {v['done']} {v.get('detail', '')}" for k, v in run["steps"].items()]
        lines += ["", f"目录：{self.run_dir(run)}"]
        self.report_path(run).parent.mkdir(parents=True, exist_ok=True)
        self.report_path(run).write_text("\n".join(lines) + "\n", encoding="utf-8")

    # steps -------------------------------------------------------------------
    def paths(self, run):
        d = self.run_dir(run)
        return {"dir": d, "project": d / "project", "rebase": d / "rebase", "pob": d / "pob",
                "engine": d / "engine", "logs": d / "logs", "sources": d / "sources"}

    def fresh(self, path):
        if path.exists():
            shutil.rmtree(path)
        return path

    def step_prepare(self, run):
        p = self.paths(run)
        log = p["logs"] / "prepare.log"
        self.git(p["dir"], "clone", "-q", "-b", self.config["project_branch"],
                 expand(self.config["project_home"]), self.fresh(p["project"]), log=log)
        run["old"]["project"] = self.git(p["project"], "rev-parse", "HEAD").stdout.strip()
        pins = self.pins(p["project"])
        for key, pin in pins.items():
            actual = self.git(expand(pin["home"]), "rev-parse", f"refs/heads/{pin.get('name') or pin['branch']}",
                              log=log).stdout.strip()
            if actual != pin["head"]:
                raise StepFailed(f"{key}: 固定值 head {pin['head'][:10]} 与 {pin['home']} 分支 {actual[:10]} 不一致",
                                 files=[f"sources/{PINS[key]}"], log=log)
            run["old"][key] = {"base": pin["base"], "head": pin["head"]}
        # the pins rebase_check reads (old base, overrides applied)
        self.fresh(p["sources"]).mkdir(parents=True)
        for key, pin in pins.items():
            write_json(p["sources"] / PINS[key], pin)
        return f"project {run['old']['project'][:10]}"

    def step_rebase(self, run):
        p = self.paths(run)
        log = p["logs"] / "rebase.log"
        pob, ee2 = run["targets"].get("pob"), run["targets"].get("ee2")
        cmd = [sys.executable, "-B", p["project"] / "ops/rebase_check.py", "--work", self.fresh(p["rebase"]),
               "--sources", p["sources"], "--pob-suite",
               "--pob-onto", f"upstream/release/{pob['tag']}" if pob else run["old"]["pob"]["base"]]
        cmd += ["--ee2-onto", ee2["sha"]] if ee2 else ["--skip-ee2"]
        result = self.sh(cmd, cwd=p["project"], log=log, check=False, timeout=self.config["timeouts"]["rebase"])
        report = read_json(p["rebase"] / "report.json", {})
        conflicts = [f for r in report.values() for c in r.get("conflicts", []) for f in c["files"]]
        failed = [f"{k}: {c['check']}" for k, r in report.items() for c in r.get("checks", []) if not c["ok"]]
        if conflicts:
            raise StepFailed("变基冲突：" + "; ".join(
                f"{k} {c['commit']}: {', '.join(c['files'])}" for k, r in report.items() for c in r["conflicts"]),
                files=conflicts, log=log)
        if failed or result.returncode or not report:
            raise StepFailed("检查失败：" + ("; ".join(failed) or f"rebase_check exit {result.returncode}"), log=log)
        run["new"] = {key: report[key]["head"] for key in report}
        run["rebased"] = dict(run["new"])
        return "; ".join(f"{k} {v[:10]}" for k, v in run["new"].items())

    def step_engine(self, run):
        p = self.paths(run)
        pob = run["targets"].get("pob")
        commit = pob["sha"] if pob else read_json(p["project"] / "sources/pob.json")["commit"]
        home = expand(self.pins(p["project"])["pob"]["home"])
        log = p["logs"] / "engine.log"
        self.git(p["dir"], "clone", "-q", "--no-checkout", home, self.fresh(p["engine"]), log=log)
        self.git(p["engine"], "checkout", "-q", "--detach", commit, log=log)
        # the rebased PoB branch, as a work tree for the generated PoB files
        self.git(p["dir"], "clone", "-q", "--no-checkout", p["rebase"] / "pob", self.fresh(p["pob"]), log=log)
        self.git(p["pob"], "checkout", "-q", "-B", "poe2-assistant", run["new"]["pob"], log=log)
        return f"engine {commit[:10]}"

    def step_data(self, run):
        p = self.paths(run)
        log = p["logs"] / "data.log"
        pob = run["targets"].get("pob")
        if pob:  # the engine pin moves first: the generated tables record it
            pin = read_json(p["project"] / "sources/pob.json")
            pin["commit"] = pob["sha"]
            write_json(p["project"] / "sources/pob.json", pin)
        cmd = [sys.executable, "-B", p["project"] / "ops/poe2db_update.py", "--engine", p["engine"],
               "--pob-tree", p["pob"], "--luajit", expand(self.config["luajit"]),
               "--lua-cpath", self.config["lua_cpath"]]
        if not self.config["fetch"]:
            cmd.append("--offline")
        elif run["data"]["mode"] == "season":
            cmd += ["--refresh-before", run["data"]["refresh_before"]]
        else:
            cmd += ["--refresh-index", str(self.config["index_max_age"])]
        self.sh(cmd, cwd=p["project"], log=log, timeout=self.config["timeouts"]["data"])
        # offline PoB indexes (sources/pob-*.json) follow the engine pin; gems last (it reads the name tables)
        for name, out in INDEXES:
            self.sh([sys.executable, "-B", p["project"] / f"scripts/index_pob_{name}.py", p["engine"],
                     p["project"] / "sources" / out], cwd=p["project"], log=log)
        trade = self.trade_inputs(run, log)
        self.sh([sys.executable, "-B", p["project"] / "ops/trade_data_prep.py", "--tencent", trade["tencent"],
                 "--intl", trade["intl"], "--out", p["project"] / "data/trade"], cwd=p["project"], log=log)
        return f"{run['data']['mode']}，" + ("联网" if self.config["fetch"] else "离线")

    def trade_inputs(self, run, log):
        if not self.config["trade_fetch"]:
            return {k: expand(v) for k, v in self.config["trade_cache"].items()}
        out = {}
        for server, urls in TRADE_URLS.items():
            folder = self.paths(run)["dir"] / "trade" / server
            folder.mkdir(parents=True, exist_ok=True)
            for name, url in urls.items():
                request = urllib.request.Request(url, headers={"User-Agent": "poe2-assistant upstream-watch"})
                with urllib.request.urlopen(request, timeout=60) as response:
                    (folder / f"{name}.json").write_bytes(response.read())
                with open(log, "a", encoding="utf-8") as handle:
                    handle.write(f"GET {url} ok\n")
            out[server] = folder
        return out

    def step_commit(self, run):
        p = self.paths(run)
        log = p["logs"] / "commit.log"
        # resumable: undo a commit an interrupted attempt made, keep the generated files
        run["new"]["pob"] = run["rebased"]["pob"]
        self.git(p["pob"], "reset", "-q", "--soft", run["rebased"]["pob"], log=log)
        self.git(p["project"], "reset", "-q", "--soft", run["old"]["project"], log=log)
        pob = self.git(p["pob"], "status", "--porcelain", "--", *POB_DATA, log=log).stdout.split("\n")
        if [line for line in pob if line.strip()] and only_project_commit_changed(p["pob"], self):
            self.git(p["pob"], "checkout", "--", "poe2-assistant/terms/source.json", log=log)
        if self.git(p["pob"], "status", "--porcelain", "--", *POB_DATA, log=log).stdout.strip():
            self.git(p["pob"], "add", "-A", "--", *POB_DATA, log=log)
            self.git(p["pob"], "commit", "-q", "-m", f"U05: refresh PoE2DB display tables\n\n{TRAILER}", log=log)
        head = self.git(p["pob"], "rev-parse", "HEAD", log=log).stdout.strip()
        run["pob_data_commit"] = head != run["new"]["pob"]
        run["new"]["pob"] = head
        pins = {key: read_json(p["project"] / "sources" / name) for key, name in PINS.items()}
        for key, target in run["targets"].items():
            if target:
                pins[key]["base"] = target["sha"]
            if key in run["new"]:
                pins[key]["head"] = run["new"][key]
            write_json(p["project"] / "sources" / PINS[key], pins[key])
        self.git(p["project"], "add", "-A", "sources", "data", log=log)
        if not self.git(p["project"], "diff", "--cached", "--quiet", log=log, check=False).returncode:
            run["nothing"] = True  # same tables, no new tag: nothing to publish
            return "无变化"
        subject = (f"U05: follow upstream {describe(run['targets'])}" if any(run["targets"].values())
                   else f"R03: PoE2DB/trade data refresh ({run['data']['reason']})")
        self.git(p["project"], "commit", "-q", "-m", f"{subject}\n\nrun {run['id']}\n\n{TRAILER}", log=log)
        run["new"]["project"] = self.git(p["project"], "rev-parse", "HEAD").stdout.strip()
        return f"project {run['new']['project'][:10]}, pob {head[:10]}"

    def step_recheck(self, run):
        """PoB checks again on the data commit, with the new pins and tables of the private repo."""
        p = self.paths(run)
        log = p["logs"] / "recheck.log"
        stage = self.fresh(p["dir"] / "stage-pob.git")
        self.git(p["dir"], "init", "-q", "--bare", stage, log=log)
        self.git(p["pob"], "push", "-q", stage, f"{run['new']['pob']}:refs/heads/poe2-assistant", log=log)
        self.git(p["rebase"] / "pob", "push", "-q", stage, "+refs/remotes/upstream/*:refs/remotes/upstream/*", log=log)
        sources = self.fresh(p["dir"] / "sources-recheck")
        sources.mkdir()
        pin = {**read_json(p["project"] / "sources/pob-branch.json"), "home": str(stage), "name": "poe2-assistant"}
        write_json(sources / "pob-branch.json", pin)
        write_json(sources / "ee2.json", read_json(p["project"] / "sources/ee2.json"))
        work = self.fresh(p["dir"] / "recheck")
        result = self.sh([sys.executable, "-B", p["project"] / "ops/rebase_check.py", "--work", work,
                          "--sources", sources, "--skip-ee2", "--pob-suite", "--pob-onto", pin["base"]],
                         cwd=p["project"], log=log, check=False, timeout=self.config["timeouts"]["rebase"],
                         env={"POB_EXPORT_ENGINE": str(p["engine"])})  # the new pinned engine checkout
        report = read_json(work / "report.json", {}).get("pob", {})
        failed = [c["check"] for c in report.get("checks", []) if not c["ok"]]
        if result.returncode or failed or report.get("head") != run["new"]["pob"]:
            raise StepFailed("数据提交后的 PoB 检查失败：" + ("; ".join(failed) or f"exit {result.returncode}"), log=log)
        return f"{len(report['checks'])} 项通过"

    def step_export(self, run):
        p = self.paths(run)
        log = p["logs"] / "export.log"
        export = self.fresh(p["dir"] / "export")
        self.sh([sys.executable, "-B", p["project"] / "ops/export_public.py", "--out", export,
                 "--commit", "HEAD", "--no-git"], cwd=p["project"], log=log)
        terms = expand(self.config["public_terms"])
        self.sh([sys.executable, "-B", p["project"] / "ops/check_public.py", export,
                 *(["--terms", terms] if terms.exists() else [])], cwd=p["project"], log=log)
        public = self.fresh(p["dir"] / "public")
        self.git(p["dir"], "clone", "-q", "-b", self.config["public_branch"], self.config["public_remote"], public,
                 log=log)
        self.git(public, "rm", "-rq", "--ignore-unmatch", ".", log=log)
        for item in export.iterdir():
            target = public / item.name
            (shutil.copytree if item.is_dir() else shutil.copy2)(item, target)
        self.git(public, "add", "-A", log=log)
        if self.git(public, "diff", "--cached", "--quiet", log=log, check=False).returncode:
            self.git(public, "commit", "-q", "-m",
                     f"Sync: {describe(run['targets'])} ({run['data']['reason']})\n\n{TRAILER}", log=log)
        run["new"]["public"] = self.git(public, "rev-parse", "HEAD").stdout.strip()
        return f"public {run['new']['public'][:10]}"

    def push(self, repo, remote, ref, new, old, log):
        """Move remote `ref` from old to new; skip when already there; lease on old otherwise."""
        current = self.git(repo, "ls-remote", remote, f"refs/heads/{ref}", log=log).stdout.split()
        current = current[0] if current else None
        if current == new:
            return "已是目标"
        if current != old:
            raise StepFailed(f"{remote} {ref} 在 {current} 而不是预期的 {old}，停止（不覆盖他人改动）", log=log)
        self.git(repo, "push", "-q", f"--force-with-lease=refs/heads/{ref}:{old}", remote,
                 f"{new}:refs/heads/{ref}", log=log)
        return "已推送"

    def step_push_forks(self, run):
        p = self.paths(run)
        log = p["logs"] / "publish.log"
        out = []
        for key, repo in (("pob", p["pob"]), ("ee2", p["rebase"] / "ee2")):
            if key not in run["new"] or run["new"][key] == run["old"][key]["head"]:
                continue
            pin = self.pins(p["project"])[key]
            out.append(f"{key} fork " + self.push(repo, self.config["forks"][key], pin.get("name") or pin["branch"],
                                                  run["new"][key], run["old"][key]["head"], log))
        return "; ".join(out) or "无"

    def step_push_homes(self, run):
        p = self.paths(run)
        log = p["logs"] / "publish.log"
        out = []
        for key, repo in (("pob", p["pob"]), ("ee2", p["rebase"] / "ee2")):
            if key not in run["new"] or run["new"][key] == run["old"][key]["head"]:
                continue
            pin = self.pins(p["project"])[key]
            home, branch = expand(pin["home"]), pin.get("name") or pin["branch"]
            self.git(home, "update-ref", f"refs/backup/upstream-watch/{run['id']}/{branch}", run["old"][key]["head"],
                     log=log)
            out.append(f"{key} home " + self.push(repo, home, branch, run["new"][key], run["old"][key]["head"], log))
        return "; ".join(out) or "无"

    def step_push_private(self, run):
        p = self.paths(run)
        return self.push(p["project"], expand(self.config["project_home"]), self.config["project_branch"],
                         run["new"]["project"], run["old"]["project"], p["logs"] / "publish.log")

    def step_push_public(self, run):
        p = self.paths(run)
        public = p["dir"] / "public"
        old = self.git(public, "rev-parse", f"origin/{self.config['public_branch']}").stdout.strip()
        if old == run["new"]["public"]:
            return "公开仓库无变化"
        return self.push(public, self.config["public_remote"], self.config["public_branch"], run["new"]["public"],
                         old, p["logs"] / "publish.log")


def only_project_commit_changed(pob_tree, watcher):
    """True when the PoB data change is nothing but source.json's project_commit (no new tables)."""
    changed = [line[3:] for line in watcher.git(pob_tree, "status", "--porcelain", "--", *POB_DATA).stdout.splitlines()
               if line.strip()]
    if changed != ["poe2-assistant/terms/source.json"]:
        return False
    old = json.loads(watcher.git(pob_tree, "show", "HEAD:poe2-assistant/terms/source.json").stdout)
    new = read_json(Path(pob_tree) / "poe2-assistant/terms/source.json")
    old.pop("project_commit", None)
    new.pop("project_commit", None)
    return old == new


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["check", "release", "status", "notify-test"])
    parser.add_argument("--config", default=str(CONFIG))
    parser.add_argument("--retry", action="store_true", help="retry a tag that failed before")
    parser.add_argument("--season", action="store_true", help="start an R03 season refresh now")
    parser.add_argument("--data", action="store_true", help="refresh data even without a new tag")
    args = parser.parse_args(argv)
    config = load_config(args.config)
    watcher = Watcher(config)
    if args.command == "check":
        return watcher.check(args.retry, args.season, args.data)
    if args.command == "release":
        return watcher.release()
    if args.command == "notify-test":
        notify(config, "PoE2 助手：upstream_watch 通知测试（无需处理）。")
        return 0
    state = watcher.state()
    print(json.dumps({"config": {k: config[k] for k in ("hold", "notify", "fetch", "trade_fetch")}, **state},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
