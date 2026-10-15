"""اختبارات G1.56 · c1 — مقدِّرات التقلّب الخالصة (ocobot/domain/volatility.py)."""
import math
import unittest

from ocobot.domain import volatility as vol
from ocobot.domain.volatility import Candle


def _flat(n, price=100.0):
    return [Candle(price, price, price, price, 10.0) for _ in range(n)]


class AsCandlesTests(unittest.TestCase):
    def test_binance_kline_list(self):
        kline = [1700000000000, "100.0", "110.0", "95.0", "105.0", "1234.5",
                 1700000599999, "0", 10, "0", "0", "0"]
        cs = vol.as_candles([kline])
        self.assertEqual(len(cs), 1)
        self.assertEqual(cs[0], Candle(100.0, 110.0, 95.0, 105.0, 1234.5))

    def test_dict_forms(self):
        cs = vol.as_candles([
            {"open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 7},
            {"o": 1, "h": 2, "l": 0.5, "c": 1.5},
        ])
        self.assertEqual(cs[0], Candle(1.0, 2.0, 0.5, 1.5, 7.0))
        self.assertEqual(cs[1], Candle(1.0, 2.0, 0.5, 1.5, 0.0))

    def test_tuple_forms(self):
        self.assertEqual(vol.as_candles([(1, 2, 0.5, 1.5)])[0],
                         Candle(1.0, 2.0, 0.5, 1.5, 0.0))
        self.assertEqual(vol.as_candles([(1, 2, 0.5, 1.5, 9)])[0],
                         Candle(1.0, 2.0, 0.5, 1.5, 9.0))

    def test_passthrough_and_bad(self):
        c = Candle(1.0, 2.0, 0.5, 1.5)
        self.assertIs(vol.as_candles([c])[0], c)
        with self.assertRaises(ValueError):
            vol.as_candles([(1, 2, 3)])
        with self.assertRaises(ValueError):
            vol.as_candles(["nope"])


class AtrTests(unittest.TestCase):
    def test_atr_wilder_hand_computed_no_smoothing(self):
        candles = [
            Candle(9, 10, 8, 9),
            Candle(10, 11, 9, 10),
            Candle(11, 12, 10, 11),
            Candle(12, 13, 10, 12),
        ]
        # TR = [2, 2, 3]; period=3 ⇒ ATR = 7/3
        atr = vol.atr_wilder(candles, period=3)
        self.assertAlmostEqual(atr, 7.0 / 3.0, places=10)
        self.assertAlmostEqual(vol.atr_pct(candles, period=3),
                               (7.0 / 3.0) / 12.0 * 100.0, places=10)

    def test_atr_wilder_with_smoothing(self):
        candles = [
            Candle(9, 10, 8, 9),
            Candle(10, 11, 9, 10),
            Candle(11, 12, 10, 11),
            Candle(12, 13, 10, 12),
            Candle(13, 14, 12, 13),
        ]
        # TR = [2, 2, 3, 2]; first ATR = 7/3, smooth with 2 ⇒ 20/9
        self.assertAlmostEqual(vol.atr_wilder(candles, period=3), 20.0 / 9.0, places=10)

    def test_atr_insufficient_data(self):
        self.assertIsNone(vol.atr_wilder(_flat(3), period=14))
        self.assertIsNone(vol.atr_pct(_flat(3), period=14))

    def test_atr_flat_series_zero(self):
        self.assertEqual(vol.atr_wilder(_flat(20), period=14), 0.0)
        self.assertEqual(vol.atr_pct(_flat(20), period=14), 0.0)

    def test_period_must_be_positive(self):
        with self.assertRaises(ValueError):
            vol.atr_wilder(_flat(5), period=0)


class OhlcVolTests(unittest.TestCase):
    def test_parkinson_single_candle(self):
        candles = [Candle(100, 110, 100, 105)]
        r = math.log(110.0 / 100.0)
        expected = math.sqrt((r * r) / (4.0 * math.log(2.0)))
        self.assertAlmostEqual(vol.parkinson_vol(candles), expected, places=12)

    def test_flat_series_all_zero(self):
        f = _flat(10)
        self.assertEqual(vol.parkinson_vol(f), 0.0)
        self.assertEqual(vol.garman_klass_vol(f), 0.0)
        self.assertEqual(vol.rogers_satchell_vol(f), 0.0)
        self.assertEqual(vol.yang_zhang_vol(f), 0.0)
        self.assertEqual(vol.close_to_close_vol(f), 0.0)

    def test_estimators_nonnegative_and_finite(self):
        candles = vol.as_candles([
            (100, 103, 99, 101), (101, 104, 100, 102), (102, 106, 101, 100),
            (100, 101, 97, 98), (98, 100, 96, 99), (99, 102, 98, 101),
        ])
        for fn in (vol.parkinson_vol, vol.garman_klass_vol,
                   vol.rogers_satchell_vol, vol.yang_zhang_vol,
                   vol.close_to_close_vol):
            v = fn(candles)
            self.assertIsNotNone(v)
            self.assertGreaterEqual(v, 0.0)
            self.assertTrue(math.isfinite(v))

    def test_yang_zhang_needs_three(self):
        self.assertIsNone(vol.yang_zhang_vol(_flat(2)))
        self.assertIsNotNone(vol.yang_zhang_vol(_flat(3)))

    def test_close_to_close_needs_two_returns(self):
        self.assertIsNone(vol.close_to_close_vol(_flat(2)))


class EwmaTests(unittest.TestCase):
    def test_ewma_hand_computed(self):
        rets = [0.01, -0.02, 0.015]
        var0 = 0.01 ** 2
        var1 = 0.94 * var0 + 0.06 * (0.02 ** 2)
        var2 = 0.94 * var1 + 0.06 * (0.015 ** 2)
        self.assertAlmostEqual(vol.ewma_vol(rets, lam=0.94),
                               math.sqrt(var2), places=12)

    def test_ewma_empty_none(self):
        self.assertIsNone(vol.ewma_vol([]))

    def test_ewma_lambda_bounds(self):
        with self.assertRaises(ValueError):
            vol.ewma_vol([0.01], lam=1.0)
        with self.assertRaises(ValueError):
            vol.ewma_vol([0.01], lam=0.0)

    def test_ewma_from_flat_candles_zero(self):
        self.assertEqual(vol.ewma_vol_from_candles(_flat(10)), 0.0)


class PercentileTests(unittest.TestCase):
    def test_percentile_linear(self):
        data = [1, 2, 3, 4]
        self.assertEqual(vol.percentile(data, 0), 1)
        self.assertEqual(vol.percentile(data, 100), 4)
        self.assertAlmostEqual(vol.percentile(data, 50), 2.5, places=12)
        self.assertAlmostEqual(vol.percentile(data, 75), 3.25, places=12)

    def test_percentile_single_and_empty(self):
        self.assertEqual(vol.percentile([5], 42), 5)
        self.assertIsNone(vol.percentile([], 50))

    def test_percentile_q_bounds(self):
        with self.assertRaises(ValueError):
            vol.percentile([1, 2], 101)

    def test_percentile_rank(self):
        data = [10, 20, 30, 40]
        self.assertEqual(vol.percentile_rank(data, 5), 0.0)
        self.assertEqual(vol.percentile_rank(data, 20), 0.5)
        self.assertEqual(vol.percentile_rank(data, 40), 1.0)
        self.assertIsNone(vol.percentile_rank([], 1))


class SummaryTests(unittest.TestCase):
    def test_summary_fields_and_dict(self):
        candles = vol.as_candles([
            (100, 103, 99, 101), (101, 104, 100, 102), (102, 106, 101, 100),
            (100, 101, 97, 98), (98, 100, 96, 99), (99, 102, 98, 101),
            (101, 105, 100, 104), (104, 107, 103, 106),
        ])
        s = vol.volatility_summary(candles, atr_period=3)
        self.assertEqual(s.n, 8)
        self.assertEqual(s.last_close, 106.0)
        self.assertIsNotNone(s.atr_pct)
        self.assertIsNotNone(s.per_period_vol_pct)
        d = s.to_dict()
        self.assertEqual(d["n"], 8)
        self.assertIn("perPeriodVolPct", d)

    def test_summary_insufficient_atr_is_none_but_struct_ok(self):
        s = vol.volatility_summary(_flat(2), atr_period=14)
        self.assertEqual(s.n, 2)
        self.assertIsNone(s.atr_pct)
        self.assertIsNone(s.yang_zhang)


if __name__ == "__main__":
    unittest.main()
