# -*- coding: utf-8 -*-
"""اختبارات G1.65 increment #4 — observability لمزوّد ATR٪ الحيّ (قراءة-فقط).

تثبّت:
  (1) عدّادات ``stats`` على المسار السعيد (calls/ok/failsafe + last_reason="ok").
  (2) تصنيف سبب السقوط على fail-safe: no_symbol / empty_candles / exception.
  (3) ``observer`` يستقبل حدثًا لكل نداء، بالشكل الصحيح (ok/failsafe).
  (4) **صفر تغيير سلوك**: قيم الإرجاع مطابقة تمامًا لما قبل الـobservability.
  (5) الـobservability نفسها fail-safe: استثناء داخل observer لا يكسر المزوّد.

صفر شبكة/رأس مال (fakes فقط)، ولا تفعيل لأي علم.
"""
import unittest

from ocobot.app_wiring import build_live_atr_pct_provider
from ocobot.domain.dynamic_exit import live_atr_pct
from ocobot.domain.klines import KlinesService


# شموع 1m ثابتة بصيغة Binance kline: [openTime, o, h, l, c, v, ...] — 12 شمعة.
_ROWS = [
    [0, 100.0, 101.0, 99.5, 100.5, 10.0, 0, 0, 0, 0, 0, 0],
    [1, 100.5, 102.0, 100.0, 101.5, 11.0, 0, 0, 0, 0, 0, 0],
    [2, 101.5, 103.0, 101.0, 102.0, 9.0, 0, 0, 0, 0, 0, 0],
    [3, 102.0, 102.5, 100.5, 101.0, 8.0, 0, 0, 0, 0, 0, 0],
    [4, 101.0, 101.5, 99.0, 99.5, 12.0, 0, 0, 0, 0, 0, 0],
    [5, 99.5, 100.5, 98.0, 100.0, 15.0, 0, 0, 0, 0, 0, 0],
    [6, 100.0, 104.0, 99.5, 103.5, 20.0, 0, 0, 0, 0, 0, 0],
    [7, 103.5, 105.0, 103.0, 104.0, 18.0, 0, 0, 0, 0, 0, 0],
    [8, 104.0, 104.5, 102.0, 102.5, 14.0, 0, 0, 0, 0, 0, 0],
    [9, 102.5, 103.0, 101.5, 102.0, 13.0, 0, 0, 0, 0, 0, 0],
    [10, 102.0, 106.0, 101.5, 105.5, 25.0, 0, 0, 0, 0, 0, 0],
    [11, 105.5, 107.0, 105.0, 106.0, 22.0, 0, 0, 0, 0, 0, 0],
]


class _FakeKlinesClient:
    """عميل وهميّ: ``public_request`` يُعيد صفوف klines ثابتة (بلا شبكة)."""

    def __init__(self, rows=None, raise_exc=False):
        self._rows = _ROWS if rows is None else rows
        self._raise = raise_exc
        self.calls = []

    def public_request(self, method, path, params):
        self.calls.append((method, path, dict(params)))
        if self._raise:
            raise RuntimeError("network down")
        return list(self._rows)


def _svc(client):
    return KlinesService(client, monotonic=lambda: 1.0)


def _expected_atr(rows, atr_win=10):
    highs = [float(r[2]) for r in rows]
    lows = [float(r[3]) for r in rows]
    closes = [float(r[4]) for r in rows]
    return live_atr_pct(highs, lows, closes, atr_win, closes[-1])


class TestObservabilityHappyPath(unittest.TestCase):
    def test_ok_stats_and_value(self):
        provider = build_live_atr_pct_provider(
            _svc(_FakeKlinesClient()), lambda: "BTCUSDT", atr_win=10)
        got = provider()
        self.assertAlmostEqual(got, _expected_atr(_ROWS, 10), places=9)
        self.assertGreater(got, 0.0)
        s = provider.stats
        self.assertEqual(s["calls"], 1)
        self.assertEqual(s["ok"], 1)
        self.assertEqual(s["failsafe"], 0)
        self.assertEqual(s["last_reason"], "ok")
        self.assertAlmostEqual(s["last_value"], got, places=9)
        self.assertEqual(s["failsafe_by_reason"], {})

    def test_multiple_calls_accumulate(self):
        provider = build_live_atr_pct_provider(
            _svc(_FakeKlinesClient()), lambda: "BTCUSDT", atr_win=10)
        for _ in range(3):
            provider()
        self.assertEqual(provider.stats["calls"], 3)
        self.assertEqual(provider.stats["ok"], 3)
        self.assertEqual(provider.stats["failsafe"], 0)


