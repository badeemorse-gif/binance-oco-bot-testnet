# -*- coding: utf-8 -*-
"""G1.50 — لوحة انزلاق BTC بنافذة متحرّكة: rolling vs anchored-at-start + عرض-فقط + §1.5."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import unittest
from decimal import Decimal

from ocobot.ui import i18n
from ocobot.ui.btc_slippage_tracker import window_slippage
from ocobot.domain.btc_follow import BtcSample


class WindowSlippagePure(unittest.TestCase):
    def test_rolling_peak_not_anchored_at_start(self):
        samples = [BtcSample(ts=0.0, price=Decimal("100")),
                   BtcSample(ts=10.0, price=Decimal("120")),
                   BtcSample(ts=11.0, price=Decimal("114"))]
        r = window_slippage(samples, now=11.0, window_seconds=3.0)
        self.assertIsNotNone(r)
        self.assertEqual(r["peak"], Decimal("120"))
        self.assertEqual(r["current"], Decimal("114"))
        self.assertEqual(r["drop_pct"], (Decimal("120") - Decimal("114")) / Decimal("120") * Decimal("100"))
        anchored = (Decimal("100") - Decimal("114")) / Decimal("100") * Decimal("100")
        self.assertNotEqual(r["drop_pct"], anchored)
        self.assertNotEqual(r["peak"], Decimal("100"))

    def test_window_excludes_old_peak(self):
        samples = [BtcSample(ts=0.0, price=Decimal("200")),
                   BtcSample(ts=9.0, price=Decimal("110")),
                   BtcSample(ts=10.0, price=Decimal("100"))]
        r = window_slippage(samples, now=10.0, window_seconds=3.0)
        self.assertEqual(r["peak"], Decimal("110"))

    def test_insufficient_samples_none(self):
        self.assertIsNone(window_slippage([BtcSample(ts=10.0, price=Decimal("100"))], 10.0, 3.0))
        self.assertIsNone(window_slippage([], 10.0, 3.0))

    def test_no_drop_at_peak(self):
        samples = [BtcSample(ts=9.0, price=Decimal("100")), BtcSample(ts=10.0, price=Decimal("100"))]
        r = window_slippage(samples, 10.0, 3.0)
        self.assertEqual(r["drop_pct"], Decimal("0"))


class SlippageWidget(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from ocobot.ui._qt import QApplication
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        i18n.set_language("ar")

    def tearDown(self):
        i18n.set_language("ar")

    def _w(self):
        from ocobot.ui.btc_slippage_tracker import BtcSlippageTracker
        return BtcSlippageTracker()

    def test_update_display_only(self):
        w = self._w()
        w.update_slippage(Decimal("114"), Decimal("120"), Decimal("5"), "ARMED")
        for banned in ("place_order", "execute", "cancel_oco", "ingest"):
            self.assertFalse(hasattr(w, banned))

    def test_bilingual_captions_mapped(self):
        pairs = [("تتبّع انزلاق BTC (نافذة متحرّكة)", "BTC Slippage (Rolling Window)"),
                 ("سعر BTC الحيّ", "BTC Live Price"),
                 ("ذروة النافذة", "Window Peak"),
                 ("انزلاق النافذة %", "Window Slippage %"),
                 ("طور الحارس", "Guard Phase"),
                 ("خامل", "Idle"), ("مُسلّح", "Armed")]
        for ar, en in pairs:
            self.assertIn(ar, i18n.AR_TO_EN)
            self.assertEqual(i18n.AR_TO_EN[ar], en)
            i18n.set_language("en"); self.assertEqual(i18n.translate(ar), en)
            i18n.set_language("ar"); self.assertEqual(i18n.translate(ar), ar)

    def test_no_ar_leak_after_retranslate_en(self):
        from ocobot.ui._qt import QLabel
        w = self._w()
        w.update_slippage(Decimal("114"), Decimal("120"), Decimal("5"), "ARMED")
        i18n.set_language("en")
        i18n.retranslate_widget_tree(w)
        texts = [l.text() for l in w.findChildren(QLabel)]
        self.assertIn("BTC Slippage (Rolling Window)", texts)
        for en in ("BTC Live Price", "Window Peak", "Window Slippage %", "Guard Phase"):
            self.assertIn(en, texts)


if __name__ == "__main__":
    unittest.main()
