import hashlib
from pathlib import Path
import subprocess
import sys
import unittest

from pob_trial import trial

FIXTURE = Path(__file__).resolve().parents[1] / "tests/fixtures/p02"


class TrialTests(unittest.TestCase):
    def run_trial(self, mode="ok", timeout=2):
        return trial(FIXTURE / "build.xml", FIXTURE / "item.txt", "Weapon 1",
                     [sys.executable, str(FIXTURE / "worker.py"), mode], timeout)

    def test_baseline_replacement_and_unchanged_input(self):
        paths = [FIXTURE / "build.xml", FIXTURE / "item.txt"]
        before = [hashlib.sha256(path.read_bytes()).digest() for path in paths]
        result = self.run_trial()
        self.assertEqual(result["baseline"]["CombinedDPS"], 100)
        self.assertEqual(result["replacement"]["CombinedDPS"], 120)
        self.assertEqual(result["delta"], dict(CombinedDPS=20, Life=0, EnergyShield=100, Armour=0, Evasion=0))
        self.assertEqual(before, [hashlib.sha256(path.read_bytes()).digest() for path in paths])

    def test_reject_bad_responses(self):
        for mode in ("exit", "malformed", "digest", "version", "missing", "nan", "boolean"):
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                self.run_trial(mode)

    def test_timeout(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            self.run_trial("timeout", timeout=0.1)

    def test_missing_executable(self):
        with self.assertRaises(FileNotFoundError):
            trial(FIXTURE / "build.xml", FIXTURE / "item.txt", "Weapon 1", ["/missing/pob-worker"])

    def test_cli(self):
        result = subprocess.run([sys.executable, str(Path(__file__).with_name("pob_trial.py")),
                                 "--build", str(FIXTURE / "build.xml"), "--item", str(FIXTURE / "item.txt"),
                                 "--slot", "Weapon 1", "--", sys.executable, str(FIXTURE / "worker.py")],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('"delta"', result.stdout)


if __name__ == "__main__":
    unittest.main()
