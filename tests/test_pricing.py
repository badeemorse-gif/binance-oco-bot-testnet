"""اختبارات حساب الأسعار الثلاثة (M2 / D4, D5, D6, D8)."""
import unittest
from decimal import Decimal

from ocobot.domain.pricing import (
    compute_levels,
    floor_to_step,
    is_multiple_of,
    max_available_stop,
    round_to_tick,
)


class TestPricing(unittest.TestCase):
    def test_round_to_tick(self):
        # D8: تقريب لأقرب مضاعف tickSize (ROUND_HALF_UP)
        self.assertEqual(round_to_tick(Decimal("0.052615"), Decimal("0.00001")),
                         Decimal("0.05262"))  # 0.0526150 → half-up
        self.assertEqual(round_to_tick(Decimal("70000.004"), Decimal("0.01")),
                         Decimal("70000"))
        self.assertEqual(round_to_tick(Decimal("70000.006"), Decimal("0.01")),
                         Decimal("70000.01"))
        # tick falsy → أعِد السعر كما هو
        self.assertEqual(round_to_tick(Decimal("1.2345"), Decimal("0")),
                         Decimal("1.2345"))

    def test_floor_to_step(self):
        # D7: كمية تُنزَّل لأقرب مضاعف أدنى (ROUND_DOWN)
        self.assertEqual(floor_to_step(Decimal("0.49999"), Decimal("0.0001")),
                         Decimal("0.4999"))
        self.assertEqual(floor_to_step(Decimal("0.5"), Decimal("0.0001")),
                         Decimal("0.5"))
        self.assertEqual(floor_to_step(Decimal("0.00035"), Decimal("0.0001")),
                         Decimal("0.0003"))

    def test_is_multiple_of(self):
        self.assertTrue(is_multiple_of(Decimal("0.05262"), Decimal("0.00001")))
        self.assertFalse(is_multiple_of(Decimal("0.052625"), Decimal("0.00001")))
        self.assertTrue(is_multiple_of(Decimal("5"), Decimal("0")))  # unit falsy → True

    def test_compute_levels_design_example(self):
        # مثال التصميم الحرفي: reference 0.05060, tp 4%, sl 2%, tick 0.00001, gap 1
        tp, trg, lim = compute_levels(
            Decimal("0.05060"), Decimal("4"), Decimal("2"), Decimal("0.00001")
        )
        self.assertEqual(tp, Decimal("0.05262"))
        self.assertEqual(trg, Decimal("0.04959"))
        self.assertEqual(lim, Decimal("0.04958"))
        # D4: الترتيب الصارم Stop Limit < Stop Trigger < TP (Last = reference بينهما)
        self.assertTrue(lim < trg < tp)
        self.assertTrue(lim < Decimal("0.05060") < tp)

    def test_compute_levels_gap_is_default_one_tick(self):
        # D5: الفجوة الافتراضية = 1 tick بين Trigger و Limit
        tp, trg, lim = compute_levels(
            Decimal("100"), Decimal("2"), Decimal("2"), Decimal("0.01")
        )
        self.assertEqual(trg - lim, Decimal("0.01"))

    def test_max_available_stop_below_last(self):
        # D4: أكبر مضاعف tick أدنى من السعر الأخير بصرامة
        self.assertEqual(max_available_stop(Decimal("100.005"), Decimal("0.01")),
                         Decimal("100"))
        # last نفسه مضاعف tick → يجب أن ينزل tick واحدًا للأسفل (بصرامة)
        self.assertEqual(max_available_stop(Decimal("100.00"), Decimal("0.01")),
                         Decimal("99.99"))
        self.assertLess(max_available_stop(Decimal("100.00"), Decimal("0.01")),
                        Decimal("100.00"))


if __name__ == "__main__":
    unittest.main()
