# -*- coding: utf-8 -*-
"""اختبارات G1.61 — معايرة السكالبنج للمُرشِّح (objective="scalp").

تغطّي الهندسة الصافية 2:1، تضييق SL عند القصّ، راية أرضية الرسوم، باند النظام
الهادئ مقابل التريند، أرضيات ضوضاء/تكلفة المُشغّل، عدم مساس المسار legacy، و
انحدار شبيه بـ SOL (النمط 18.5/16.3/1.774 لا يتكرّر).
"""
import unittest
from decimal import Decimal

from ocobot.domain.excursion import ExcursionStats
from ocobot.domain.recommender import (Recommendation, RecommenderParams,
                                        recommend)
from ocobot.domain.regime import RegimeSummary
from ocobot.domain.volatility import VolatilitySummary


def _vs(atr_pct=1.0):
    return VolatilitySummary(n=50, last_close=100.0, atr_abs=None, atr_pct=atr_pct,
                             yang_zhang=None, garman_klass=None, parkinson=None,
                             rogers_satchell=None, close_to_close=None, ewma=None)


def _ex(p75_mfe=5.0, p80_mae=1.0, med=0.5):
    return ExcursionStats(count=100, p50_mfe=4.0, p75_mfe=p75_mfe, p90_mfe=8.0,
                          p50_mae=0.5, p80_mae=p80_mae, p90_mae=2.0,
                          median_pullback=med, p75_pullback=0.8)


def _rg(adx=30.0, choppiness=40.0):
    """نظام قابل للضبط: adx عالٍ + choppiness منخفض ⇒ trending؛ adx منخفض ⇒ ranging."""
    return RegimeSummary(n=50, adx=adx, plus_di=25.0, minus_di=10.0,
                         choppiness=choppiness, hurst=0.5, variance_ratio=1.0)


def _scalp(**kw):
    base = dict(objective="scalp", round_trip_cost_pct=0.25, rr_target=2.0,
                quiet_atr_pct=0.6, quiet_band_lo=0.3, quiet_band_hi=0.9)
    base.update(kw)
    return RecommenderParams(**base)


class ScalpGeometryTests(unittest.TestCase):
    def test_net_2to1_when_reachable(self):
        # sl_raw = max(2*1.0, 1.0)=2.0 ; tp_reach = 5.0*adx_factor(=1.1)=5.5
        # tp_need = 2*2 + 3*0.25 = 4.75 <= 5.5 ⇒ tp=4.75, sl=2.0 (لا تضييق)
        rec = recommend(_vs(1.0), _ex(p75_mfe=5.0, p80_mae=1.0), _rg(adx=30.0),
                        None, 100, params=_scalp())
        self.assertIsInstance(rec, Recommendation)
        self.assertNotIn("sl_tightened_for_rr", rec.flags)
        c = 0.25
        tp = float(rec.tp_pct)
        sl = float(rec.sl_pct)
        # (tp - c) ≈ rr*(sl + c)
        self.assertAlmostEqual(tp - c, 2.0 * (sl + c), places=2)

    def test_sl_tightened_and_flag_when_need_exceeds_reach(self):
        # sl_raw = max(2*2.0, 4.0)=4.0 ; tp_need=2*4+3*0.25=8.75
        # tp_reach = p75_mfe(3.0)*1.1=3.3 < 8.75 ⇒ قصّ: tp=3.3, sl=(3.3-0.75)/2=1.275
        rec = recommend(_vs(2.0), _ex(p75_mfe=3.0, p80_mae=4.0), _rg(adx=30.0),
                        None, 100, params=_scalp())
        self.assertIn("sl_tightened_for_rr", rec.flags)
        c = 0.25
        tp = float(rec.tp_pct)
        sl = float(rec.sl_pct)
        self.assertAlmostEqual(tp - c, 2.0 * (sl + c), places=2)
        self.assertLess(sl, 4.0)  # ضُيِّق فعلًا

    def test_below_fee_floor_flag(self):
        # tp_reach صغير جدًّا ⇒ صافي tp < 0.3
        rec = recommend(_vs(0.1), _ex(p75_mfe=0.4, p80_mae=0.1), _rg(adx=30.0),
                        None, 100, params=_scalp())
        self.assertIn("below_fee_floor", rec.flags)


class ScalpTriggerBandTests(unittest.TestCase):
    def test_quiet_band_clamps_trigger(self):
        # ranging + htf_atr_pct<0.6 ⇒ المُشغّل داخل [0.3,0.9]
        rec = recommend(_vs(1.0), _ex(med=5.0), _rg(adx=10.0, choppiness=70.0),
                        None, 100, params=_scalp(), ltf_atr_pct=0.0,
                        htf_atr_pct=0.4)
        self.assertIn("quiet_band", rec.flags)
        tr = float(rec.trigger_pct)
        self.assertGreaterEqual(tr, 0.3)
        self.assertLessEqual(tr, 0.9)

    def test_trending_trigger_not_forced_into_quiet_band(self):
        # trending (adx عالٍ) + طموح مُشغّل كبير ⇒ لا راية quiet_band ولا قصّ عند 0.9
        rec = recommend(_vs(1.0), _ex(med=5.0), _rg(adx=40.0, choppiness=20.0),
                        None, 100, params=_scalp(), ltf_atr_pct=0.0,
                        htf_atr_pct=1.5)
        self.assertNotIn("quiet_band", rec.flags)
        # المُشغّل الخام = med*trigger_f = 5*0.7=3.5 ⇒ أوسع من باند الهدوء
        self.assertGreater(float(rec.trigger_pct), 0.9)

    def test_trigger_respects_cost_and_noise_floors(self):
        # ضوضاء 1m عالية ⇒ trigger ≥ k_noise*noise ؛ وأيضًا ≥ c+buffer
        rec = recommend(_vs(1.0), _ex(med=0.01), _rg(adx=30.0),
                        None, 100, params=_scalp(), ltf_atr_pct=1.2,
                        htf_atr_pct=1.0)
        self.assertGreaterEqual(float(rec.trigger_pct), 1.2 - 1e-9)
        # وأرضية التكلفة c+buffer=0.30 محترمة ضمنًا
        self.assertGreaterEqual(float(rec.trigger_pct), 0.30 - 1e-9)

    def test_trigger_cost_floor_when_noise_zero(self):
        rec = recommend(_vs(1.0), _ex(med=0.001), _rg(adx=30.0),
                        None, 100, params=_scalp(), ltf_atr_pct=0.0,
                        htf_atr_pct=1.0)
        # لا هدوء (htf_atr_pct>=0.6) ⇒ المُشغّل = max(raw, 0, c+buffer=0.30)
        self.assertAlmostEqual(float(rec.trigger_pct), 0.30, places=3)


