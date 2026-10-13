# -*- coding: utf-8 -*-
"""اختبارات G1.45 / chunk_2 + chunk_3 — لوحتا التتبّع داخل المراقبة الديناميكية.

- PURE (بلا Qt): BtcFollowSupervisor.price_snapshot (last/prev/نافذة ~5s).
- QT (offscreen): لوحة BTC تُغذّى من اللقطة؛ لوحة العملة المراقَبة تُحسب من سعر
  بدء المراقبة المثبّت (reference_price) الثابت عبر إعادة التموضع.
- i18n (§1.5): عنوان جديد له مدخل إنجليزي خالٍ من العربية.

offscreen ونقيّ: لا شبكة في طبقة الواجهة (يحترم tests/test_ui_no_direct_network).
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import re
import unittest
from decimal import Decimal
from types import SimpleNamespace

from ocobot.domain.btc_follow import BtcFollowConfig
from ocobot.domain.btc_follow_supervisor import BtcFollowSupervisor
from ocobot.ui.i18n import AR_TO_EN

_ARABIC = re.compile(r"[\u0600-\u06FF]")


# ===================== PURE: price_snapshot (بلا Qt) =====================
class TestBtcPriceSnapshot(unittest.TestCase):
    def _sup(self):
        return BtcFollowSupervisor(config=BtcFollowConfig(enabled=True, window_seconds=5.0))

    def test_empty_is_none_triple(self):
        self.assertEqual(self._sup().price_snapshot(now=0.0), (None, None, None))

    def test_single_sample(self):
        sup = self._sup()
        sup.ingest(Decimal("100"), ts=0.0)
        last, prev, wstart = sup.price_snapshot(now=5.0, window_seconds=5.0)
        self.assertEqual(last, Decimal("100"))
        self.assertIsNone(prev)
        self.assertEqual(wstart, Decimal("100"))

    def test_window_start_is_price_five_seconds_ago(self):
        sup = self._sup()
        sup.ingest(Decimal("100"), ts=0.0)
        sup.ingest(Decimal("101"), ts=1.0)
        sup.ingest(Decimal("99"), ts=5.0)
        last, prev, wstart = sup.price_snapshot(now=5.0, window_seconds=5.0)
        self.assertEqual(last, Decimal("99"))    # آخر عيّنة
        self.assertEqual(prev, Decimal("101"))   # ما قبل الأخيرة مباشرة
        self.assertEqual(wstart, Decimal("100"))  # أقدم عيّنة داخل نافذة 5s

    def test_window_excludes_old_samples(self):
        sup = self._sup()
        sup.ingest(Decimal("100"), ts=0.0)
        sup.ingest(Decimal("50"), ts=10.0)
        sup.ingest(Decimal("55"), ts=11.0)
        last, prev, wstart = sup.price_snapshot(now=11.0, window_seconds=5.0)
        self.assertEqual(last, Decimal("55"))
        self.assertEqual(prev, Decimal("50"))
        self.assertEqual(wstart, Decimal("50"))  # 100@ts=0 خارج النافذة [6,11]

    def test_never_raises(self):
        sup = self._sup()
        sup.ingest(Decimal("100"), ts=0.0)
        # لا يرمي مهما كانت الوسائط.
        self.assertIsInstance(sup.price_snapshot(), tuple)


# ===================== QT (offscreen) =====================
from ocobot.ui._qt import QApplication  # noqa: E402
from ocobot.ui.theme import apply_theme  # noqa: E402
from ocobot.ui.monitoring import DynamicMonitoringScreen  # noqa: E402


class TestTrackersUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    def _screen(self):
        return DynamicMonitoringScreen(runner=None)

    # ---- البناء: اللوحتان موجودتان كعنصري عرض ----
    def test_trackers_built(self):
        s = self._screen()
        self.assertIsNotNone(s._btc_tracker)
        self.assertIsNotNone(s._monitored_tracker)
        self.assertIsNotNone(s._btc_display_sup)

    # ---- لوحة BTC تُغذّى من اللقطة ----
    def test_btc_tracker_from_snapshot(self):
        s = self._screen()
        sup = s._btc_display_sup
        sup.ingest(Decimal("100"), ts=0.0)
        sup.ingest(Decimal("101"), ts=1.0)
        sup.ingest(Decimal("99"), ts=5.0)
        snap = sup.price_snapshot(now=5.0, window_seconds=5.0)
        s._refresh_btc_tracker(snap)
        live, prev, change, track = s._btc_tracker.value_texts()
        self.assertEqual(live, "99")
        self.assertEqual(prev, "101")
        self.assertEqual(change, "-1.98020%")   # (99-101)/101*100
        self.assertEqual(track, "-1.00000%")    # (99-100)/100*100

    def test_btc_tracker_via_on_live_tick_3tuple(self):
        s = self._screen()
        sup = s._btc_display_sup
        sup.ingest(Decimal("100"), ts=0.0)
        sup.ingest(Decimal("102"), ts=5.0)
        snap = sup.price_snapshot(now=5.0, window_seconds=5.0)
        # مسار النبض: 3-tuple (price, tick, btc_snap) لا يرمي ويحدّث اللوحة.
        s._on_live_tick((Decimal("102"), None, snap))
        live, prev, change, track = s._btc_tracker.value_texts()
        self.assertEqual(live, "102")
        self.assertEqual(prev, "100")
        self.assertEqual(change, "+2.00000%")

    def test_on_live_tick_two_tuple_still_supported(self):
        s = self._screen()
        # توافق خلفي: 2-tuple لا يكسر شيئًا.
        s._on_live_tick((Decimal("123"), None))
        self.assertEqual(s._current_price, Decimal("123"))

    # ---- لوحة العملة المراقَبة: النسبة من سعر البدء المثبّت ----
    def test_monitored_tracker_from_frozen_reference(self):
        s = self._screen()
        s._engine = SimpleNamespace(state=SimpleNamespace(reference_price=Decimal("100")))
        # G1.48: التتبّع من المرساة المجمّدة (100)، والتغيّر لحظي عن السعر السابق.
        s._current_price = Decimal("100"); s._refresh_monitored_tracker()
        s._current_price = Decimal("110"); s._refresh_monitored_tracker()
        live, prev, change, track = s._monitored_tracker.value_texts()
        self.assertEqual(live, "110")
        self.assertEqual(prev, "100")           # السابق = آخر سعر قبل الحالي (rolling)
        self.assertEqual(change, "+10.00000%")  # 110 عن 100 (لحظي)
        self.assertEqual(track, "+10.00000%")   # 110 عن المرساة 100

    def test_monitored_anchor_frozen_across_reposition(self):
        s = self._screen()
        s._engine = SimpleNamespace(state=SimpleNamespace(reference_price=Decimal("100")))
        s._current_price = Decimal("100"); s._refresh_monitored_tracker()
        s._current_price = Decimal("110"); s._refresh_monitored_tracker()
        self.assertEqual(s._monitored_anchor, Decimal("100"))
        s._engine.state.reference_price = Decimal("110")  # إعادة تموضع
        s._current_price = Decimal("121"); s._refresh_monitored_tracker()
        self.assertEqual(s._monitored_anchor, Decimal("100"))  # ثابت
        _, _, change, track = s._monitored_tracker.value_texts()
        self.assertEqual(change, "+10.00000%")  # 121 عن 110 (لحظي)
        self.assertEqual(track, "+21.00000%")   # 121 عن المرساة المجمّدة 100

    def test_monitored_tracker_negative_is_red_sign(self):
        s = self._screen()
        s._engine = SimpleNamespace(state=SimpleNamespace(reference_price=Decimal("100")))
        s._current_price = Decimal("100"); s._refresh_monitored_tracker()
        s._current_price = Decimal("90"); s._refresh_monitored_tracker()
        _, _, change, _ = s._monitored_tracker.value_texts()
        self.assertEqual(change, "-10.00000%")  # 90 عن 100 (لحظي)

    def test_set_selected_resets_anchor(self):
        s = self._screen()
        s._monitored_anchor = Decimal("100")
        s.set_selected(None)
        self.assertIsNone(s._monitored_anchor)


# ===================== i18n §1.5 =====================
class TestI18nNewHeading(unittest.TestCase):
    def test_monitored_heading_has_english_without_arabic(self):
        key = "تتبّع العملة المراقَبة"
        self.assertIn(key, AR_TO_EN)
        en = AR_TO_EN[key]
        self.assertFalse(_ARABIC.search(en), "ترجمة تحوي عربية: %r" % (en,))


if __name__ == "__main__":
    unittest.main()
