# -*- coding: utf-8 -*-
"""اختبارات G1.48 — دلالة «نسبة التغيّر» و«نسبة التتبّع» في متتبّعَي المراقبة.

«نسبة التغيّر» = لكل انتقال سعري لحظي (مقابل آخر سعر حيّ سابق، rolling).
«نسبة التتبّع» = مقابل سعر بدء المراقبة المُجمّد (anchor الثابت طوال الجلسة).
يسري على العملة المراقَبة وعلى BTC. offscreen · بلا شبكة.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest
from decimal import Decimal
from types import SimpleNamespace

from ocobot.ui._qt import QApplication
from ocobot.ui.theme import apply_theme
from ocobot.ui.monitoring import DynamicMonitoringScreen


class G148MonitoredTrackerSemantics(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    def _screen(self):
        s = DynamicMonitoringScreen(runner=None)
        s._engine = SimpleNamespace(state=SimpleNamespace(reference_price=Decimal("100")))
        return s

    def test_change_is_rolling_and_track_is_from_anchor(self):
        s = self._screen()
        for p in ("100", "110", "121"):
            s._current_price = Decimal(p)
            s._refresh_monitored_tracker()
        live, prev, change, track = s._monitored_tracker.value_texts()
        self.assertEqual(live, "121")
        self.assertEqual(prev, "110")            # السابق = آخر سعر قبل الحالي (rolling)
        self.assertEqual(change, "+10.00000%")   # 121 عن 110 (لحظي)
        self.assertEqual(track, "+21.00000%")    # 121 عن المرساة 100
        self.assertNotEqual(change, track)       # النسبتان مختلفتان

    def test_first_tick_change_neutral(self):
        s = self._screen()
        s._current_price = Decimal("100")
        s._refresh_monitored_tracker()
        _, _, change, track = s._monitored_tracker.value_texts()
        self.assertEqual(change, "0.00000%")   # لا سعر سابق بعد
        self.assertEqual(track, "0.00000%")    # 100 عن المرساة 100

    def test_change_holds_between_equal_ticks(self):
        s = self._screen()
        for p in ("100", "110", "110", "110"):
            s._current_price = Decimal(p)
            s._refresh_monitored_tracker()
        _, prev, change, _ = s._monitored_tracker.value_texts()
        self.assertEqual(prev, "100")           # لم يتغيّر السابق دون انتقال
        self.assertEqual(change, "+10.00000%")  # محفوظة عند ثبات السعر

    def test_anchor_frozen_across_reposition(self):
        s = self._screen()
        s._current_price = Decimal("100"); s._refresh_monitored_tracker()
        s._current_price = Decimal("110"); s._refresh_monitored_tracker()
        self.assertEqual(s._monitored_anchor, Decimal("100"))
        s._engine.state.reference_price = Decimal("110")  # إعادة تموضع
        s._current_price = Decimal("121"); s._refresh_monitored_tracker()
        self.assertEqual(s._monitored_anchor, Decimal("100"))  # ثابت
        _, _, change, track = s._monitored_tracker.value_texts()
        self.assertEqual(change, "+10.00000%")  # 121 عن 110 (لحظي)
        self.assertEqual(track, "+21.00000%")   # 121 عن المرساة المجمّدة 100

    def test_set_selected_resets_rolling_refs(self):
        s = self._screen()
        s._current_price = Decimal("100"); s._refresh_monitored_tracker()
        s._current_price = Decimal("110"); s._refresh_monitored_tracker()
        s.set_selected(None)
        # جلسة جديدة: تُصفَّر مراجع «نسبة التغيّر» (rolling) ومرساة BTC.
        self.assertIsNone(s._monitored_prev)
        self.assertIsNone(s._monitored_last)
        self.assertIsNone(s._btc_anchor)
        # ومرساة العملة تُعاد تجميدها من مرجع المحرّك للجلسة الجديدة (لا تبقى على القديمة).
        self.assertEqual(s._monitored_anchor, Decimal("100"))


class G148BtcTrackerSemantics(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    def _screen(self):
        return DynamicMonitoringScreen(runner=None)

    def test_change_uses_prev_and_track_uses_frozen_anchor(self):
        s = self._screen()
        # اللقطة الأولى تُجمّد المرساة = أول window_start صالح (100).
        s._refresh_btc_tracker((Decimal("110"), Decimal("105"), Decimal("100")))
        self.assertEqual(s._btc_anchor, Decimal("100"))
        # لقطة لاحقة: window_start تدحرّج إلى 102، لكن المرساة تبقى 100.
        s._refresh_btc_tracker((Decimal("121"), Decimal("110"), Decimal("102")))
        live, prev, change, track = s._btc_tracker.value_texts()
        self.assertEqual(live, "121")
        self.assertEqual(prev, "110")
        self.assertEqual(change, "+10.00000%")   # 121 عن 110 (لحظي، prev)
        self.assertEqual(track, "+21.00000%")    # 121 عن المرساة المجمّدة 100 (لا 102)

    def test_btc_anchor_frozen_once(self):
        s = self._screen()
        s._refresh_btc_tracker((Decimal("100"), None, Decimal("100")))
        s._refresh_btc_tracker((Decimal("200"), Decimal("150"), Decimal("150")))
        self.assertEqual(s._btc_anchor, Decimal("100"))  # لم تتغيّر


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
