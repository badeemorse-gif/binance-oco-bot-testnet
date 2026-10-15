"""اختبارات G1.56 · c3 — طبقة النظام + قياس السيولة (regime.py)."""
import math
import unittest

from ocobot.domain import regime as rg
from ocobot.domain.volatility import Candle


def _uptrend(n=40):
    return [Candle(100 + i, 101 + i, 100 + i, 100.9 + i) for i in range(n)]


def _choppy_adx(n=40):
    out = []
    for i in range(n):
        if i % 2:
            out.append(Candle(100, 102, 99, 100.5))
        else:
            out.append(Candle(100, 101, 98, 99.5))
    return out


def _flat(n=40, p=100.0):
    return [Candle(p, p, p, p, 5.0) for _ in range(n)]


class AdxTests(unittest.TestCase):
    def test_trend_stronger_than_choppy(self):
        a_up = rg.adx(_uptrend(), period=14)
        a_ch = rg.adx(_choppy_adx(), period=14)
        self.assertIsNotNone(a_up)
        self.assertIsNotNone(a_ch)
        self.assertGreater(a_up, a_ch)
        for a in (a_up, a_ch):
            self.assertGreaterEqual(a, 0.0)
            self.assertLessEqual(a, 100.0)

    def test_dmi_direction_in_uptrend(self):
        _, pdi, mdi = rg.adx_dmi(_uptrend(), period=14)
        self.assertGreater(pdi, mdi)

    def test_flat_zero(self):
        self.assertEqual(rg.adx(_flat(), period=14), 0.0)

    def test_insufficient_none(self):
        self.assertIsNone(rg.adx(_uptrend(10), period=14))

    def test_period_guard(self):
        with self.assertRaises(ValueError):
            rg.adx_dmi(_uptrend(), period=0)


class ChoppinessTests(unittest.TestCase):
    def _trend(self, n=20):
        return [Candle(100 + 5 * i, 105 + 5 * i, 100 + 5 * i, 103 + 5 * i)
                for i in range(n)]

    def _choppy(self, n=20):
        return [Candle(100, 110, 90, 109 if i % 2 else 91) for i in range(n)]

    def test_trend_lower_than_choppy(self):
        c_tr = rg.choppiness_index(self._trend(), period=5)
        c_ch = rg.choppiness_index(self._choppy(), period=5)
        self.assertLess(c_tr, c_ch)
        for c in (c_tr, c_ch):
            self.assertGreaterEqual(c, 0.0)
            self.assertLessEqual(c, 100.0001)

    def test_insufficient_none(self):
        self.assertIsNone(rg.choppiness_index(_flat(3), period=14))

    def test_flat_range_zero_none(self):
        self.assertIsNone(rg.choppiness_index(_flat(20), period=5))


class VarianceRatioTests(unittest.TestCase):
    def test_persistent_gt_one(self):
        r = [0.01, 0.01, -0.01, -0.01] * 2
        vr = rg.variance_ratio(r, q=2)
        self.assertGreater(vr, 1.0)
        self.assertAlmostEqual(vr, 7.0 / 3.0, places=10)

    def test_meanreverting_lt_one(self):
        r = [0.01, -0.01] * 4
        self.assertLess(rg.variance_ratio(r, q=2), 1.0)

    def test_short_none_and_q_guard(self):
        self.assertIsNone(rg.variance_ratio([0.01, 0.02], q=2))
        with self.assertRaises(ValueError):
            rg.variance_ratio([0.0] * 10, q=1)

    def test_zero_variance_none(self):
        self.assertIsNone(rg.variance_ratio([0.0] * 10, q=2))


class HurstTests(unittest.TestCase):
    def test_short_none(self):
        self.assertIsNone(rg.hurst_rs([0.1] * 10, min_chunk=8))

    def test_finite_for_valid_series(self):
        series = [math.sin(i * 0.3) + 0.05 * i for i in range(64)]
        h = rg.hurst_rs(series, min_chunk=8)
        self.assertIsNotNone(h)
        self.assertTrue(math.isfinite(h))


class LiquidityTests(unittest.TestCase):
    def test_spread_pct(self):
        self.assertAlmostEqual(rg.spread_pct(100, 101),
                               1.0 / 100.5 * 100.0, places=12)
        self.assertIsNone(rg.spread_pct(None, 101))
        self.assertIsNone(rg.spread_pct(101, 100))  # ask<bid

    def test_average_volume(self):
        cs = [Candle(100, 102, 98, 100, 10), Candle(100, 104, 100, 102, 20)]
        self.assertAlmostEqual(rg.average_volume(cs), 15.0, places=12)
        # quote: typical1=100 -> 1000 ; typical2=102 -> 2040 ; avg=1520
        self.assertAlmostEqual(rg.average_volume(cs, quote=True), 1520.0, places=9)
        self.assertIsNone(rg.average_volume([]))

    def test_assess_liquidity_flags(self):
        cs = [Candle(100, 102, 98, 100, 10), Candle(100, 104, 100, 102, 20)]
        thin = rg.assess_liquidity(cs, bid=100, ask=101,
                                   min_quote_volume=2000, max_spread_pct=0.5)
        self.assertTrue(thin.is_thin)
        self.assertTrue(thin.is_wide_spread)
        self.assertFalse(thin.ok)

        good = rg.assess_liquidity(cs, bid=100, ask=101,
                                   min_quote_volume=1000, max_spread_pct=2.0)
        self.assertFalse(good.is_thin)
        self.assertFalse(good.is_wide_spread)
        self.assertTrue(good.ok)
        self.assertIn("spreadPct", good.to_dict())

    def test_no_thresholds_no_flags(self):
        st = rg.assess_liquidity([Candle(1, 1, 1, 1, 1)])
        self.assertFalse(st.is_thin)
        self.assertFalse(st.is_wide_spread)
        self.assertTrue(st.ok)


class RegimeSummaryTests(unittest.TestCase):
    def test_summary_trending(self):
        s = rg.regime_summary(_uptrend(60), period=14)
        self.assertEqual(s.n, 60)
        self.assertIsNotNone(s.adx)
        self.assertGreaterEqual(s.trend_strength, 0.0)
        self.assertLessEqual(s.trend_strength, 1.0)
        self.assertGreaterEqual(s.adx_factor, 0.8)
        self.assertLessEqual(s.adx_factor, 1.3)
        self.assertIn(s.label, ("trending", "transition", "ranging"))
        self.assertIn("adxFactor", s.to_dict())

    def test_summary_insufficient_unknown(self):
        s = rg.regime_summary(_uptrend(5), period=14)
        self.assertIsNone(s.adx)
        self.assertEqual(s.label, "unknown")
        self.assertEqual(s.trend_strength, 0.0)
        self.assertEqual(s.adx_factor, 0.8)


if __name__ == "__main__":
    unittest.main()
