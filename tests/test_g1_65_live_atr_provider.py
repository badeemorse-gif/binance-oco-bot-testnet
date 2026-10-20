# -*- coding: utf-8 -*-
"""اختبارات G1.65 — وصل مصدر ATR٪/fill/peak الحقيقي (خلف المفتاح المُطفأ).

تثبّت:
  (1) ``build_live_atr_pct_provider`` يطابق صيغة ``dynamic_exit.live_atr_pct``
      المُتحقَّقة forward على شموع 1m ثابتة (المرجع = آخر إغلاق حيّ).
  (2) fail-safe = 0.0 عند غياب الرمز/الشموع/خطأ شبكة (يتراجع لبذرة التتبّع المتحفّظة).
  (3) علم الإعداد مُطفأ افتراضيًّا، و``_dynamic_exit_kwargs`` **فارغة** عند الإطفاء
      ⇒ المسار الافتراضي لا يمرّر أي وسائط جديدة (flag-OFF parity).
  (4) عند التفعيل فقط: يبني ``DynamicExitConfig(enabled=True)`` + مزوّدًا حيًّا
      يُنتج القيمة نفسها. صفر شبكة/رأس مال (fakes فقط).
"""
import os
import unittest

from ocobot.app_wiring import build_live_atr_pct_provider
from ocobot.cli import _dynamic_exit_kwargs
from ocobot.config import AppConfig
from ocobot.domain.dynamic_exit import DynamicExitConfig, live_atr_pct
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


class TestLiveAtrProviderFormula(unittest.TestCase):
    def test_matches_validated_formula(self):
        provider = build_live_atr_pct_provider(_svc(_FakeKlinesClient()),
                                               lambda: "BTCUSDT", atr_win=10)
        got = provider()
        self.assertAlmostEqual(got, _expected_atr(_ROWS, 10), places=9)
        self.assertGreater(got, 0.0)

    def test_requests_1m_for_symbol(self):
        client = _FakeKlinesClient()
        build_live_atr_pct_provider(_svc(client), lambda: "BTCUSDT", atr_win=10)()
        self.assertTrue(client.calls)
        self.assertEqual(client.calls[0][2].get("interval"), "1m")
        self.assertEqual(client.calls[0][2].get("symbol"), "BTCUSDT")


class TestLiveAtrProviderFailSafe(unittest.TestCase):
    def test_no_symbol_returns_zero_without_network(self):
        client = _FakeKlinesClient()
        self.assertEqual(build_live_atr_pct_provider(_svc(client), lambda: None)(), 0.0)
        self.assertEqual(build_live_atr_pct_provider(_svc(client), lambda: "")(), 0.0)
        self.assertEqual(client.calls, [])  # لا نداء شبكة بلا رمز

    def test_network_error_returns_zero(self):
        provider = build_live_atr_pct_provider(
            _svc(_FakeKlinesClient(raise_exc=True)), lambda: "BTCUSDT")
        self.assertEqual(provider(), 0.0)

    def test_empty_candles_returns_zero(self):
        provider = build_live_atr_pct_provider(
            _svc(_FakeKlinesClient(rows=[])), lambda: "BTCUSDT")
        self.assertEqual(provider(), 0.0)


class TestDynamicExitConfigKnob(unittest.TestCase):
    def test_default_off(self):
        self.assertFalse(AppConfig().dynamic_exit_enabled)

    def test_kwargs_empty_when_off(self):
        # flag-OFF parity: لا وسائط جديدة تُمرَّر إلى MonitoringEngine
        self.assertEqual(
            _dynamic_exit_kwargs(AppConfig(), _FakeKlinesClient(), "BTCUSDT"), {})

    def test_kwargs_wired_when_on(self):
        cfg = AppConfig(dynamic_exit_enabled=True, dynamic_exit_lock_base=0.80)
        kw = _dynamic_exit_kwargs(cfg, _FakeKlinesClient(), "BTCUSDT")
        self.assertEqual(set(kw), {"dynamic_exit", "live_atr_pct_provider"})
        dyn = kw["dynamic_exit"]
        self.assertIsInstance(dyn, DynamicExitConfig)
        self.assertTrue(dyn.enabled)
        self.assertEqual(dyn.lock_base, 0.80)
        val = kw["live_atr_pct_provider"]()
        self.assertAlmostEqual(val, _expected_atr(_ROWS, dyn.params().atr_win), places=9)


class TestEnvParsing(unittest.TestCase):
    def _with_env(self, value):
        old = os.environ.get("OCOBOT_DYNAMIC_EXIT")
        try:
            if value is None:
                os.environ.pop("OCOBOT_DYNAMIC_EXIT", None)
            else:
                os.environ["OCOBOT_DYNAMIC_EXIT"] = value
            return AppConfig.from_env_vars().dynamic_exit_enabled
        finally:
            if old is None:
                os.environ.pop("OCOBOT_DYNAMIC_EXIT", None)
            else:
                os.environ["OCOBOT_DYNAMIC_EXIT"] = old

    def test_env_default_off(self):
        self.assertFalse(self._with_env(None))

    def test_env_on(self):
        self.assertTrue(self._with_env("1"))
        self.assertTrue(self._with_env("true"))

    def test_env_off_explicit(self):
        self.assertFalse(self._with_env("0"))
        self.assertFalse(self._with_env("false"))


if __name__ == "__main__":
    unittest.main()
