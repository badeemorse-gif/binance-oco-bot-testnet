# -*- coding: utf-8 -*-
"""G1.49 chunk_4a — اختبارات مُنفِّذ الـchase الموحّد execute_exit_chase (بلا شبكة، بلا Qt).

يغطّي: المعاينة الجافّة، الملء بأول IOC، الـchase ثم الملء، ملاذ MARKET عند عدم
الملء، RECONCILE لمنع البيع المزدوج، لا رصيد حرّ، حماية الأرضية (لا سعر تحتها)،
واستدعاء kill_switch/notifier. كل التبعيات محقونة بمحاكاة بلا أيّ شبكة.
"""
import unittest
from decimal import Decimal

from ocobot.domain.market_exit import ExitExecutionPolicy, execute_exit_chase
from ocobot.domain.models import SymbolFilters


def _filters(symbol="LSKUSDT"):
    return SymbolFilters(symbol=symbol, tick_size=Decimal("0.0001"),
                         step_size=Decimal("0.01"), min_qty=Decimal("0.1"),
                         min_notional=Decimal("5"))


class _FakeChaseClient:
    """عميل خروج مُحاكى: يسجّل IOC/MARKET/الإلغاءات ويعيد executedQty مُبرمَجًا."""

    def __init__(self, *, free="100", resting=None, ioc_fills=None, ioc_default="0"):
        self._free = Decimal(str(free))
        self._resting = list(resting or [])
        self._ioc_fills = list(ioc_fills or [])
        self._ioc_default = ioc_default
        self.ioc_calls = []
        self.market_calls = []
        self.cancels = []

    def get_open_sell_orders(self, symbol):
        return list(self._resting)

    def get_free_asset_qty(self, asset):
        return self._free

    def cancel_oco(self, symbol, order_list_id):
        self.cancels.append(order_list_id)
        return {"ok": True}

    def place_limit_sell_ioc(self, *, symbol, quantity, price, client_order_id):
        self.ioc_calls.append({"quantity": quantity, "price": price})
        ex = self._ioc_fills.pop(0) if self._ioc_fills else self._ioc_default
        if ex == "ALL":
            ex = quantity
        executed = Decimal(str(ex))
        if executed >= quantity:
            status = "FILLED"
        elif executed > 0:
            status = "PARTIALLY_FILLED"
        else:
            status = "EXPIRED"
        return {"status": status, "executedQty": str(executed)}

    def place_market_sell(self, *, symbol, quantity, client_order_id):
        self.market_calls.append({"quantity": quantity})
        return {"status": "FILLED", "executedQty": str(quantity)}


def _bid(value="100"):
    return lambda: Decimal(value)


