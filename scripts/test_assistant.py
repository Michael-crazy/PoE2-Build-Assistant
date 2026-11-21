"""Linux tests of process launch without a Windows runtime or Wine."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from assistant import launch_pob
from build_estimate import aggregate_quotes


ENTRY = Path(__file__).with_name("assistant.py")
FIXTURE = ENTRY.parent.parent / "tests/fixtures/m04/quotes.synthetic.json"


class EstimateTests(unittest.TestCase):
    def run_cli(self, path):
        return subprocess.run(
            [sys.executable, "-B", str(ENTRY), "estimate-build", str(path)],
            capture_output=True, text=True, timeout=5,
        )

    def test_authored_fixture_through_assistant(self):
        data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        result = self.run_cli(FIXTURE)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        output = json.loads(result.stdout)
        self.assertEqual(output, aggregate_quotes(data["slots"], **data["context"]))
        self.assertEqual(output["quoted_slot_count"], 3)
        self.assertEqual(output["subtotals_by_currency"], {"divine": 2, "exalted": .3})
        self.assertEqual(output["missing_slots"], [
            {"slot": "Boots", "reason": "missing_price"},
            {"slot": "Gloves", "reason": "missing_listing"},
        ])

    def test_input_failures_have_no_partial_output(self):
        data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        data["slots"][-1]["listing"] = data["slots"][0]["listing"].copy()
        data["slots"][-1]["listing"]["league"] = "Other League"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "quotes.json"
            for content in ("{", "null", json.dumps(data)):
                path.write_text(content, encoding="utf-8")
                result = self.run_cli(path)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, "")
                self.assertIn("整套估价汇总失败", result.stderr)
                self.assertNotIn("Traceback", result.stderr)
            path.unlink()
            result = self.run_cli(path)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stdout, "")
            self.assertNotIn("Traceback", result.stderr)


class LaunchTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "posix", "Linux fake executable")
    def test_launches_selected_executable_with_its_directory_and_no_arguments(self):
        with tempfile.TemporaryDirectory(prefix="pob 测试 & ") as directory:
            root = Path(directory)
            executable = root / "Path of Building-PoE2.exe"
            executable.write_text(
                f"#!{sys.executable}\n"
                "import json, os, pathlib, sys\n"
                "pathlib.Path('observed.json').write_text(json.dumps(\n"
                "    {'cwd': os.getcwd(), 'argv': sys.argv}))\n",
                encoding="utf-8",
            )
            executable.chmod(0o755)
            process = launch_pob(executable)
            try:
                self.assertEqual(process.wait(timeout=5), 0)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
            observed = json.loads((root / "observed.json").read_text())
            self.assertEqual(observed, {"cwd": str(root), "argv": [str(executable)]})

    def run_cli(self, *arguments):
        return subprocess.run(
            [sys.executable, "-B", str(ENTRY), "launch-pob", *arguments],
            capture_output=True, text=True, timeout=5,
        )

    def test_requires_explicit_selection(self):
        result = self.run_cli()
        self.assertEqual(result.returncode, 2)
        self.assertIn("--pob-exe", result.stderr)

    def test_missing_file_reports_failure_without_traceback(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_cli("--pob-exe", str(Path(directory) / "missing.exe"))
        self.assertEqual(result.returncode, 1)
        self.assertIn("无法启动 PoB", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_rejects_directory_and_non_executable_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "pob.cmd"
            script.write_text("echo unexpected")
            for path in (root, script):
                with self.subTest(path=path), self.assertRaises(ValueError):
                    launch_pob(path)

    @unittest.skipUnless(os.name == "posix", "Linux execute permission failure")
    def test_process_creation_failure_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "pob.exe"
            executable.write_text("not executable")
            result = self.run_cli("--pob-exe", str(executable))
        self.assertEqual(result.returncode, 1)
        self.assertIn("无法启动 PoB", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
