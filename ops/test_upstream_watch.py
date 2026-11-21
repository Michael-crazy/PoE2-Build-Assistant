import json
from datetime import timedelta
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import upstream_watch as uw

BASE = "b" * 40


class TagTests(unittest.TestCase):
    LISTING = "\n".join([
        f"{'1' * 40}\trefs/tags/v2.60.0",          # PoE1 tag in the PoB repo
        f"{'2' * 40}\trefs/tags/v0.23.1",          # older than our base
        f"{'3' * 40}\trefs/tags/v0.24.0",          # annotated: the peeled commit counts
        f"{'4' * 40}\trefs/tags/v0.24.0^{{}}",
        f"{'5' * 40}\trefs/tags/v0.24.1",
        f"{'6' * 40}\trefs/tags/v0.9.9",
        f"{'7' * 40}\trefs/tags/v0.25.0-beta",
        f"{'8' * 40}\trefs/tags/latest",
    ])

    def test_parse_only_v0_tags(self):
        tags = uw.parse_ls_remote(self.LISTING)
        self.assertEqual(set(tags), {"v0.23.1", "v0.24.0", "v0.24.1", "v0.9.9"})
        self.assertEqual(tags["v0.24.0"], "4" * 40)

    def test_select_newest_descendant(self):
        tags = uw.parse_ls_remote(self.LISTING)
        newer = {"4" * 40, "5" * 40, "6" * 40}
        self.assertEqual(uw.select_tag(tags, BASE, newer.__contains__), {"tag": "v0.24.1", "sha": "5" * 40})
        # v0.24.1 not on top of our base (e.g. a hotfix branch): v0.24.0 wins; v0.9.9 < v0.24.0 numerically
        self.assertEqual(uw.select_tag(tags, BASE, {"4" * 40, "6" * 40}.__contains__)["tag"], "v0.24.0")

    def test_base_itself_and_older_tags_are_not_new(self):
        tags = {"v0.23.1": "2" * 40, "v0.23.2": BASE}
        self.assertIsNone(uw.select_tag(tags, BASE, lambda sha: sha != "2" * 40))  # v0.23.1 is an ancestor of base
        self.assertIsNone(uw.select_tag({"v2.61.0": "9" * 40}, BASE, lambda sha: True))


class NotifyTests(unittest.TestCase):
    def test_dry_run_prints_command_and_sends_nothing(self):
        config = uw.load_config("/nonexistent.json")
        lines = []
        with mock.patch.object(uw.subprocess, "run", side_effect=AssertionError("must not run")):
            result = uw.notify(config, "PoE2 助手：测试。报告：/x/report.md", lines.append)
        self.assertEqual(result["mode"], "dry-run")
        self.assertTrue(result["command"][0].endswith(".npm-global/bin/openclaw"))
        self.assertEqual(result["command"][1:4], ["agent", "--agent", "main"])
        self.assertEqual(result["command"][-1], "--deliver")
        self.assertIn("--message", result["command"])
        self.assertTrue(any("[通知 dry-run]" in line and "--deliver" in line for line in lines))
        self.assertTrue(any("报告：/x/report.md" in line for line in lines))

    def test_send_puts_node_24_first(self):
        config = {**uw.load_config("/nonexistent.json"), "notify": "send"}
        with mock.patch.object(uw.subprocess, "run") as run:
            run.return_value = mock.Mock(returncode=0, stdout="ok", stderr="")
            uw.notify(config, "x", lambda m: None)
        env = run.call_args.kwargs["env"]
        self.assertTrue(env["PATH"].startswith(str(Path.home() / ".nvm/versions/node/v24.22.1/bin") + ":"))


class Recorder(uw.Watcher):
    """A watcher whose steps only record their calls; `fail_at` raises in that step."""

    def __init__(self, config, fail_at=None, files=()):
        super().__init__(config, log=lambda m: None)
        self.calls, self.fail_at, self.files = [], fail_at, files
        for name in uw.CHECK_STEPS + uw.PUBLISH_STEPS:
            setattr(self, f"step_{name}", self.recorder(name))

    def recorder(self, name):
        def step(run):
            self.calls.append(name)
            if name == self.fail_at:
                raise uw.StepFailed(f"{name} broke", files=self.files, log="/x/logs/rebase.log")
            return "ok"
        return step


class RunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config = {**uw.load_config("/nonexistent.json"), "state": self.tmp.name}

    def tearDown(self):
        self.tmp.cleanup()

    def run_dict(self, steps=()):
        return {"id": "r1", "created": uw.stamp(), "status": "running",
                "targets": {"pob": {"tag": "v0.24.0", "sha": "4" * 40}, "ee2": None},
                "data": {"mode": "index", "reason": "上游新版本", "refresh_before": uw.stamp()},
                "steps": {s: {"done": "t"} for s in steps},
                "old": {"pob": {"base": BASE, "head": "c" * 40}, "ee2": {"base": BASE, "head": "d" * 40}}}

    def test_conflict_stops_before_any_push(self):
        w = Recorder(self.config, fail_at="rebase", files=["src/Modules/Build.lua"])
        state = {"handled": {}, "season": {}, "current": "r1"}
        self.assertEqual(w.execute(self.run_dict(), state), 1)
        self.assertEqual(w.calls, ["prepare", "rebase"])
        self.assertFalse(set(w.calls) & set(uw.PUBLISH_STEPS))
        run = json.loads((Path(self.tmp.name) / "runs/r1/run.json").read_text(encoding="utf-8"))
        self.assertEqual(run["status"], "failed")
        report = (Path(self.tmp.name) / "runs/r1/report.md").read_text(encoding="utf-8")
        self.assertIn("步骤：rebase", report)
        self.assertIn("src/Modules/Build.lua", report)
        self.assertIn("/x/logs/rebase.log", report)
        text = run["notifications"][0]["text"]
        self.assertEqual(run["notifications"][0]["mode"], "dry-run")
        self.assertIn("冲突", text)
        self.assertIn("未推送任何内容", text)
        self.assertIn(str(Path(self.tmp.name) / "runs/r1/report.md"), text)
        self.assertEqual(state["handled"]["pob"]["result"], "failed")
        self.assertIsNone(state["current"])

    def test_every_check_failure_blocks_publishing(self):
        for step in uw.CHECK_STEPS:
            w = Recorder(self.config, fail_at=step)
            w.execute(self.run_dict(), {"handled": {}, "season": {}, "current": "r1"})
            self.assertEqual(w.calls[-1], step)
            self.assertFalse(set(w.calls) & set(uw.PUBLISH_STEPS), step)

    def test_resume_skips_finished_steps(self):
        w = Recorder(self.config)
        state = {"handled": {}, "season": {}, "current": "r1"}
        self.assertEqual(w.execute(self.run_dict(["prepare", "rebase", "engine"]), state), 0)
        self.assertEqual(w.calls, ["data", "commit", "recheck", "export"] + uw.PUBLISH_STEPS)
        self.assertEqual(state["handled"]["pob"]["result"], "published")

    def test_failed_push_resumes_at_that_push(self):
        w = Recorder(self.config, fail_at="push_private")
        state = {"handled": {}, "season": {}, "current": "r1"}
        self.assertEqual(w.execute(self.run_dict(), state), 1)
        run = json.loads((Path(self.tmp.name) / "runs/r1/run.json").read_text(encoding="utf-8"))
        self.assertEqual(run["status"], "publish-failed")
        self.assertEqual(state["current"], "r1")          # kept: the next check continues it
        self.assertIn("下次运行会续推", run["notifications"][0]["text"])
        w2 = Recorder(self.config)
        self.assertEqual(w2.execute(run, state), 0)
        self.assertEqual(w2.calls, ["push_private", "push_public"])

    def test_hold_switch_waits_for_release(self):
        config = {**self.config, "hold": True}
        w = Recorder(config)
        state = {"handled": {}, "season": {}, "current": "r1"}
        self.assertEqual(w.execute(self.run_dict(), state), 0)
        self.assertEqual(w.calls, uw.CHECK_STEPS)
        run = json.loads((Path(self.tmp.name) / "runs/r1/run.json").read_text(encoding="utf-8"))
        self.assertEqual(run["status"], "held")
        self.assertIn("等待放行", run["notifications"][0]["text"])
        w.save_state(state)
        w2 = Recorder(config)
        self.assertEqual(w2.release(), 0)
        self.assertEqual(w2.calls, uw.PUBLISH_STEPS)

    def test_failed_tag_not_retried_without_flag(self):
        w = Recorder(self.config)
        w.save_state({"handled": {"pob": {"tag": "v0.24.0", "sha": "4" * 40, "result": "failed"}},
                      "season": {"leagues": ["永久"]}, "current": None})
        w.pins = lambda root=None: {"pob": {"base": BASE, "head": "c" * 40}, "ee2": {"base": BASE, "head": "d" * 40}}
        w.find_tag = lambda key, pin, log=None: {"tag": "v0.24.0", "sha": "4" * 40} if key == "pob" else None
        w.trade_leagues = lambda folder=None: ["永久"]
        self.assertEqual(w.check(), 0)
        self.assertEqual(w.calls, [])
        self.assertEqual(w.check(retry=True), 0)
        self.assertEqual(w.calls[0], "prepare")


class SeasonTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.w = uw.Watcher({**uw.load_config("/nonexistent.json"), "state": self.tmp.name}, log=lambda m: None)

    def tearDown(self):
        self.tmp.cleanup()

    def test_new_league_starts_season_then_weekly_for_two_weeks(self):
        state = {"season": {"leagues": ["永久", "旧赛季"]}}
        self.assertEqual(self.w.season_due(state, ["永久", "旧赛季"])[0], None)
        mode, reason = self.w.season_due(state, ["永久", "新赛季"])
        self.assertEqual(mode, "season")
        self.assertIn("新赛季", reason)
        start = uw.datetime.fromisoformat(state["season"]["started"])
        state["season"]["refreshes"] = [uw.stamp(start)]
        with mock.patch.object(uw, "now", return_value=start + timedelta(days=3)):
            self.assertIsNone(self.w.season_due(state, ["永久", "新赛季"])[0])
        with mock.patch.object(uw, "now", return_value=start + timedelta(days=7, hours=1)):
            self.assertEqual(self.w.season_due(state, ["永久", "新赛季"]), ("season", "赛季更新后每周补跑"))
        state["season"]["refreshes"].append(uw.stamp(start + timedelta(days=7, hours=1)))
        with mock.patch.object(uw, "now", return_value=start + timedelta(days=14, hours=2)):
            self.assertIsNone(self.w.season_due(state, ["永久", "新赛季"])[0])


if __name__ == "__main__":
    unittest.main()
