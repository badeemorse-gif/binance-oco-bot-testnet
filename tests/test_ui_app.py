import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest

from ocobot.ui._qt import QApplication, Qt
from ocobot.ui.theme import PALETTE, contrast_ratio, apply_theme
from ocobot.ui.main_window import MainWindow
from ocobot.ui.app import build_app


class UIAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    def test_app_layout_is_rtl(self):
        self.assertEqual(
            self.app.layoutDirection(), Qt.LayoutDirection.RightToLeft
        )

    def test_palette_tokens_exact(self):
        self.assertEqual(PALETTE["BG"], "#031021")
        self.assertEqual(PALETTE["TEXT"], "#f0f7fb")
        self.assertEqual(PALETTE["GREEN"], "#19c58b")
        self.assertEqual(PALETTE["RED"], "#ff4b68")
        self.assertEqual(PALETTE["SIDEBAR"], "#020d1c")
        self.assertEqual(PALETTE["CARD"], "#061529")
        self.assertEqual(PALETTE["BORDER"], "#0d2a43")
        self.assertEqual(PALETTE["BLUE"], "#0876e8")
        self.assertEqual(PALETTE["AMBER"], "#f08f1b")

    def test_dark_theme_applied_no_light_mix(self):
        from ocobot.ui._qt import QColor, QPalette

        window_color = self.app.palette().color(QPalette.ColorRole.Window)
        self.assertEqual(window_color.name(), QColor(PALETTE["BG"]).name())

    def test_wcag_aa_contrast(self):
        self.assertGreaterEqual(
            contrast_ratio(PALETTE["TEXT"], PALETTE["BG"]), 4.5
        )

    def test_font_is_tajawal(self):
        self.assertEqual(self.app.font().family(), "Tajawal")

    def test_main_window_boots(self):
        window = MainWindow()
        self.assertEqual(window.windowTitle(), "OCOBot")
        self.assertEqual(
            window.layoutDirection(), Qt.LayoutDirection.RightToLeft
        )

    # --- G1.3: build_app يمرّر select_fn إلى MainWindow (حقن Live context) ---

    def test_build_app_forwards_select_fn(self):
        marker = lambda oid: None
        app, window = build_app(select_fn=marker)
        self.assertIs(window._select_fn, marker)


if __name__ == "__main__":
    unittest.main()
