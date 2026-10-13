"""G1.32a chunk_2 — اختبارات تسلسل execute_market_exit بمحاكاة عميل (بلا شبكة)."""
import unittest
from decimal import Decimal

from ocobot.domain.models import SymbolFilters
from ocobot.domain.market_exit import execute_market_exit, EXIT_LOWER, EXIT_UPPER


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


class FakeClient:
    """عميل مُحاكى يسجّل ترتيب الاستدعاءات ولا يلمس أيّ شبكة."""

    def __init__(self, free="100", resting=None):
        self.free = Decimal(str(free))
        self.resting = list(resting) if resting is not None else []
        self.calls = []
        self.cancelled = []
        self.placed = []

    def get_open_sell_orders(self, symbol):
        self.calls.append(("reconcile", symbol))
        return list(self.resting)

    def get_free_asset_qty(self, asset):
        self.calls.append(("free", asset))
        return self.free

    def cancel_oco(self, symbol, order_list_id):
        self.calls.append(("cancel", order_list_id))
        self.cancelled.append(order_list_id)
        return {"ok": True, "orderListId": order_list_id}

    def place_stop_loss_limit(self, symbol, quantity, stop_price, limit_price, client_order_id):
        self.calls.append(("place_sll", client_order_id))
        self.placed.append(("STOP_LOSS_LIMIT", quantity, stop_price, limit_price))
        return {"ok": True, "type": "STOP_LOSS_LIMIT"}

    def place_limit_sell(self, symbol, quantity, price, client_order_id):
        self.calls.append(("place_limit", client_order_id))
        self.placed.append(("LIMIT", quantity, price))
        return {"ok": True, "type": "LIMIT"}

    def place_market_sell(self, symbol, quantity, client_order_id):
        self.calls.append(("place_market", client_order_id))
        self.placed.append(("MARKET", quantity))
        return {"ok": True, "type": "MARKET"}


def _run(client, **over):
    kw = dict(
        client=client, symbol="LSKUSDT", base_asset="LSK", exit_side=EXIT_LOWER,
        reference_price=Decimal("1.0000"), target_qty=Decimal("50"), filters=_filters(),
        client_order_id="exit-1", order_list_id=136428, dry_run=False,
    )
    kw.update(over)
    return execute_market_exit(**kw)


class TestExitSequenceHappy(unittest.TestCase):
    def test_lower_places_stop_loss_limit_once_in_order(self):
        c = FakeClient(free="100", resting=[])
        order = []
        res = _run(c, kill_switch=lambda: order.append("kill"))
        self.assertEqual(res["action"], "PLACED")
        self.assertTrue(res["placed"])
        self.assertEqual(len(c.placed), 1)
        self.assertEqual(c.placed[0][0], "STOP_LOSS_LIMIT")
        self.assertEqual(c.cancelled, [136428])
        # الترتيب: kill ⇐ cancel ⇐ reconcile ⇐ place
        names = [x[0] for x in c.calls]
        self.assertTrue(order == ["kill"])  # kill_switch نُفّذ
        self.assertLess(names.index("cancel"), names.index("reconcile"))
        self.assertLess(names.index("reconcile"), names.index("place_sll"))

    def test_upper_places_limit_once(self):
        c = FakeClient(free="100", resting=[])
        res = _run(c, exit_side=EXIT_UPPER, reference_price=Decimal("2.0000"))
        self.assertEqual(res["action"], "PLACED")
        self.assertEqual(len(c.placed), 1)
        self.assertEqual(c.placed[0][0], "LIMIT")


class TestExitSequenceDoubleSellGuard(unittest.TestCase):
    def test_abort_when_resting_sell_after_cancel(self):
        # الإلغاء لم يُزل البيع الحمائي ⇒ منع بيع ثانٍ.
        c = FakeClient(free="100", resting=[{"orderId": 1, "side": "SELL"}])
        res = _run(c)
        self.assertEqual(res["action"], "ABORT_PROTECTED")
        self.assertFalse(res["placed"])
        self.assertEqual(c.placed, [])


class TestExitSequenceGuards(unittest.TestCase):
    def test_no_free_qty_aborts(self):
        c = FakeClient(free="0", resting=[])
        res = _run(c)
        self.assertEqual(res["action"], "ABORT_NO_FREE_QTY")
        self.assertEqual(c.placed, [])

    def test_dust_aborts_invalid_filters(self):
        c = FakeClient(free="0.05", resting=[])
        res = _run(c, target_qty=Decimal("0.05"))
        self.assertEqual(res["action"], "ABORT_INVALID_FILTERS")
        self.assertEqual(res["reason"], "below_lot_size_min_qty")
        self.assertEqual(c.placed, [])

    def test_eff_qty_capped_by_free(self):
        c = FakeClient(free="7", resting=[])
        res = _run(c, target_qty=Decimal("50"))
        self.assertEqual(res["action"], "PLACED")
        # الكمية الموضوعة = floor_to_step(min(50,7)) = 7
        self.assertEqual(c.placed[0][1], Decimal("7"))


class TestExitSequenceDryRun(unittest.TestCase):
    def test_dry_run_has_no_side_effects(self):
        c = FakeClient(free="100", resting=[{"orderId": 1}])
        order = []
        res = _run(c, dry_run=True, kill_switch=lambda: order.append("kill"))
        self.assertEqual(res["action"], "DRY_RUN")
        self.assertFalse(res["placed"])
        self.assertEqual(c.placed, [])
        self.assertEqual(c.cancelled, [])
        self.assertEqual(order, [])          # لا kill_switch
        self.assertEqual(c.calls, [])        # لا أيّ استدعاء عميل
        self.assertTrue(res["plan"]["valid"])


class TestExitSequenceNotifier(unittest.TestCase):
    def test_notifier_called_on_placed(self):
        c = FakeClient(free="100", resting=[])
        seen = []
        res = _run(c, notifier=lambda r: seen.append(r["action"]))
        self.assertEqual(res["action"], "PLACED")
        self.assertEqual(seen, ["PLACED"])


if __name__ == "__main__":
    unittest.main()
