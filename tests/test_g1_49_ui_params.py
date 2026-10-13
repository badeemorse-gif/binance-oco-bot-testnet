# -*- coding: utf-8 -*-
"""G1.49 chunk_5 — بارامترات سياسة تنفيذ الخروج في الواجهة + §1.5 ثنائية اللغة. بلا شبكة."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import unittest
from decimal import Decimal

from ocobot.ui import i18n


class ExitPolicyUIParams(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from ocobot.ui._qt import QApplication
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        i18n.set_language("ar")

    def tearDown(self):
        i18n.set_language("ar")

    def _screen(self):
        from ocobot.ui.monitoring import DynamicMonitoringScreen
        return DynamicMonitoringScreen()

    def test_fields_present_and_default_none(self):
        s = self._screen()
        for attr in ("_exit_band_edit", "_exit_chase_step_edit", "_exit_chase_attempts_edit",
                     "_exit_chase_interval_edit", "_exit_stop_offset_edit"):
            self.assertIsNotNone(getattr(s, attr, None), attr)
        v = s.exit_policy_values()
        self.assertTrue(all(x is None for x in v.values()))

    def test_values_parsed(self):
        s = self._screen()
        s._exit_band_edit.setText("0.3")
        s._exit_chase_step_edit.setText("0.25")
        s._exit_chase_attempts_edit.setText("8")
        s._exit_chase_interval_edit.setText("0.7")
        s._exit_stop_offset_edit.setText("0.4")
        v = s.exit_policy_values()
        self.assertEqual(v["band_pct"], Decimal("0.3"))
        self.assertEqual(v["chase_step_pct"], Decimal("0.25"))
        self.assertEqual(v["chase_max_attempts"], 8)
        self.assertEqual(v["chase_interval_s"], Decimal("0.7"))
        self.assertEqual(v["stop_limit_offset_pct"], Decimal("0.4"))

    def test_invalid_ignored(self):
        s = self._screen()
        s._exit_band_edit.setText("abc")
        s._exit_chase_attempts_edit.setText("0")
        v = s.exit_policy_values()
        self.assertIsNone(v["band_pct"])
        self.assertIsNone(v["chase_max_attempts"])

    def test_exit_execution_policy_builder(self):
        s = self._screen()
        s._exit_band_edit.setText("0.3")
        s._exit_chase_attempts_edit.setText("9")
        pol = s.exit_execution_policy()
        self.assertEqual(pol.band_pct, Decimal("0.3"))
        self.assertEqual(pol.chase_max_attempts, 9)

    def test_bilingual_captions_mapped(self):
        pairs = [("سياسة تنفيذ الخروج الموحّدة", "Unified Exit Policy"),
                 ("نطاق العبور %", "Cross Band %"),
                 ("خطوة الملاحقة %", "Chase Step %"),
                 ("محاولات الملاحقة", "Chase Attempts"),
                 ("مهلة الملاحقة ث", "Chase Interval s"),
                 ("إزاحة ستوب الحارس %", "Guard Stop Offset %")]
        for ar, en in pairs:
            self.assertIn(ar, i18n.AR_TO_EN)
            self.assertEqual(i18n.AR_TO_EN[ar], en)
            i18n.set_language("en")
            self.assertEqual(i18n.translate(ar), en)
            i18n.set_language("ar")
            self.assertEqual(i18n.translate(ar), ar)

    def test_no_ar_leak_after_retranslate_en(self):
        from ocobot.ui._qt import QLabel
        s = self._screen()
        i18n.set_language("en")
        i18n.retranslate_widget_tree(s)
        texts = [w.text() for w in s.findChildren(QLabel)]
        for en in ("Unified Exit Policy", "Cross Band %", "Chase Step %",
                   "Chase Attempts", "Chase Interval s", "Guard Stop Offset %"):
            self.assertIn(en, texts)


if __name__ == "__main__":
    unittest.main()
