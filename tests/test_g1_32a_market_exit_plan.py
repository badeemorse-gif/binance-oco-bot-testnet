"""G1.32a chunk_1 — اختبارات الدالة الخالصة plan_market_exit (بلا شبكة)."""
import unittest
from decimal import Decimal

from ocobot.domain.models import SymbolFilters
from ocobot.domain.market_exit import plan_market_exit, EXIT_LOWER, EXIT_UPPER


def _filters(**kw):
    base = dict(
        symbol="LSKUSDT",
        tick_size=Decimal("0.0001"),
        step_size=Decimal("0.01"),
        min_qty=Decimal("0.1"),
        min_notional=Decimal("5"),
    )
    base.update(kw)
    return SymbolFilters(**base)


class TestPlanMarketExitLower(unittest.TestCase):
    def test_lower_is_stop_loss_limit_marketable_with_floor(self):
        p = plan_market_exit(exit_side=EXIT_LOWER, reference_price=Decimal("1.0000"),
                             qty=Decimal("100"), filters=_filters())
        self.assertTrue(p["valid"], p)
        self.assertEqual(p["type"], "STOP_LOSS_LIMIT")
        self.assertEqual(p["side"], "SELL")
        # الزناد أدنى من المرجع (marketable) و limit أدنى من الزناد بصرامة.
        self.assertLess(p["stop_price"], Decimal("1.0000"))
        self.assertLess(p["limit_price"], p["stop_price"])
        # limit لا يقلّ عن الأرضية (ضد الفلاش-كراش).
        self.assertGreaterEqual(p["limit_price"], p["price_floor"])

    def test_quantity_floored_to_step(self):
        p = plan_market_exit(exit_side=EXIT_LOWER, reference_price=Decimal("2"),
                             qty=Decimal("10.1234"), filters=_filters())
        self.assertEqual(p["quantity"], Decimal("10.12"))


class TestPlanMarketExitUpper(unittest.TestCase):
    def test_upper_is_limit_marketable_known_price(self):
        p = plan_market_exit(exit_side=EXIT_UPPER, reference_price=Decimal("2.0000"),
                             qty=Decimal("50"), filters=_filters())
        self.assertTrue(p["valid"], p)
        self.assertEqual(p["type"], "LIMIT")
        self.assertIsNotNone(p["price"])
        self.assertIsNone(p["stop_price"])
        # SELL LIMIT أدنى بقليل من المرجع ⇒ قابل للتنفيذ فورًا.
        self.assertLessEqual(p["price"], Decimal("2.0000"))


class TestPlanFiltersGuards(unittest.TestCase):
    def test_dust_below_min_qty_invalid(self):
        p = plan_market_exit(exit_side=EXIT_UPPER, reference_price=Decimal("2"),
                             qty=Decimal("0.05"), filters=_filters())
        self.assertFalse(p["valid"])
        self.assertEqual(p["reason"], "below_lot_size_min_qty")

    def test_below_min_notional_invalid(self):
        p = plan_market_exit(exit_side=EXIT_UPPER, reference_price=Decimal("1"),
                             qty=Decimal("1"), filters=_filters(min_notional=Decimal("1000")))
        self.assertFalse(p["valid"])
        self.assertEqual(p["reason"], "below_min_notional")

    def test_zero_qty_after_floor_invalid(self):
        p = plan_market_exit(exit_side=EXIT_LOWER, reference_price=Decimal("5"),
                             qty=Decimal("0.4"),
                             filters=_filters(step_size=Decimal("1"), min_qty=Decimal("1")))
        self.assertFalse(p["valid"])
        self.assertEqual(p["reason"], "zero_qty_after_floor")

    def test_unknown_side_invalid(self):
        p = plan_market_exit(exit_side="sideways", reference_price=Decimal("2"),
                             qty=Decimal("10"), filters=_filters())
        self.assertFalse(p["valid"])
        self.assertEqual(p["reason"], "unknown_exit_side")


class TestPlanMarketAdvanced(unittest.TestCase):
    def test_market_only_when_explicitly_allowed(self):
        p = plan_market_exit(exit_side=EXIT_LOWER, reference_price=Decimal("2"),
                             qty=Decimal("50"), filters=_filters(), allow_market=True)
        self.assertTrue(p["valid"], p)
        self.assertEqual(p["type"], "MARKET")
        self.assertIsNone(p["price"])
        self.assertIsNone(p["stop_price"])


if __name__ == "__main__":
    unittest.main()
