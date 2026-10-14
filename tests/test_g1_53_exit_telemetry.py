# -*- coding: utf-8 -*-
"""G1.53 chunk_2 — اختبارات telemetry تنفيذ الخروج (exit_execution) عبر audit_sink.

يُثبت (بلا شبكة، بلا Qt):
  - ``audit_sink`` محقون default None ⇒ لا إرسال ولا تغيير سلوك (opt-in، لا انحدار).
  - ``execute_exit_chase`` الحقيقي يُرسِل سجلّ ``exit_execution`` واحدًا بالقيم
    المحسوبة (source/slippage_pct/reached_floor/attempts_used/qty) — Decimal.
  - الـdry_run مع audit_sink يُرسِل سجلًّا (dry_run=True) **بلا أي أثر جانبي**
    على الوسيط (لا IOC ولا MARKET).
  - استثناء من audit_sink لا يُفشِل الخروج (دفاعي).
  - ``execute_market_exit`` (PLACED) يُرسِل سجلًّا بنوع الأمر من الخطّة.
  - تكامل: السجلّات المُرسَلة تُقرأ عبر profitability.extract_exit_executions
    وتُغذّي profitability_by_mode.

قابل للتشغيل عبر: python -m unittest tests.test_g1_53_exit_telemetry
"""
import unittest
from decimal import Decimal

from ocobot.domain.market_exit import (
    build_exit_execution_record,
    execute_exit_chase,
    execute_market_exit,
)
from ocobot.domain.models import SymbolFilters
from ocobot.domain.profitability import extract_exit_executions, profitability_by_mode


def _filters(symbol="LSKUSDT"):
    return SymbolFilters(symbol=symbol, tick_size=Decimal("0.0001"),
                         step_size=Decimal("0.01"), min_qty=Decimal("0.1"),
                         min_notional=Decimal("5"))


def _bid(value="100"):
    return lambda: Decimal(value)


class _Sink:
    """audit_sink مُسجِّل: يلتقط (event, details) كسجلّ تدقيق {event, details}."""

    def __init__(self):
        self.records = []

    def __call__(self, event, details):
        self.records.append({"event": event, "details": details})


class _RaisingSink:
    def __call__(self, event, details):
        raise RuntimeError("sink boom")


class _FakeChaseClient:
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
        status = "FILLED" if executed >= quantity else ("PARTIALLY_FILLED" if executed > 0 else "EXPIRED")
        return {"status": status, "executedQty": str(executed)}

    def place_market_sell(self, *, symbol, quantity, client_order_id):
        self.market_calls.append({"quantity": quantity})
        return {"status": "FILLED", "executedQty": str(quantity)}


class _FakeExitClient:
    """عميل execute_market_exit مُحاكى (upper ⇒ LIMIT)."""

    def __init__(self, *, free="100", resting=None):
        self._free = Decimal(str(free))
        self._resting = list(resting or [])
        self.limit_calls = []

    def get_open_sell_orders(self, symbol):
        return list(self._resting)

    def get_free_asset_qty(self, asset):
        return self._free

    def cancel_oco(self, symbol, order_list_id):
        return {"ok": True}

    def place_limit_sell(self, *, symbol, quantity, price, client_order_id):
        self.limit_calls.append({"quantity": quantity, "price": price})
        return {"status": "NEW", "orderId": 1}

    def place_stop_loss_limit(self, *, symbol, quantity, stop_price, limit_price, client_order_id):
        return {"status": "NEW", "orderId": 2}

    def place_market_sell(self, *, symbol, quantity, client_order_id):
        return {"status": "FILLED", "orderId": 3}


