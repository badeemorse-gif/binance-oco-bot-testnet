"""G1.32b chunk_1 — اختبارات بطاقة القوس في شاشة المراقبة (Qt offscreen)."""
import unittest
from decimal import Decimal


class TestBracketUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from ocobot.ui._qt import QApplication
        cls._app = QApplication.instance() or QApplication([])

    def _screen(self):
        from ocobot.ui.monitoring import DynamicMonitoringScreen
        return DynamicMonitoringScreen()

    def test_bracket_card_present(self):
        from ocobot.ui._qt import QFrame
        s = self._screen()
        self.assertIsNotNone(s.findChild(QFrame, "MonitoringBracketCard"))

    def test_default_disabled(self):
        cfg = self._screen().bracket_config()
        self.assertFalse(cfg.enabled)

    def test_bracket_config_reads_inputs(self):
        s = self._screen()
        s._bracket_enable_toggle.setChecked(True)
        s._bracket_upper_edit.setText("2.5")
        s._bracket_lower_edit.setText("1.5")
        cfg = s.bracket_config()
        self.assertTrue(cfg.enabled)
        self.assertEqual(cfg.upper, Decimal("2.5"))
        self.assertEqual(cfg.lower, Decimal("1.5"))

    def test_inverted_shows_hint(self):
        s = self._screen()
        s._bracket_upper_edit.setText("1.0")
        s._bracket_lower_edit.setText("2.0")
        s._on_bracket_changed()
        # headless: الشاشة غير معروضة فـ isVisible()=False؛ نتحقّق من عدم الإخفاء + نص التحذير.
        self.assertFalse(s._bracket_hint.isHidden())
        self.assertIn("السفلي", s._bracket_hint.text())


if __name__ == "__main__":
    unittest.main()
