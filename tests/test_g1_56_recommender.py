"""اختبارات G1.56 · c4 — مُرشِّح النِّسب (recommender.py)."""
import unittest
from decimal import Decimal

from ocobot.domain.excursion import ExcursionStats
from ocobot.domain.models import SymbolFilters
from ocobot.domain.recommender import (Recommendation, RecommenderParams,
                                       recommend)
from ocobot.domain.regime import LiquidityState, RegimeSummary
from ocobot.domain.volatility import VolatilitySummary


def _vs(atr_pct=2.0):
    return VolatilitySummary(n=50, last_close=100.0, atr_abs=None, atr_pct=atr_pct,
                             yang_zhang=None, garman_klass=None, parkinson=None,
                             rogers_satchell=None, close_to_close=None, ewma=None)


def _ex(p75_mfe=5.0, p80_mae=3.0, med=1.0):
    return ExcursionStats(count=100, p50_mfe=4.0, p75_mfe=p75_mfe, p90_mfe=8.0,
                          p50_mae=2.0, p80_mae=p80_mae, p90_mae=4.0,
                          median_pullback=med, p75_pullback=1.5)


def _rg(adx=30.0):
    return RegimeSummary(n=50, adx=adx, plus_di=25.0, minus_di=10.0,
                         choppiness=40.0, hurst=0.5, variance_ratio=1.0)


FILTERS = SymbolFilters(symbol="X", tick_size=Decimal("0.01"),
                        step_size=Decimal("0.001"), min_qty=Decimal("0.001"),
                        min_notional=Decimal("10"))


class BaseCouplingTests(unittest.TestCase):
    def test_base_values(self):
        rec = recommend(_vs(), _ex(), _rg(), FILTERS, 100)
        self.assertIsInstance(rec, Recommendation)
        # sl = max(2*2, 3)=4 ; trigger = 1*0.7=0.7 ; tp = 5*1.1=5.5
        self.assertEqual(rec.tp_pct, Decimal("5.5"))
        self.assertEqual(rec.sl_pct, Decimal("4.0"))
        self.assertEqual(rec.trigger_pct, Decimal("0.7"))
        self.assertEqual(rec.gap_ticks, 1)
        self.assertNotIn("levels_degenerate", rec.flags)

    def test_to_dict_strings(self):
        d = recommend(_vs(), _ex(), _rg(), FILTERS, 100).to_dict()
        self.assertEqual(d["tpPct"], "5.5")
        self.assertEqual(d["gapTicks"], 1)
        self.assertIn("rationale", d)

    def test_filters_none_ok(self):
        rec = recommend(_vs(), _ex(), _rg(), None, 100)
        self.assertEqual(rec.tp_pct, Decimal("5.5"))
        self.assertNotIn("levels", rec.rationale)

    def test_insufficient_returns_none(self):
        vs_none = VolatilitySummary(n=1, last_close=None, atr_abs=None, atr_pct=None,
                                    yang_zhang=None, garman_klass=None, parkinson=None,
                                    rogers_satchell=None, close_to_close=None, ewma=None)
        ex_none = ExcursionStats(0, None, None, None, None, None, None, None, None)
        self.assertIsNone(recommend(vs_none, ex_none, _rg(), FILTERS, 100))


class HierarchyTests(unittest.TestCase):
    def test_htf_regime_scales_tp(self):
        htf = _rg(adx=50.0)  # adx_factor = 1.3
        rec = recommend(_vs(), _ex(), _rg(adx=10.0), FILTERS, 100, htf_regime=htf)
        self.assertEqual(rec.tp_pct, Decimal("6.5"))  # 5 * 1.3

    def test_ltf_noise_floor_on_trigger(self):
        rec = recommend(_vs(), _ex(), _rg(), FILTERS, 100, ltf_atr_pct=1.5)
        self.assertEqual(rec.trigger_pct, Decimal("1.5"))
        self.assertIn("noise_floor_trigger", rec.flags)


class FlashCrashFloorTests(unittest.TestCase):
    def test_injected_floor_raises_sl(self):
        rec = recommend(_vs(), _ex(), _rg(), FILTERS, 100, flash_crash_floor_pct=6.0)
        self.assertEqual(rec.sl_pct, Decimal("6.0"))
        self.assertIn("flash_crash_floor", rec.flags)

    def test_floor_not_applied_when_below(self):
        rec = recommend(_vs(), _ex(), _rg(), FILTERS, 100, flash_crash_floor_pct=1.0)
        self.assertEqual(rec.sl_pct, Decimal("4.0"))
        self.assertNotIn("flash_crash_floor", rec.flags)


class LiquidityClampTests(unittest.TestCase):
    def test_wide_spread_and_thin(self):
        liq = LiquidityState(avg_quote_volume=500.0, spread_pct=1.0,
                             is_thin=True, is_wide_spread=True)
        rec = recommend(_vs(), _ex(), _rg(), FILTERS, 100, liquidity=liq)
        self.assertEqual(rec.trigger_pct, Decimal("2.0"))   # 1.0 * 2.0
        self.assertEqual(rec.tp_pct, Decimal("4.4"))         # 5.5 * 0.8
        self.assertEqual(rec.gap_ticks, 2)                   # +1 extra
        self.assertIn("liquidity_wide_spread", rec.flags)
        self.assertIn("liquidity_thin", rec.flags)

    def test_ok_liquidity_no_change(self):
        liq = LiquidityState(avg_quote_volume=10_000.0, spread_pct=0.05,
                             is_thin=False, is_wide_spread=False)
        rec = recommend(_vs(), _ex(), _rg(), FILTERS, 100, liquidity=liq)
        self.assertEqual(rec.trigger_pct, Decimal("0.7"))
        self.assertEqual(rec.gap_ticks, 1)


class BoundsAndTickTests(unittest.TestCase):
    def test_tp_max_clamp(self):
        params = RecommenderParams(tp_max_pct=5.0)
        rec = recommend(_vs(), _ex(), _rg(), FILTERS, 100, params=params)
        self.assertEqual(rec.tp_pct, Decimal("5.0"))
        self.assertIn("tp_max", rec.flags)

    def test_tick_floor(self):
        big_tick = SymbolFilters(symbol="Y", tick_size=Decimal("1"),
                                 step_size=Decimal("1"), min_qty=Decimal("1"),
                                 min_notional=Decimal("10"))
        rec = recommend(_vs(), _ex(p75_mfe=0.5, med=0.1), _rg(), big_tick, 100)
        # min_tp_ticks(2) * tick_pct(1.0) = 2.0 floor
        self.assertEqual(rec.tp_pct, Decimal("2.0"))
        self.assertIn("tp_tick_floor", rec.flags)
        self.assertEqual(rec.trigger_pct, Decimal("2.0"))
        self.assertIn("trigger_tick_floor", rec.flags)


if __name__ == "__main__":
    unittest.main()
