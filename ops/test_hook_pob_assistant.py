import unittest

from hook_pob_assistant import BEGIN, hook

LAUNCH = """\tif errMsg then
\t\tself:ShowErrMsg("In 'Init': %s", errMsg)
\tend

\tif not self.devMode and not firstRunFile then
\t\tself:CheckForUpdate(true)
\tend
"""


class HookTests(unittest.TestCase):
    def test_hook_runs_before_the_update_check_and_replays_cleanly(self):
        hooked = hook(LAUNCH)
        self.assertLess(hooked.index(BEGIN), hooked.index("if not self.devMode"))
        self.assertIn('SpawnProcess(assistant, "--pob-pid=" ..', hooked)
        self.assertEqual(hook(hooked), hooked)
        self.assertEqual(hooked.count(BEGIN), 1)

    def test_unknown_launch_file_is_refused(self):
        with self.assertRaises(ValueError):
            hook("launch = {}\n")


if __name__ == "__main__":
    unittest.main()
