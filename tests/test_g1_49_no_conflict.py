# -*- coding: utf-8 -*-
"""G1.49 chunk_4b — اختبارات لا-تعارض: ربط الـchase الموحّد في الخروج اليدوي +
توسيع إزاحة STOP_LOSS_LIMIT (حارس/قوس سفلي) + بيع واحد وأولوية صحيحة. بلا شبكة، بلا Qt."""
import unittest
from decimal import Decimal
from types import SimpleNamespace

from ocobot.ui.manual_exit import run_manual_market_exit
from ocobot.domain.market_exit import plan_market_exit
from ocobot.domain.guardian_exec import plan_protective_stop, place_protective_stop
from ocobot.domain.guardian_supervisor import GuardianSupervisor
from ocobot.domain.guardian import GuardianSnapshot, GuardianConfig, GuardianAction, evaluate


def _filters(symbol="LSKUSDT"):
    return SimpleNamespace(symbol=symbol, tick_size=Decimal("0.0001"),
                           step_size=Decimal("0.01"), min_qty=Decimal("0.1"),
                           min_notional=Decimal("5"), gap_ticks=1)


class _FakeChaseClient:
    """عميل خروج مُحاكى (IOC/MARKET/إلغاء/قراءة) — يحقّق ما يحتاجه execute_exit_chase."""
    def __init__(self, *, free="100", resting=None, ioc_fills=None, ioc_default="0"):
        self._free = Decimal(str(free)); self._resting = list(resting or [])
        self._ioc_fills = list(ioc_fills or []); self._ioc_default = ioc_default
        self.ioc_calls = []; self.market_calls = []; self.cancels = []
        self.limit_calls = []; self.sll_calls = []
    def get_open_sell_orders(self, symbol): return list(self._resting)
    def get_free_asset_qty(self, asset): return self._free
    def cancel_oco(self, symbol, order_list_id):
        self.cancels.append(order_list_id); return {"ok": True}
    def place_limit_sell_ioc(self, *, symbol, quantity, price, client_order_id):
        self.ioc_calls.append({"quantity": quantity, "price": price})
        ex = self._ioc_fills.pop(0) if self._ioc_fills else self._ioc_default
        if ex == "ALL": ex = quantity
        executed = Decimal(str(ex))
        status = "FILLED" if executed >= quantity else ("PARTIALLY_FILLED" if executed > 0 else "EXPIRED")
        return {"status": status, "executedQty": str(executed)}
    def place_market_sell(self, *, symbol, quantity, client_order_id):
        self.market_calls.append({"quantity": quantity})
        return {"status": "FILLED", "executedQty": str(quantity)}
    # for the fallback (execute_market_exit) path, if ever used:
    def place_limit_sell(self, symbol, quantity, price, client_order_id):
        self.limit_calls.append((quantity, price)); return {"orderId": 1, "status": "NEW"}
    def place_stop_loss_limit(self, symbol, quantity, stop_price, limit_price, client_order_id):
        self.sll_calls.append((quantity,)); return {"orderId": 2, "status": "NEW"}


class ManualExitUnifiedChaseWiring(unittest.TestCase):
    def test_manual_exit_routes_to_chase_when_bid_getter_present(self):
        c = _FakeChaseClient(free="10", ioc_fills=["ALL"])
        r = run_manual_market_exit(
            client=c, symbol="LSKUSDT", base_asset="LSK",
            free_base_qty=Decimal("10"), monitored_qty=Decimal("10"),
            has_resting_protective_sell=False, reference_price=Decimal("100"),
            filters=_filters(), exit_side="upper", bid_getter=lambda: Decimal("100"),
            dry_run=False)
        self.assertEqual(r["action"], "FILLED")
        self.assertGreaterEqual(len(c.ioc_calls), 1)           # مرّ عبر الـchase (IOC)
        self.assertEqual(c.market_calls, [])
        self.assertEqual(c.limit_calls, [])                    # لم يسلك مسار execute_market_exit

    def test_manual_exit_chase_gate_blocks_resting_no_sell(self):
        c = _FakeChaseClient(free="10", ioc_fills=["ALL"], resting=[{"id": 1}])
        r = run_manual_market_exit(
            client=c, symbol="LSKUSDT", base_asset="LSK",
            free_base_qty=Decimal("10"), monitored_qty=Decimal("10"),
            has_resting_protective_sell=True, reference_price=Decimal("100"),
            filters=_filters(), exit_side="upper", bid_getter=lambda: Decimal("100"),
            dry_run=False)
        self.assertEqual(r["action"], "ABORT_GATE")
        self.assertFalse(r["placed"])
        self.assertEqual(c.ioc_calls, [])
        self.assertEqual(c.market_calls, [])

    def test_manual_exit_default_path_unchanged_without_bid_getter(self):
        c = _FakeChaseClient(free="10")
        r = run_manual_market_exit(
            client=c, symbol="LSKUSDT", base_asset="LSK",
            free_base_qty=Decimal("10"), monitored_qty=Decimal("10"),
            has_resting_protective_sell=False, reference_price=Decimal("100"),
            filters=_filters(), exit_side="upper", dry_run=False)   # no bid_getter
        self.assertEqual(r["action"], "PLACED")                 # execute_market_exit LIMIT path
        self.assertEqual(len(c.limit_calls), 1)
        self.assertEqual(c.ioc_calls, [])