class ExitTelemetryTests(unittest.TestCase):
    # ---- opt-in: default None ⇒ لا إرسال ولا تغيير سلوك ----
    def test_default_no_sink_no_regression_chase(self):
        c = _FakeChaseClient(ioc_fills=["ALL"])
        r = execute_exit_chase(client=c, symbol="LSKUSDT", base_asset="LSK",
                               bid_getter=_bid("100"), target_qty=Decimal("10"),
                               filters=_filters(), client_order_id="cx", dry_run=False)
        self.assertEqual(r["action"], "FILLED")
        self.assertEqual(r["filled_qty"], Decimal("10"))

    def test_dry_run_with_sink_no_side_effects_but_emits(self):
        c = _FakeChaseClient()
        sink = _Sink()
        r = execute_exit_chase(client=c, symbol="LSKUSDT", base_asset="LSK",
                               bid_getter=_bid("100"), target_qty=Decimal("10"),
                               filters=_filters(), client_order_id="cx",
                               audit_sink=sink, source="MANUAL_EXIT", dry_run=True)
        self.assertEqual(r["action"], "DRY_RUN")
        self.assertEqual(c.ioc_calls, [])      # لا أثر جانبي على الوسيط
        self.assertEqual(c.market_calls, [])
        self.assertEqual(len(sink.records), 1)
        det = sink.records[0]["details"]
        self.assertEqual(sink.records[0]["event"], "exit_execution")
        self.assertEqual(det["source"], "MANUAL_EXIT")
        self.assertTrue(det["dry_run"])

    def test_chase_real_emits_computed_record(self):
        c = _FakeChaseClient(ioc_fills=["ALL"])
        sink = _Sink()
        r = execute_exit_chase(client=c, symbol="LSKUSDT", base_asset="LSK",
                               bid_getter=_bid("100"), target_qty=Decimal("10"),
                               filters=_filters(), client_order_id="cx",
                               audit_sink=sink, source="BTC_FOLLOW",
                               trade_uid="abc12345", dry_run=False)
        self.assertEqual(r["action"], "FILLED")
        self.assertEqual(len(sink.records), 1)
        det = sink.records[0]["details"]
        self.assertEqual(det["source"], "BTC_FOLLOW")
        self.assertEqual(det["order_type"], "LIMIT_IOC")
        self.assertEqual(det["tif"], "IOC")
        self.assertEqual(det["trade_uid"], "abc12345")
        self.assertFalse(det["dry_run"])
        self.assertFalse(det["reached_floor"])
        self.assertEqual(det["qty"], Decimal("10"))
        self.assertEqual(det["attempts_used"], 1)
        self.assertIsInstance(det["slippage_pct"], Decimal)
        self.assertIsInstance(det["live_bid"], Decimal)

    def test_raising_sink_does_not_break_exit(self):
        c = _FakeChaseClient(ioc_fills=["ALL"])
        r = execute_exit_chase(client=c, symbol="LSKUSDT", base_asset="LSK",
                               bid_getter=_bid("100"), target_qty=Decimal("10"),
                               filters=_filters(), client_order_id="cx",
                               audit_sink=_RaisingSink(), source="MONITORING", dry_run=False)
        self.assertEqual(r["action"], "FILLED")  # الـtelemetry لا تُفشِل الخروج

    def test_market_exit_placed_emits_order_type_from_plan(self):
        c = _FakeExitClient(free="100")
        sink = _Sink()
        r = execute_market_exit(client=c, symbol="LSKUSDT", base_asset="LSK",
                                exit_side="upper", reference_price=Decimal("100"),
                                target_qty=Decimal("10"), filters=_filters(),
                                client_order_id="mx", audit_sink=sink,
                                source="PRICE_BRACKET", trade_uid="dd99",
                                dry_run=False)
        self.assertEqual(r["action"], "PLACED")
        self.assertEqual(len(sink.records), 1)
        det = sink.records[0]["details"]
        self.assertEqual(det["source"], "PRICE_BRACKET")
        self.assertEqual(det["order_type"], "LIMIT")
        self.assertFalse(det["dry_run"])
        self.assertEqual(det["qty"], Decimal("10"))
        self.assertIsInstance(det["requested_price"], Decimal)

    def test_build_record_shape_pure(self):
        rec = build_exit_execution_record(
            source="MANUAL_EXIT", exit_side="upper", order_type="LIMIT_IOC", tif="IOC",
            requested_price=Decimal("99.9"), filled_price=None, live_bid=Decimal("100"),
            slippage_pct=Decimal("0.1"), band_pct=Decimal("0.2"), attempts_used=2,
            reached_floor=1, floor_price=Decimal("92"), qty=Decimal("10"),
            trade_uid="", dry_run=0)
        self.assertEqual(rec["source"], "MANUAL_EXIT")
        self.assertIs(rec["reached_floor"], True)   # bool() طبّع 1 ⇒ True
        self.assertIs(rec["dry_run"], False)         # bool() طبّع 0 ⇒ False
        self.assertEqual(rec["trade_uid"], "")

    def test_pipeline_sink_to_profitability_reader(self):
        # تنفيذان حقيقيان من وضع MONITORING ⇒ سجلّان telemetry.
        c1 = _FakeChaseClient(ioc_fills=["ALL"])
        c2 = _FakeChaseClient(ioc_fills=["ALL"])
        sink = _Sink()
        for c in (c1, c2):
            execute_exit_chase(client=c, symbol="LSKUSDT", base_asset="LSK",
                               bid_getter=_bid("100"), target_qty=Decimal("10"),
                               filters=_filters(), client_order_id="cx",
                               audit_sink=sink, source="MONITORING", dry_run=False)
        execs = extract_exit_executions(sink.records)
        self.assertEqual(len(execs), 2)
        self.assertTrue(all(e["source"] == "MONITORING" for e in execs))

        # صفقة واحدة من نفس الوضع ⇒ المُجمِّع يربط telemetry بالوضع.
        from ocobot.domain.completed_trades import CompletedTrade
        trade = CompletedTrade(
            trade_key="k", symbol="LSKUSDT", reference_price=Decimal("100"),
            opened_at="t0", closed_at="t1", close_reason="", exit_price=Decimal("101"),
            side="SELL", quantity=Decimal("1"), profit_usd=Decimal("10"),
            profit_pct=Decimal("1"), profit_available=True, exit_source="MONITORING")
        res = profitability_by_mode([trade], exit_executions=execs)
        self.assertEqual(res["MONITORING"].n_exec, 2)
        self.assertIsNotNone(res["MONITORING"].floor_rate)


if __name__ == "__main__":
    unittest.main()
