# -*- coding: utf-8 -*-
"""G1.53 chunk_3 — اختبارات التقاط العمولة (اختياري، best-effort) + net_pnl الخالصة.

يُثبت (بلا شبكة):
  - sum_commission يقرأ شكلَي Binance (executionReport n/N و fills[]) ويُعيد
    (Decimal, asset)؛ وعند الغياب/التلف ⇒ (0, None) بلا رفع.
  - execute_exit_chase يلتقط العمولة في سجلّ telemetry عند توفّرها في ردّ الوسيط،
    مع asset صحيح — Decimal.
  - عند غياب العمولة يبقى سجلّ telemetry مطابقًا لسكيمة chunk_2 (لا مفتاح commission).
  - extract_exit_executions يُحوّل commission إلى Decimal.
  - net_pnl = gross − commission (Decimal)؛ None إن غاب gross؛ العمولة الغائبة = 0.

قابل للتشغيل عبر: python -m unittest tests.test_g1_53_commission
"""
import unittest
from decimal import Decimal

from ocobot.domain.market_exit import execute_exit_chase, sum_commission
from ocobot.domain.models import SymbolFilters
from ocobot.domain.profitability import extract_exit_executions, net_pnl


def _filters():
    return SymbolFilters(symbol="LSKUSDT", tick_size=Decimal("0.0001"),
                         step_size=Decimal("0.01"), min_qty=Decimal("0.1"),
                         min_notional=Decimal("5"))


class _Sink:
    def __init__(self):
        self.records = []

    def __call__(self, event, details):
        self.records.append({"event": event, "details": details})


class _CommChaseClient:
    """عميل chase يملأ أول IOC بالكامل ويُرجِع عمولة (n/N) اختياريًّا."""

    def __init__(self, *, commission=None, asset=None):
        self._commission = commission
        self._asset = asset

    def get_open_sell_orders(self, symbol):
        return []

    def get_free_asset_qty(self, asset):
        return Decimal("100")

    def cancel_oco(self, symbol, order_list_id):
        return {"ok": True}

    def place_limit_sell_ioc(self, *, symbol, quantity, price, client_order_id):
        resp = {"status": "FILLED", "executedQty": str(quantity)}
        if self._commission is not None:
            resp["n"] = self._commission
            resp["N"] = self._asset
        return resp

    def place_market_sell(self, *, symbol, quantity, client_order_id):
        return {"status": "FILLED", "executedQty": str(quantity)}


class SumCommissionTests(unittest.TestCase):
    def test_execution_report_n_N(self):
        total, asset = sum_commission({"n": "0.5", "N": "USDT"})
        self.assertEqual(total, Decimal("0.5"))
        self.assertEqual(asset, "USDT")

    def test_fills_list(self):
        resp = {"fills": [
            {"commission": "0.1", "commissionAsset": "USDT"},
            {"commission": "0.2", "commissionAsset": "USDT"},
        ]}
        total, asset = sum_commission(resp)
        self.assertEqual(total, Decimal("0.3"))
        self.assertEqual(asset, "USDT")

    def test_absent_or_corrupt(self):
        self.assertEqual(sum_commission({}), (Decimal("0"), None))
        self.assertEqual(sum_commission(None), (Decimal("0"), None))
        self.assertEqual(sum_commission({"n": "oops"}), (Decimal("0"), None))


class ChaseCommissionTelemetryTests(unittest.TestCase):
    def test_commission_captured_in_record(self):
        sink = _Sink()
        c = _CommChaseClient(commission="0.5", asset="USDT")
        execute_exit_chase(client=c, symbol="LSKUSDT", base_asset="LSK",
                           bid_getter=lambda: Decimal("100"), target_qty=Decimal("10"),
                           filters=_filters(), client_order_id="cx",
                           audit_sink=sink, source="MANUAL_EXIT", dry_run=False)
        det = sink.records[0]["details"]
        self.assertIn("commission", det)
        self.assertEqual(det["commission"], Decimal("0.5"))
        self.assertEqual(det["commission_asset"], "USDT")

    def test_no_commission_keeps_chunk2_schema(self):
        sink = _Sink()
        c = _CommChaseClient(commission=None)
        execute_exit_chase(client=c, symbol="LSKUSDT", base_asset="LSK",
                           bid_getter=lambda: Decimal("100"), target_qty=Decimal("10"),
                           filters=_filters(), client_order_id="cx",
                           audit_sink=sink, source="MANUAL_EXIT", dry_run=False)
        det = sink.records[0]["details"]
        self.assertNotIn("commission", det)
        self.assertNotIn("commission_asset", det)

    def test_reader_converts_commission_to_decimal(self):
        rec = {"event": "exit_execution", "details": {
            "source": "MANUAL_EXIT", "commission": "0.5", "slippage_pct": "0.1",
            "reached_floor": False, "dry_run": False}}
        out = extract_exit_executions([rec])
        self.assertEqual(len(out), 1)
        self.assertIsInstance(out[0]["commission"], Decimal)
        self.assertEqual(out[0]["commission"], Decimal("0.5"))


class NetPnlTests(unittest.TestCase):
    def test_net_pnl_basic(self):
        self.assertEqual(net_pnl(Decimal("100"), Decimal("0.5")), Decimal("99.5"))

    def test_net_pnl_missing_commission_is_zero(self):
        self.assertEqual(net_pnl("50", None), Decimal("50"))

    def test_net_pnl_missing_gross_is_none(self):
        self.assertIsNone(net_pnl(None, "1"))


if __name__ == "__main__":
    unittest.main()