class LegacyUnchangedTests(unittest.TestCase):
    def test_legacy_path_identical_to_before(self):
        # نفس مُدخلات اختبارات G1.56 الأساسية ⇒ نفس المخرجات (legacy افتراضي)
        vs = VolatilitySummary(n=50, last_close=100.0, atr_abs=None, atr_pct=2.0,
                               yang_zhang=None, garman_klass=None, parkinson=None,
                               rogers_satchell=None, close_to_close=None, ewma=None)
        ex = ExcursionStats(count=100, p50_mfe=4.0, p75_mfe=5.0, p90_mfe=8.0,
                            p50_mae=2.0, p80_mae=3.0, p90_mae=4.0,
                            median_pullback=1.0, p75_pullback=1.5)
        rg = RegimeSummary(n=50, adx=30.0, plus_di=25.0, minus_di=10.0,
                           choppiness=40.0, hurst=0.5, variance_ratio=1.0)
        rec = recommend(vs, ex, rg, None, 100)  # params=None ⇒ legacy
        # sl=max(2*2,3)=4 ; trigger=1*0.7=0.7 ; tp=5*1.1=5.5 (كما في G1.56)
        self.assertEqual(rec.tp_pct, Decimal("5.5"))
        self.assertEqual(rec.sl_pct, Decimal("4.0"))
        self.assertEqual(rec.trigger_pct, Decimal("0.7"))
        self.assertNotIn("objective", rec.rationale)
        for f in ("sl_tightened_for_rr", "below_fee_floor", "quiet_band"):
            self.assertNotIn(f, rec.flags)

    def test_explicit_legacy_objective_matches_default(self):
        p = RecommenderParams(objective="legacy")
        rec = recommend(_vs(2.0), _ex(p75_mfe=5.0, p80_mae=3.0, med=1.0),
                        _rg(adx=30.0), None, 100, params=p)
        self.assertEqual(rec.tp_pct, Decimal("5.5"))
        self.assertEqual(rec.sl_pct, Decimal("4.0"))
        self.assertEqual(rec.trigger_pct, Decimal("0.7"))


class SolRegressionTests(unittest.TestCase):
    """النمط المُبلَّغ (tp=18.5%، sl=16.3%، trigger=1.774% على 1h/horizon=24).

    على فريم السكالبنج (5m) يكون أقصى طموح واقعي (P75(MFE)) صغيرًا؛ نُحاكي ذلك
    بتغذية tp_reach صغير مع MAE/ATR قديمَين ضخمَين، ونؤكّد أن objective=scalp
    يُنتج tp/sl محدودَين ومتّسقَين (net-2:1) و trigger ≥ التكلفة — فلا يتكرّر
    النمط (18.5/16.3/1.774): tp لا يُضخَّم، وSL يُضيَّق ليتّسق مع trigger صغير.
    """
    def test_sol_like_values_bounded_under_scalp(self):
        # القديم: p80_mae=16.3 و ATR عالٍ (نمط 1h). الجديد: tp_reach واقعي صغير
        # (p75_mfe=0.8 على 5m) ⇒ القوس محدود ومتّسق.
        rec = recommend(_vs(8.0), _ex(p75_mfe=1.5, p80_mae=16.3, med=0.1),
                        _rg(adx=30.0), None, 100, params=_scalp(),
                        ltf_atr_pct=0.2, htf_atr_pct=1.0)
        self.assertIsInstance(rec, Recommendation)
        tp = float(rec.tp_pct)
        sl = float(rec.sl_pct)
        tr = float(rec.trigger_pct)
        c = 0.25
        # الهندسة الصافية 2:1 محفوظة
        self.assertAlmostEqual(tp - c, 2.0 * (sl + c), places=2)
        # المُشغّل لا يقلّ عن التكلفة
        self.assertGreaterEqual(tr, c)
        # النمط القديم لا يتكرّر: tp/sl محدودان بعيدًا عن 18.5/16.3
        self.assertLess(tp, 18.5)
        self.assertLess(sl, 16.3)
        # tp أكبر من trigger (قوس متّسق)
        self.assertGreater(tp, tr)

    def test_sol_like_tightens_sl(self):
        # p80_mae الضخم (16.3) ⇒ sl_raw ضخم ⇒ tp_need هائل > tp_reach ⇒ تضييق SL.
        rec = recommend(_vs(8.0), _ex(p75_mfe=0.8, p80_mae=16.3, med=1.774),
                        _rg(adx=30.0), None, 100, params=_scalp(),
                        ltf_atr_pct=0.2, htf_atr_pct=1.0)
        self.assertIn("sl_tightened_for_rr", rec.flags)


if __name__ == "__main__":
    unittest.main()
