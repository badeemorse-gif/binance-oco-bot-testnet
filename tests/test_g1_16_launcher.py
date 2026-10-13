import importlib.util
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(path):
    with open(path, encoding="utf-8", errors="ignore") as f:
        return f.read()


class G116LauncherTest(unittest.TestCase):
    """G1.16 (G-LAUNCH-01): no-console shortcut that opens the GUI from the project root."""

    def test_module_entry_point_resolvable(self):
        spec = importlib.util.find_spec("ocobot.ui.app")
        self.assertIsNotNone(spec, "ocobot.ui.app module not found")

    def test_vbs_launcher_present_no_console(self):
        path = os.path.join(ROOT, "OCOBot.vbs")
        self.assertTrue(os.path.isfile(path), "OCOBot.vbs missing in project root")
        text = _read(path)
        self.assertIn("pythonw", text)
        self.assertIn("ocobot.ui.app", text)
        self.assertIn("CurrentDirectory", text)

    def test_generator_present(self):
        path = os.path.join(ROOT, "tools", "create_OCOBot_shortcut.ps1")
        self.assertTrue(os.path.isfile(path), "tools/create_OCOBot_shortcut.ps1 missing")
        text = _read(path)
        self.assertIn("pythonw", text)
        self.assertIn("-m ocobot.ui.app", text)
        self.assertIn("WorkingDirectory", text)
        self.assertIn("OCOBot.lnk", text)

    def test_shortcut_generated(self):
        path = os.path.join(ROOT, "OCOBot.lnk")
        self.assertTrue(os.path.isfile(path), "OCOBot.lnk missing in project root")


if __name__ == "__main__":
    unittest.main()
