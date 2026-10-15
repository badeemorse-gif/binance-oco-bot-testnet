# -*- coding: utf-8 -*-
"""اختبارات G1.60 — حقن recommendation_provider الحقيقي (klines⇒recommender).

offscreen، بلا شبكة (klines مزيّفة). تغطّي عقد G1.60:
  - recommendation_from_candles: klines/candles ⇒ Recommendation (أو None عند الفراغ).
  - make_recommendation_provider: دالة بلا وسائط؛ symbol None ⇒ None بلا جلب.
  - build_recommendation_provider فوق KlinesService مزيّف (interval/limit صحيحان).
  - set_recommendation_provider على DynamicMonitoringScreen يملأ لوحة النِّسب
    عبر رَنَر مزيّف (الخانات تتحوّل من '—' إلى قيمة٪) — إصلاح الخلل المُبلَّغ.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import math
import unittest
from decimal import Decimal

from ocobot.domain.recommender import Recommendation
from ocobot.domain.rec_provider import (make_recommendation_provider,
                                        recommendation_from_candles)
from ocobot.app_wiring import build_recommendation_provider


def _klines(n=120, start=100.0):
    """صفوف klines بنمط Binance ([openTime, o, h, l, c, v]) — اتجاه صاعد + تذبذب."""
    rows = []
    px = start
    for i in range(n):
        px = px * (1.0 + 0.004 * math.sin(i / 5.0) + 0.001)
        rows.append([i, px * 0.999, px * 1.005, px * 0.995, px, 10.0 + i])
    return rows


class _FakeRunner:
    """رَنَر متزامن: ينفّذ fn ثم on_result/on_error فورًا (بلا خيوط/شبكة)."""

    def __init__(self):
        self.calls = 0

    def submit(self, fn, *args, on_result=None, on_error=None):
        self.calls += 1
        try:
            res = fn(*args)
        except Exception as exc:  # pragma: no cover - دفاعي
            if on_error:
                on_error(exc)
            return None
        if on_result:
            on_result(res)
        return None


class _FakeKlinesService:
    """شبيه KlinesService: get_candles(symbol, interval=, limit=) يُرجع klines ثابتة."""

    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def get_candles(self, symbol, interval="1h", limit=200, force_refresh=False):
        self.calls.append((symbol, interval, limit))
        return self.rows


class PipelineTests(unittest.TestCase):
    def test_from_candles_returns_recommendation(self):
        rec = recommendation_from_candles(_klines())
        self.assertIsInstance(rec, Recommendation)
        self.assertIsInstance(rec.tp_pct, Decimal)
        self.assertGreater(float(rec.tp_pct), 0.0)
        self.assertGreater(float(rec.sl_pct), 0.0)

    def test_from_candles_empty_or_none_is_none(self):
        self.assertIsNone(recommendation_from_candles([]))
        self.assertIsNone(recommendation_from_candles(None))


class FactoryTests(unittest.TestCase):
    def test_provider_with_symbol_fn_yields_rec(self):
        rows = _klines()
        prov = make_recommendation_provider(lambda s: rows, symbol_fn=lambda: "BTCUSDT")
        self.assertIsInstance(prov(), Recommendation)

    def test_provider_symbol_none_returns_none_without_fetch(self):
        calls = []

        def candles_fn(sym):
            calls.append(sym)
            return _klines()

        prov = make_recommendation_provider(candles_fn, symbol_fn=lambda: None)
        self.assertIsNone(prov())
        self.assertEqual(calls, [])  # لا جلب بلا رمز

    def test_provider_zero_arg_candles_fn(self):
        rows = _klines()
        prov = make_recommendation_provider(lambda: rows)  # بلا symbol_fn
        self.assertIsInstance(prov(), Recommendation)


class AppWiringHelperTests(unittest.TestCase):
    def test_build_over_klines_service(self):
        fake = _FakeKlinesService(_klines())
        prov = build_recommendation_provider(fake, symbol_fn=lambda: "ETHUSDT",
                                             interval="1h", limit=150)
        self.assertIsInstance(prov(), Recommendation)
        self.assertEqual(fake.calls[-1], ("ETHUSDT", "1h", 150))

    def test_build_symbol_none_skips_fetch(self):
        fake = _FakeKlinesService(_klines())
        prov = build_recommendation_provider(fake, symbol_fn=lambda: None)
        self.assertIsNone(prov())
        self.assertEqual(fake.calls, [])


class ScreenWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from ocobot.ui._qt import QApplication
        from ocobot.ui.theme import apply_theme
        cls.app = QApplication.instance() or QApplication([])
        try:
            apply_theme(cls.app)
        except Exception:
            pass

    def test_setter_populates_panel_via_runner(self):
        from ocobot.ui.monitoring import DynamicMonitoringScreen
        runner = _FakeRunner()
        screen = DynamicMonitoringScreen(runner=runner)   # بلا مزوّد ⇒ '—'

        # قبل الحقن: لا مزوّد ⇒ no-op آمن، والخانات تبقى '—'.
        screen._recompute_recommendation()
        self.assertEqual(runner.calls, 0)
        self.assertEqual(screen.rec_panel.value_texts()["tp"], "—")

        # بعد الحقن عبر setter (كنمط set_price_provider):
        screen.set_recommendation_provider(
            build_recommendation_provider(_FakeKlinesService(_klines()),
                                          symbol_fn=lambda: "BTCUSDT"))
        screen._recompute_recommendation()
        self.assertGreaterEqual(runner.calls, 1)
        self.assertIsNotNone(screen.rec_panel.current_recommendation())
        tp_text = screen.rec_panel.value_texts()["tp"]
        self.assertNotEqual(tp_text, "—")
        self.assertTrue(tp_text.endswith("%"))

    def test_setter_stores_provider_reference(self):
        from ocobot.ui.monitoring import DynamicMonitoringScreen
        screen = DynamicMonitoringScreen(runner=_FakeRunner())
        prov = (lambda: None)
        screen.set_recommendation_provider(prov)
        self.assertIs(screen._rec_provider, prov)


if __name__ == "__main__":
    unittest.main()
