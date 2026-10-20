# -*- coding: utf-8 -*-
"""اختبارات G1.65 — تطبيق الخروج المتكيّف (dynamic_exit) المُتحقَّق forward في G1.64.

تثبّت الصيغة المنقولة من exp_021_run.resim_1m_wave على قيم محسوبة يدويًّا، وتؤكّد أنّ
الافتراضيات = السلوك الحالي (recommender_profile='baseline' ⇒ None؛ flag معطّل).
"""
import unittest

from ocobot.domain.dynamic_exit import (
    CHAMPION_RECOMMENDER, DynamicExitConfig, WADAPT_TIGHT, WaveAdaptiveParams,
    lock_floor_frac, next_stop, recommender_profile, trail_distance_pct,
)
from ocobot.domain.recommender import RecommenderParams


class TestTrailDistance(unittest.TestCase):
    def test_clamp_below_min(self):
        # wave_k=1.5 → 1.5*0.2=0.30 < dist_min(0.5)
        self.assertAlmostEqual(trail_distance_pct(0.2), 0.5, places=9)

    def test_in_range(self):
        self.assertAlmostEqual(trail_distance_pct(1.0), 1.5, places=9)

    def test_clamp_above_max(self):
        # 1.5*5.0=7.5 > dist_max(3.0)
        self.assertAlmostEqual(trail_distance_pct(5.0), 3.0, places=9)


class TestLockFloorFrac(unittest.TestCase):
    def test_zero_or_negative_runup(self):
        self.assertEqual(lock_floor_frac(0.0), 0.0)
        self.assertEqual(lock_floor_frac(-3.0), 0.0)

    def test_linear(self):
        # lock_base=0.80, lock_slope=0.040 ⇒ g=1 → 0.84
        self.assertAlmostEqual(lock_floor_frac(1.0), 0.84, places=9)

    def test_capped(self):
        # g=2 → 0.88 (cap) ؛ g=5 → 0.88 (cap)
        self.assertAlmostEqual(lock_floor_frac(2.0), 0.88, places=9)
        self.assertAlmostEqual(lock_floor_frac(5.0), 0.88, places=9)


class TestNextStop(unittest.TestCase):
    def test_locks_profit_floor(self):
        # fill=100, peak=105 (g=5%), atr=1.0 → dist=1.5% ⇒ chandelier=103.425؛
        # lf=min(0.88, 0.80+0.04*5=1.0)=0.88 ⇒ floor=100*(1+0.88*5/100)=104.4 يسيطر.
        self.assertAlmostEqual(next_stop(100.0, 105.0, 99.0, 1.0), 104.4, places=6)

    def test_monotone_never_decreases(self):
        # prev_stop أعلى من كل المرشّحات ⇒ يبقى كما هو (الستوب لا ينزل).
        self.assertAlmostEqual(next_stop(100.0, 103.0, 103.0, 1.0), 103.0, places=6)

    def test_be_floor_when_lock_disabled(self):
        # أرضية القفل مُعطّلة (lock_*=0) لعزل فرع BE: peak=101≥be_trigger(101) ⇒ be_lock=100.3 يسيطر.
        p = WaveAdaptiveParams(lock_base=0.0, lock_slope=0.0, lock_cap=0.0)
        self.assertAlmostEqual(next_stop(100.0, 101.0, 99.0, 5.0, p), 100.3, places=6)

    def test_no_be_below_trigger(self):
        # peak دون be_trigger ⇒ لا قفل BE؛ النتيجة من chandelier/floor فقط، وأعلى من prev.
        out = next_stop(100.0, 100.5, 99.0, 2.0)
        self.assertGreater(out, 99.0)

    def test_zero_fill_guard(self):
        self.assertEqual(next_stop(0.0, 10.0, 5.0, 1.0), 5.0)


class TestRecommenderProfile(unittest.TestCase):
    def test_baseline_is_none(self):
        # baseline = لا تجاوز (يُبقي افتراض موقع النداء الحالي — objective='scalp' في app_wiring)
        self.assertIsNone(recommender_profile("baseline"))

    def test_champion_values(self):
        champ = recommender_profile("champion")
        self.assertIsNotNone(champ)
        self.assertEqual(champ.k_sl, 5.0)
        self.assertEqual(champ.trigger_f, 0.15)
        self.assertEqual(champ.objective, "legacy")

    def test_champion_is_copy(self):
        a = recommender_profile("champion")
        b = recommender_profile("champion")
        self.assertIsNot(a, b)
        self.assertIsNot(a, CHAMPION_RECOMMENDER)

    def test_unknown_raises(self):
        with self.assertRaises(ValueError):
            recommender_profile("nope")


class TestDynamicExitConfig(unittest.TestCase):
    def test_defaults_are_no_change(self):
        c = DynamicExitConfig()
        self.assertFalse(c.enabled)
        self.assertEqual(c.preset, "wadapt_tight")
        self.assertEqual(c.recommender_profile, "baseline")
        self.assertIsNone(c.recommender())
        self.assertAlmostEqual(c.params().lock_base, 0.80, places=9)

    def test_lock_base_override(self):
        c = DynamicExitConfig(lock_base=0.60)
        self.assertAlmostEqual(c.params().lock_base, 0.60, places=9)
        # باقي البروتوكول ثابت
        self.assertEqual(c.params().wave_k, WADAPT_TIGHT.wave_k)
        self.assertEqual(c.params().lock_cap, WADAPT_TIGHT.lock_cap)

    def test_champion_profile_selected(self):
        c = DynamicExitConfig(recommender_profile="champion")
        rp = c.recommender()
        self.assertIsInstance(rp, RecommenderParams)
        self.assertEqual(rp.k_sl, 5.0)
        self.assertEqual(rp.trigger_f, 0.15)

    def test_unknown_preset_raises(self):
        with self.assertRaises(ValueError):
            DynamicExitConfig(preset="bogus").params()


if __name__ == "__main__":
    unittest.main()