class TestObservabilityFailSafe(unittest.TestCase):
    def test_no_symbol_reason_and_no_network(self):
        client = _FakeKlinesClient()
        provider = build_live_atr_pct_provider(_svc(client), lambda: None)
        self.assertEqual(provider(), 0.0)
        self.assertEqual(client.calls, [])  # لا نداء شبكة بلا رمز
        s = provider.stats
        self.assertEqual(s["failsafe"], 1)
        self.assertEqual(s["last_reason"], "no_symbol")
        self.assertEqual(s["failsafe_by_reason"].get("no_symbol"), 1)

    def test_network_error_reason_exception(self):
        provider = build_live_atr_pct_provider(
            _svc(_FakeKlinesClient(raise_exc=True)), lambda: "BTCUSDT")
        self.assertEqual(provider(), 0.0)
        s = provider.stats
        self.assertEqual(s["failsafe"], 1)
        self.assertEqual(s["last_reason"], "exception")
        self.assertEqual(s["failsafe_by_reason"].get("exception"), 1)

    def test_empty_candles_reason(self):
        provider = build_live_atr_pct_provider(
            _svc(_FakeKlinesClient(rows=[])), lambda: "BTCUSDT")
        self.assertEqual(provider(), 0.0)
        s = provider.stats
        self.assertEqual(s["failsafe"], 1)
        self.assertEqual(s["last_reason"], "empty_candles")
        self.assertEqual(s["failsafe_by_reason"].get("empty_candles"), 1)


class TestObserverCallback(unittest.TestCase):
    def test_observer_receives_ok_event(self):
        events = []
        provider = build_live_atr_pct_provider(
            _svc(_FakeKlinesClient()), lambda: "BTCUSDT", atr_win=10,
            observer=events.append)
        got = provider()
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertTrue(ev["ok"])
        self.assertEqual(ev["reason"], "ok")
        self.assertEqual(ev["symbol"], "BTCUSDT")
        self.assertAlmostEqual(ev["value"], got, places=9)
        self.assertEqual(ev["candles"], len(_ROWS))

    def test_observer_receives_failsafe_event(self):
        events = []
        provider = build_live_atr_pct_provider(
            _svc(_FakeKlinesClient(raise_exc=True)), lambda: "BTCUSDT",
            observer=events.append)
        provider()
        self.assertEqual(len(events), 1)
        self.assertFalse(events[0]["ok"])
        self.assertEqual(events[0]["reason"], "exception")
        self.assertEqual(events[0]["value"], 0.0)
        self.assertEqual(events[0]["symbol"], "BTCUSDT")  # الرمز محفوظ عند الاستثناء

    def test_observer_exception_does_not_break_provider(self):
        def _boom(_ev):
            raise RuntimeError("observer blew up")

        provider = build_live_atr_pct_provider(
            _svc(_FakeKlinesClient()), lambda: "BTCUSDT", atr_win=10,
            observer=_boom)
        # الـobservability لا يجب أن تكسر المراقبة: القيمة تظلّ صحيحة.
        self.assertAlmostEqual(provider(), _expected_atr(_ROWS, 10), places=9)
        self.assertEqual(provider.stats["ok"], 1)


class TestZeroBehaviorChange(unittest.TestCase):
    """قيم الإرجاع مطابقة تمامًا لما قبل الـobservability (صفر تغيير سلوك)."""

    def test_return_parity_ok_and_failures(self):
        ok_provider = build_live_atr_pct_provider(
            _svc(_FakeKlinesClient()), lambda: "BTCUSDT", atr_win=10)
        self.assertAlmostEqual(ok_provider(), _expected_atr(_ROWS, 10), places=9)
        self.assertEqual(
            build_live_atr_pct_provider(_svc(_FakeKlinesClient()), lambda: None)(), 0.0)
        self.assertEqual(
            build_live_atr_pct_provider(
                _svc(_FakeKlinesClient(raise_exc=True)), lambda: "BTCUSDT")(), 0.0)
        self.assertEqual(
            build_live_atr_pct_provider(
                _svc(_FakeKlinesClient(rows=[])), lambda: "BTCUSDT")(), 0.0)


if __name__ == "__main__":
    unittest.main()
