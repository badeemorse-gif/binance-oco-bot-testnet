# -*- coding: utf-8 -*-
"""G1.49 / chunk_2 — اختبارات سياسة التنفيذ الموحّدة (منطق خالص، بلا Qt/شبكة).

يغطّي: السعر القابل للتنفيذ (marketable) تحت أفضل BID، الأرضية الصارمة،
سُلّم الـchase النازل المحدود بالأرضية (تناقص صارم + آخره الأرضية)، وحساب الانزلاق.
"""
import unittest
from decimal import Decimal

from ocobot.domain.market_exit import (
    DEFAULT_BAND_PCT,
    DEFAULT_PRICE_FLOOR_PCT,
    ExitExecutionPolicy,
    compute_slippage_pct,
    flash_crash_floor,
    marketable_sell_price,
    plan_chase_ladder,
)

TICK = Decimal("0.01")


class MarketablePriceTests(unittest.TestCase):
    def test_price_is_below_bid_by_band(self):
        p = marketable_sell_price(Decimal("100"), Decimal("0.2"), TICK)
        self.assertEqual(p, Decimal("99.80"))        # 100*(1-0.002)
        self.assertLess(p, Decimal("100"))           # تحت الـBID ⇒ marketable

    def test_zero_band_equals_bid(self):
        p = marketable_sell_price(Decimal("100"), Decimal("0"), TICK)
        self.assertEqual(p, Decimal("100"))

    def test_negative_band_clamped_to_zero(self):
        p = marketable_sell_price(Decimal("100"), Decimal("-5"), TICK)
        self.assertEqual(p, Decimal("100"))


class FloorTests(unittest.TestCase):
    def test_floor_is_pct_below_bid(self):
        f = flash_crash_floor(Decimal("100"), Decimal("8"), TICK)
        self.assertEqual(f, Decimal("92"))           # 100*(1-0.08)

    def test_default_floor_pct(self):
        self.assertEqual(DEFAULT_PRICE_FLOOR_PCT, Decimal("8"))


class ChaseLadderTests(unittest.TestCase):
    def test_ladder_strictly_decreasing_bounded_last_is_floor(self):
        res = plan_chase_ladder(
            Decimal("100"), TICK,
            band_pct=Decimal("0.2"), chase_step_pct=Decimal("0.2"),
            max_attempts=6, floor_pct=Decimal("1"),   # floor=99
        )
        ladder, floor = res["ladder"], res["floor"]
        self.assertEqual(floor, Decimal("99"))
        self.assertGreaterEqual(len(ladder), 1)
        for a, b in zip(ladder, ladder[1:]):
            self.assertGreater(a, b)                  # تناقص صارم
        for px in ladder:
            self.assertGreaterEqual(px, floor)        # لا نزول تحت الأرضية
        self.assertEqual(ladder[-1], floor)           # آخر محاولة = الأرضية
        self.assertEqual(ladder[0], Decimal("99.80")) # أول محاولة = marketable band

    def test_ladder_never_sells_below_floor_even_with_many_attempts(self):
        res = plan_chase_ladder(
            Decimal("100"), TICK,
            band_pct=Decimal("0.2"), chase_step_pct=Decimal("0.2"),
            max_attempts=50, floor_pct=Decimal("1"),
        )
        for px in res["ladder"]:
            self.assertGreaterEqual(px, res["floor"])
        self.assertEqual(res["ladder"][-1], res["floor"])


class SlippageTests(unittest.TestCase):
    def test_slippage_positive_is_worse(self):
        self.assertEqual(compute_slippage_pct(Decimal("100"), Decimal("99")), Decimal("1"))

    def test_slippage_zero_reference_safe(self):
        self.assertEqual(compute_slippage_pct(Decimal("0"), Decimal("99")), Decimal("0"))


class PolicyTests(unittest.TestCase):
    def test_defaults(self):
        pol = ExitExecutionPolicy()
        self.assertEqual(pol.band_pct, DEFAULT_BAND_PCT)
        self.assertTrue(pol.last_resort_market)       # الخيار (ب) المعتمد

    def test_policy_ladder_matches_floor(self):
        pol = ExitExecutionPolicy(floor_pct=Decimal("1"))
        res = pol.ladder(Decimal("100"), TICK)
        self.assertEqual(res["floor"], Decimal("99"))
        self.assertEqual(res["ladder"][-1], Decimal("99"))


if __name__ == "__main__":
    unittest.main()