class ExitChaseTests(unittest.TestCase):
    def test_dry_run_previews_ladder_no_side_effects(self):
        c = _FakeChaseClient()
        r = execute_exit_chase(client=c, symbol="LSKUSDT", base_asset="LSK",
                               bid_getter=_bid("100"), target_qty=Decimal("10"),
                               filters=_filters(), client_order_id="cx", dry_run=True)
        self.assertEqual(r["action"], "DRY_RUN")
        self.assertGreaterEqual(len(r["ladder"]), 1)
        self.assertEqual(c.ioc_calls, [])
        self.assertEqual(c.market_calls, [])

    def test_first_ioc_fills_fully(self):
        c = _FakeChaseClient(ioc_fills=["ALL"])
        r = execute_exit_chase(client=c, symbol="LSKUSDT", base_asset="LSK",
                               bid_getter=_bid("100"), target_qty=Decimal("10"),
                               filters=_filters(), client_order_id="cx", dry_run=False)
        self.assertEqual(r["action"], "FILLED")
        self.assertEqual(len(c.ioc_calls), 1)
        self.assertEqual(c.market_calls, [])
        self.assertEqual(r["filled_qty"], Decimal("10"))

    def test_chase_then_fills(self):
        c = _FakeChaseClient(free="10", ioc_fills=["4", "ALL"])
        r = execute_exit_chase(client=c, symbol="LSKUSDT", base_asset="LSK",
                               bid_getter=_bid("100"), target_qty=Decimal("10"),
                               filters=_filters(), client_order_id="cx", dry_run=False)
        self.assertEqual(r["action"], "FILLED")
        self.assertEqual(len(c.ioc_calls), 2)
        self.assertEqual(c.market_calls, [])

    def test_last_resort_market_when_ioc_never_fills(self):
        c = _FakeChaseClient(free="10", ioc_default="0")
        r = execute_exit_chase(client=c, symbol="LSKUSDT", base_asset="LSK",
                               bid_getter=_bid("100"), target_qty=Decimal("10"),
                               filters=_filters(), client_order_id="cx",
                               policy=ExitExecutionPolicy(), dry_run=False)
        self.assertEqual(r["action"], "MARKET_FALLBACK")
        self.assertTrue(r["market_fallback"])
        self.assertEqual(len(c.market_calls), 1)
        self.assertEqual(c.market_calls[0]["quantity"], Decimal("10"))
        self.assertEqual(len(c.ioc_calls), ExitExecutionPolicy().chase_max_attempts)

    def test_reconcile_aborts_on_resting_sell(self):
        c = _FakeChaseClient(resting=[{"orderId": 1}])
        r = execute_exit_chase(client=c, symbol="LSKUSDT", base_asset="LSK",
                               bid_getter=_bid("100"), target_qty=Decimal("10"),
                               filters=_filters(), client_order_id="cx",
                               order_list_id=99, dry_run=False)
        self.assertEqual(r["action"], "ABORT_PROTECTED")
        self.assertEqual(c.ioc_calls, [])
        self.assertEqual(c.market_calls, [])
        self.assertEqual(c.cancels, [99])

    def test_no_free_qty_aborts(self):
        c = _FakeChaseClient(free="0")
        r = execute_exit_chase(client=c, symbol="LSKUSDT", base_asset="LSK",
                               bid_getter=_bid("100"), target_qty=Decimal("10"),
                               filters=_filters(), client_order_id="cx", dry_run=False)
        self.assertEqual(r["action"], "ABORT_NO_FREE_QTY")
        self.assertEqual(c.ioc_calls, [])

    def test_ioc_prices_never_below_floor(self):
        pol = ExitExecutionPolicy(band_pct=Decimal("0.2"), chase_step_pct=Decimal("5"),
                                  chase_max_attempts=6, floor_pct=Decimal("8"))
        c = _FakeChaseClient(free="10", ioc_default="0")
        r = execute_exit_chase(client=c, symbol="LSKUSDT", base_asset="LSK",
                               bid_getter=_bid("100"), target_qty=Decimal("10"),
                               filters=_filters(), client_order_id="cx",
                               policy=pol, dry_run=False)
        floor = r["floor"]
        self.assertTrue(c.ioc_calls)
        for call in c.ioc_calls:
            self.assertGreaterEqual(call["price"], floor)
        self.assertEqual(r["action"], "MARKET_FALLBACK")

    def test_kill_switch_and_notifier_invoked(self):
        c = _FakeChaseClient(ioc_fills=["ALL"])
        flags = {"killed": False, "noted": None}

        def _kill():
            flags["killed"] = True

        def _note(res):
            flags["noted"] = res["action"]

        execute_exit_chase(client=c, symbol="LSKUSDT", base_asset="LSK",
                           bid_getter=_bid("100"), target_qty=Decimal("10"),
                           filters=_filters(), client_order_id="cx",
                           kill_switch=_kill, notifier=_note, dry_run=False)
        self.assertTrue(flags["killed"])
        self.assertEqual(flags["noted"], "FILLED")


if __name__ == "__main__":
    unittest.main()
