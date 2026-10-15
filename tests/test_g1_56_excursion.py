"""اختبارات G1.56 · c2 — تحليل الحركة MFE/MAE + عمق الارتداد (excursion.py)."""
import unittest

from ocobot.domain import excursion as ex
from ocobot.domain.volatility import Candle


class FavorablePctTests(unittest.TestCase):
    def test_long_short_signs(self):
        self.assertAlmostEqual(ex.favorable_pct(100, 105, "long"), 5.0, places=12)
        self.assertAlmostEqual(ex.favorable_pct(100, 105, "short"), -5.0, places=12)
        self.assertAlmostEqual(ex.favorable_pct(100, 90, "short"), 10.0, places=12)

    def test_guards(self):
        self.assertEqual(ex.favorable_pct(0, 100), 0.0)
        with self.assertRaises(ValueError):
            ex.favorable_pct(100, 105, "sideways")


class MfeMaeTests(unittest.TestCase):
    def test_long(self):
        mfe, mae = ex.mfe_mae([105, 110], [98, 102], entry=100, side="long")
        self.assertAlmostEqual(mfe, 10.0, places=12)
        self.assertAlmostEqual(mae, 2.0, places=12)

    def test_short_mirror(self):
        mfe, mae = ex.mfe_mae([105, 110], [98, 102], entry=100, side="short")
        self.assertAlmostEqual(mfe, 2.0, places=12)
        self.assertAlmostEqual(mae, 10.0, places=12)

    def test_none_on_empty(self):
        self.assertIsNone(ex.mfe_mae([], [], 100))
        self.assertIsNone(ex.mfe_mae([1], [1], 0))


class PullbackTests(unittest.TestCase):
    PATH = [100, 110, 105, 115, 108, 120]

    def test_max_pullback(self):
        self.assertAlmostEqual(ex.max_pullback_pct(self.PATH, "long"),
                               7.0 / 115.0 * 100.0, places=12)

    def test_pullback_depths(self):
        depths = ex.pullback_depths(self.PATH, "long")
        self.assertEqual(len(depths), 2)
        self.assertAlmostEqual(depths[0], 5.0 / 110.0 * 100.0, places=12)
        self.assertAlmostEqual(depths[1], 7.0 / 115.0 * 100.0, places=12)

    def test_monotonic_up_no_pullback(self):
        self.assertEqual(ex.max_pullback_pct([1, 2, 3, 4], "long"), 0.0)
        self.assertEqual(ex.pullback_depths([1, 2, 3, 4], "long"), [])

    def test_short_side_mirror(self):
        # هبوط متّصل: لا ارتداد صاعد
        self.assertEqual(ex.max_pullback_pct([100, 90, 80], "short"), 0.0)
        # قاع ثم ارتداد صاعد
        self.assertAlmostEqual(ex.max_pullback_pct([100, 90, 99], "short"),
                               (99.0 - 90.0) / 90.0 * 100.0, places=12)

    def test_too_short(self):
        self.assertEqual(ex.max_pullback_pct([100], "long"), 0.0)
        self.assertEqual(ex.pullback_depths([100], "long"), [])


class SimulateTests(unittest.TestCase):
    CANDLES = [
        Candle(100, 101, 99, 100),
        Candle(100, 110, 95, 108),
        Candle(108, 112, 100, 109),
        Candle(109, 115, 105, 114),
    ]

    def test_counts_and_values(self):
        s = ex.simulate_excursions(self.CANDLES, horizon=2, step=1, side="long")
        self.assertEqual(len(s), 2)
        self.assertAlmostEqual(s.mfe[0], 12.0, places=12)      # 112/100
        self.assertAlmostEqual(s.mae[0], 5.0, places=12)       # 1-95/100
        self.assertAlmostEqual(s.mfe[1], (115.0 / 108.0 - 1) * 100, places=10)
        self.assertAlmostEqual(s.mae[1], (1 - 100.0 / 108.0) * 100, places=10)
        self.assertEqual(s.pullback, [0.0, 0.0])

    def test_insufficient_window_empty(self):
        s = ex.simulate_excursions(self.CANDLES, horizon=10)
        self.assertEqual(len(s), 0)

    def test_validation(self):
        with self.assertRaises(ValueError):
            ex.simulate_excursions(self.CANDLES, horizon=0)
        with self.assertRaises(ValueError):
            ex.simulate_excursions(self.CANDLES, horizon=2, step=0)


class StatsTests(unittest.TestCase):
    def test_summary_ordering_and_dict(self):
        samples = ex.ExcursionSamples(
            mfe=[2, 4, 6, 8, 10],
            mae=[1, 2, 3, 4, 5],
            pullback=[0.5, 1.0, 1.5, 2.0, 2.5],
        )
        st = ex.summarize_excursions(samples)
        self.assertEqual(st.count, 5)
        self.assertLessEqual(st.p50_mfe, st.p75_mfe)
        self.assertLessEqual(st.p75_mfe, st.p90_mfe)
        self.assertLessEqual(st.p50_mae, st.p80_mae)
        self.assertLessEqual(st.p80_mae, st.p90_mae)
        self.assertEqual(st.median_pullback, 1.5)
        d = st.to_dict()
        self.assertEqual(d["count"], 5)
        self.assertIn("p80Mae", d)

    def test_empty_samples_none(self):
        st = ex.summarize_excursions(ex.ExcursionSamples())
        self.assertEqual(st.count, 0)
        self.assertIsNone(st.p75_mfe)
        self.assertIsNone(st.p80_mae)

    def test_excursion_stats_shortcut(self):
        candles = SimulateTests.CANDLES
        st = ex.excursion_stats(candles, horizon=2, step=1)
        self.assertEqual(st.count, 2)
        self.assertIsNotNone(st.p75_mfe)


if __name__ == "__main__":
    unittest.main()
