"""G1.33 — نِسب تسعير قوس الخروج قابلة للتعديل: pricing_kwargs + تمرير wiring + UI."""
import unittest
from decimal import Decimal
from types import SimpleNamespace

from ocobot.domain.models import SymbolFilters
from ocobot.domain.bracket import BracketConfig, FLOOR_MAX_PCT
from ocobot.ui.bracket_wiring import BracketExitWiring
from ocobot.core.market_exit_broker import MarketExitBroker


class TestPricingKwargs(unittest.TestCase):
    def test_empty_returns_no_kwargs(self):
        self.assertEqual(BracketConfig.from_inputs(True, "1", "2").pricing_kwargs(), {})

    def test_set_values_mapped(self):
        c = BracketConfig.from_inputs(True, "1", "2", slip_pct="0.5", sl_pct="2",
                                      floor_pct="10", gap_ticks="3")
        k = c.pricing_kwargs()
        self.assertEqual(k["slip_pct"], Decimal("0.5"))
        self.assertEqual(k["emergency_sl_pct"], Decimal("2"))
        self.assertEqual(k["price_floor_pct"], Decimal("10"))
        self.assertEqual(k["gap_ticks"], 3)

    def test_floor_clamped_to_max(self):
        c = BracketConfig.from_inputs(True, "1", "2", floor_pct="99")
        self.assertEqual(c.pricing_kwargs()["price_floor_pct"], FLOOR_MAX_PCT)

    def test_invalid_or_nonpositive_ignored(self):
        c = BracketConfig.from_inputs(True, "1", "2", slip_pct="abc", sl_pct="-1", gap_ticks="0")
        self.assertEqual(c.pricing_kwargs(), {})


class _FakeRest:
    def __init__(self, free="100"):
        self._free = str(free)
        self.calls = []

    def get_open_orders(self, symbol=None):
        self.calls.append(("open_orders", symbol))
        return []

    def get_account(self):
        return {"balances": [{"asset": "LSK", "free": self._free, "locked": "0"}]}

    def signed_request(self, method, path, params=None):
        self.calls.append((method, path, dict(params or [])))
        return {"ok": True}


def _wiring(rest, *, slip=None, sl=None, floor=None, gap=None, price="2.0"):
    sel = SimpleNamespace(symbol="LSKUSDT", order_list_id=1, quantity=Decimal("50"))
    cfg = BracketConfig.from_inputs(True, "1.0", "2.0", slip_pct=slip, sl_pct=sl,
                                    floor_pct=floor, gap_ticks=gap)
    return BracketExitWiring(
        broker=MarketExitBroker(rest),
        config_getter=lambda: cfg,
        price_getter=lambda: price,
        selected_getter=lambda: sel,
        filters_fn=lambda s: SymbolFilters(symbol=s, tick_size=Decimal("0.0001"),
                                           step_size=Decimal("0.01"), min_qty=Decimal("0.1"),
                                           min_notional=Decimal("5")),
        base_asset_fn=lambda s: "LSK",
        dry_run_getter=lambda: False,
    )


def _post(rest):
    return [c for c in rest.calls if c[0] == "POST"][0][2]


class TestWiringPassthrough(unittest.TestCase):
    def test_default_slip_upper_price(self):
        rest = _FakeRest()
        w = _wiring(rest, price="2.0")
        w.tick(); w.tick()   # G1.49: wick-debounce — تِكّتان لتأكيد الاختراق
        p = _post(rest)
        self.assertEqual(p["type"], "LIMIT")
        self.assertEqual(Decimal(p["price"]), Decimal("1.998"))  # 2*(1-0.1%) الافتراضي

    def test_custom_slip_changes_upper_price(self):
        rest = _FakeRest()
        w = _wiring(rest, price="2.0", slip="0.5")
        w.tick(); w.tick()   # G1.49: wick-debounce — تِكّتان لتأكيد الاختراق
        self.assertEqual(Decimal(_post(rest)["price"]), Decimal("1.99"))  # 2*(1-0.5%)

    def test_custom_sl_changes_lower_stop(self):
        rest = _FakeRest()
        w = _wiring(rest, price="1.0", sl="2")
        w.tick(); w.tick()   # G1.49: wick-debounce — تِكّتان لتأكيد الاختراق
        p = _post(rest)
        self.assertEqual(p["type"], "STOP_LOSS_LIMIT")
        self.assertEqual(Decimal(p["stopPrice"]), Decimal("0.98"))  # 1*(1-2%)


class TestBracketPricingUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from ocobot.ui._qt import QApplication
        cls._app = QApplication.instance() or QApplication([])

    def test_pricing_fields_present_and_read(self):
        from ocobot.ui.monitoring import DynamicMonitoringScreen
        s = DynamicMonitoringScreen()
        s._bracket_slip_edit.setText("0.5")
        s._bracket_sl_edit.setText("2")
        s._bracket_floor_edit.setText("10")
        s._bracket_gap_edit.setText("3")
        k = s.bracket_config().pricing_kwargs()
        self.assertEqual(k["slip_pct"], Decimal("0.5"))
        self.assertEqual(k["emergency_sl_pct"], Decimal("2"))
        self.assertEqual(k["price_floor_pct"], Decimal("10"))
        self.assertEqual(k["gap_ticks"], 3)

    def test_empty_pricing_fields_use_defaults(self):
        from ocobot.ui.monitoring import DynamicMonitoringScreen
        s = DynamicMonitoringScreen()
        self.assertEqual(s.bracket_config().pricing_kwargs(), {})


if __name__ == "__main__":
    unittest.main()
