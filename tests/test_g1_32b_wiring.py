"""G1.32b chunk_2 — اختبارات ربط القوس بالمنفّذ (BracketExitWiring) بمحاكاة بلا شبكة."""
import unittest
from decimal import Decimal
from types import SimpleNamespace

from ocobot.domain.models import SymbolFilters
from ocobot.domain.bracket import BracketConfig
from ocobot.ui.bracket_wiring import BracketExitWiring
from ocobot.core.market_exit_broker import MarketExitBroker


class FakeRest:
    """عميل REST مُحاكى: يسجّل الاستدعاءات ويعيد ردودًا بسيطة بلا شبكة."""

    def __init__(self, free="100", open_orders=None):
        self._free = str(free)
        self._open = open_orders if open_orders is not None else []
        self.calls = []

    def get_open_orders(self, symbol=None):
        self.calls.append(("open_orders", symbol))
        return list(self._open)

    def get_account(self):
        return {"balances": [{"asset": "LSK", "free": self._free, "locked": "0"}]}

    def signed_request(self, method, path, params=None):
        self.calls.append((method, path, dict(params or [])))
        return {"ok": True, "method": method, "path": path}


def _filters(symbol):
    return SymbolFilters(symbol=symbol, tick_size=Decimal("0.0001"),
                         step_size=Decimal("0.01"), min_qty=Decimal("0.1"),
                         min_notional=Decimal("5"))


def _wiring(rest, *, enabled=True, lower="1.0", upper="2.0", price="2.0",
            dry_run=True, selected=True):
    sel = SimpleNamespace(symbol="LSKUSDT", order_list_id=136428,
                          quantity=Decimal("50")) if selected else None
    return BracketExitWiring(
        broker=MarketExitBroker(rest),
        config_getter=lambda: BracketConfig.from_inputs(enabled, lower, upper),
        price_getter=lambda: price,
        selected_getter=lambda: sel,
        filters_fn=_filters,
        base_asset_fn=lambda s: "LSK",
        dry_run_getter=lambda: dry_run,
    )


class TestBracketWiring(unittest.TestCase):
    def test_disabled_tick_noop(self):
        rest = FakeRest()
        w = _wiring(rest, enabled=False)
        r = w.tick()
        self.assertEqual(r["action"], "DISABLED")
        # لا أيّ أمر على العميل.
        self.assertFalse(any(c[0] in ("POST", "DELETE") for c in rest.calls))

    def test_within_bracket_noop(self):
        rest = FakeRest()
        w = _wiring(rest, price="1.5")
        self.assertEqual(w.tick()["action"], "WITHIN_BRACKET")

    def test_upper_breach_dry_run_no_order(self):
        rest = FakeRest()
        w = _wiring(rest, price="2.0", dry_run=True)
        self.assertEqual(w.tick()["action"], "ARMED")   # G1.49: أول اختراق مُسلَّح
        r = w.tick()
        self.assertEqual(r["action"], "EXIT_TRIGGERED")
        self.assertEqual(r["exit_side"], "upper")
        self.assertEqual(r["result"]["action"], "DRY_RUN")
        self.assertFalse(any(c[0] in ("POST", "DELETE") for c in rest.calls))

    def test_upper_breach_live_places_limit_once(self):
        rest = FakeRest()
        w = _wiring(rest, price="2.0", dry_run=False)
        self.assertEqual(w.tick()["action"], "ARMED")   # G1.49: أول اختراق مُسلَّح
        r = w.tick()
        self.assertEqual(r["result"]["action"], "PLACED")
        posts = [c for c in rest.calls if c[0] == "POST"]
        dels = [c for c in rest.calls if c[0] == "DELETE"]
        self.assertEqual(len(dels), 1)       # ألغى الـ OCO
        self.assertEqual(len(posts), 1)      # وضعًا واحدًا فقط (منع بيع مزدوج)
        self.assertEqual(posts[0][2]["type"], "LIMIT")
        # خروج-واحد: tick ثالث لا يضع ثانيةً.
        w.tick()
        self.assertEqual(len([c for c in rest.calls if c[0] == "POST"]), 1)

    def test_lower_breach_live_places_stop_loss_limit(self):
        rest = FakeRest()
        w = _wiring(rest, price="1.0", dry_run=False)
        self.assertEqual(w.tick()["action"], "ARMED")   # G1.49: أول اختراق مُسلَّح
        r = w.tick()
        self.assertEqual(r["result"]["action"], "PLACED")
        posts = [c for c in rest.calls if c[0] == "POST"]
        self.assertEqual(posts[0][2]["type"], "STOP_LOSS_LIMIT")

    def test_no_selection_safe(self):
        rest = FakeRest()
        w = _wiring(rest, price="2.0", dry_run=False, selected=False)
        self.assertEqual(w.tick()["action"], "ARMED")   # G1.49: أول اختراق مُسلَّح
        r = w.tick()
        self.assertEqual(r["result"]["action"], "NO_SELECTION")


if __name__ == "__main__":
    unittest.main()