class GuardianStopLimitOffset(unittest.TestCase):
    def _gfilters(self):
        return SimpleNamespace(symbol="LSKUSDT", tick_size=Decimal("0.0001"),
                               step_size=Decimal("0.01"), gap_ticks=1)
    def test_offset_widens_stop_limit_below_trigger(self):
        base = plan_protective_stop(Decimal("100"), Decimal("10"), Decimal("1"), self._gfilters())
        wide = plan_protective_stop(Decimal("100"), Decimal("10"), Decimal("1"), self._gfilters(),
                                    stop_limit_offset_pct=Decimal("0.5"))
        self.assertLess(wide["stop_limit"], base["stop_limit"])          # أوسع (أدنى)
        self.assertLess(wide["stop_limit"], wide["stop_trigger"])        # يبقى تحت الزناد
    def test_offset_none_is_byte_identical(self):
        a = plan_protective_stop(Decimal("100"), Decimal("10"), Decimal("1"), self._gfilters())
        b = plan_protective_stop(Decimal("100"), Decimal("10"), Decimal("1"), self._gfilters(),
                                 stop_limit_offset_pct=None)
        self.assertEqual(a, b)
    def test_floor_bounds_offset(self):
        # أرضية 0.3% تمنع النزول تحتها رغم إزاحة كبيرة.
        r = plan_protective_stop(Decimal("100"), Decimal("10"), Decimal("1"), self._gfilters(),
                                 stop_limit_offset_pct=Decimal("5"), price_floor_pct=Decimal("0.3"))
        self.assertGreaterEqual(r["stop_limit"], Decimal("99.7") - Decimal("0.0001"))
    def test_supervisor_accepts_and_stores_offset(self):
        sup = GuardianSupervisor(state_provider=lambda: None, client=object(),
                                 alert_cb=lambda m: None,
                                 stop_limit_offset_pct=Decimal("0.4"),
                                 price_floor_pct=Decimal("0.3"))
        self.assertEqual(sup._stop_limit_offset_pct, Decimal("0.4"))
        self.assertEqual(sup._price_floor_pct, Decimal("0.3"))


class MarketExitLowerOffset(unittest.TestCase):
    def test_lower_offset_widens_gap(self):
        f = _filters()
        base = plan_market_exit(exit_side="lower", reference_price=Decimal("100"),
                                qty=Decimal("10"), filters=f, gap_ticks=1)
        wide = plan_market_exit(exit_side="lower", reference_price=Decimal("100"),
                                qty=Decimal("10"), filters=f, gap_ticks=1,
                                stop_limit_offset_pct=Decimal("0.5"))
        self.assertLess(wide["limit_price"], base["limit_price"])
        self.assertLess(wide["limit_price"], wide["stop_price"])
        self.assertTrue(wide["valid"])
    def test_lower_offset_none_identical(self):
        f = _filters()
        a = plan_market_exit(exit_side="lower", reference_price=Decimal("100"),
                             qty=Decimal("10"), filters=f, gap_ticks=1)
        b = plan_market_exit(exit_side="lower", reference_price=Decimal("100"),
                             qty=Decimal("10"), filters=f, gap_ticks=1,
                             stop_limit_offset_pct=None)
        self.assertEqual(a, b)


class NoConflictPriority(unittest.TestCase):
    def test_resting_sell_makes_guardian_noop(self):
        # بعد خروج يترك بيعًا حمائيًّا قائمًا ⇒ الحارس NOOP (لا تدخّل ثانٍ ⇒ لا بيع مزدوج).
        snap = GuardianSnapshot(symbol="LSKUSDT", state="MONITORING_ACTIVE", in_flight=False,
                                naked_seconds=10.0, has_resting_protective_sell=True,
                                free_base_qty=Decimal("0"), monitored_qty=Decimal("10"))
        d = evaluate(snap, GuardianConfig())
        self.assertEqual(d.action, GuardianAction.NOOP)
    def test_second_manual_exit_aborts_at_reconcile(self):
        # محاولة خروج ثانية بوجود بيع قائم ⇒ البوّابة تمنع (بيع واحد فقط).
        c = _FakeChaseClient(free="10", resting=[{"id": 9}])
        r = run_manual_market_exit(
            client=c, symbol="LSKUSDT", base_asset="LSK",
            free_base_qty=Decimal("10"), monitored_qty=Decimal("10"),
            has_resting_protective_sell=True, reference_price=Decimal("100"),
            filters=_filters(), exit_side="upper", bid_getter=lambda: Decimal("100"),
            dry_run=False)
        self.assertEqual(r["action"], "ABORT_GATE")
        self.assertEqual(c.ioc_calls, [])


if __name__ == "__main__":
    unittest.main()
