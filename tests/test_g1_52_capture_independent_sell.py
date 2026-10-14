# -*- coding: utf-8 -*-
"""اختبار تشخيصي G1.52 (chunk_1): التقاط ونسب تعبئة بيع مستقلّة (g=-1).

يثبت أنّ أمر بيع منفَّذ خارج OCO (``g == -1``) يُلتقَط كـ ``trade_closed_fill`` عبر
``build_fill_recorder`` (مع ``order_id``/``client_order_id``)، ثم يُنسب للصفقة
النشطة ضمن مقطع ``monitor_start``..``monitor_closed`` فيعطي ``exit_price`` وربحًا
متاحًا — وليس أوامر OCO فقط. كما يثبت أنّ تعبئة الدخول BUY لا تُسجَّل كإغلاق.

مكتبة قياسية فقط (unittest). لا Qt ولا شبكة.
"""
from __future__ import annotations

import unittest
from decimal import Decimal

from ocobot.domain.completed_trades import build_fill_recorder, build_completed_trades


class FakeAuditLog:
    """سجلّ تدقيق زائف يلتقط (event, details) في قائمة بالذاكرة."""

    def __init__(self):
        self.records = []

    def record(self, event, details=None):
        self.records.append((event, details))
        return {"event": event, "details": details}


def _sell_fill(g=-1):
    """executionReport لتعبئة بيع (SELL FILLED). ``g=-1`` = أمر مستقل خارج OCO."""
    return {
        "e": "executionReport",
        "X": "FILLED",
        "S": "SELL",
        "g": g,
        "s": "BTCUSDT",
        "L": "104.0",
        "z": "0.5",
        "i": 987654,
        "c": "ind-sell-1",
    }


class CaptureIndependentSellTests(unittest.TestCase):
    def test_independent_sell_is_recorded_with_ids(self):
        audit = FakeAuditLog()
        recorder = build_fill_recorder(audit)

        recorder(_sell_fill(g=-1))

        self.assertEqual(len(audit.records), 1)
        event, details = audit.records[0]
        self.assertEqual(event, "trade_closed_fill")
        self.assertEqual(details["order_list_id"], -1)  # مستقل (ليس OCO)
        self.assertEqual(details["order_id"], 987654)
        self.assertEqual(details["client_order_id"], "ind-sell-1")
        self.assertEqual(details["side"], "SELL")
        self.assertEqual(details["fill_price"], "104.0")

    def test_entry_buy_fill_is_not_recorded_as_close(self):
        audit = FakeAuditLog()
        seen = []
        recorder = build_fill_recorder(audit, next_callback=seen.append)

        buy = _sell_fill(g=-1)
        buy["S"] = "BUY"  # تعبئة دخول — ليست إغلاقًا.
        recorder(buy)

        self.assertEqual(audit.records, [])  # لا trade_closed_fill للدخول BUY
        self.assertEqual(seen, [buy])  # next_callback يُنادى دائمًا

    def test_independent_sell_attributed_to_active_trade_with_exit_price(self):
        # مقطع صفقة كامل: بدء مراقبة ⇒ تعبئة بيع مستقلّة (g=-1) ⇒ إغلاق المراقبة.
        records = [
            {
                "event": "monitor_start",
                "ts": "2026-10-14T10:00:00Z",
                "details": {
                    "symbol": "BTCUSDT",
                    "order_list_id": 123,
                    "reference_price": "100.0",
                    "trade_uid": "abc12345",
                    "session_no": 1,
                },
            },
            {
                "event": "trade_closed_fill",
                "ts": "2026-10-14T10:03:00Z",
                "details": {
                    "order_list_id": -1,  # أمر بيع مستقل خارج OCO
                    "symbol": "BTCUSDT",
                    "fill_price": "104.0",
                    "side": "SELL",
                    "quantity": "0.5",
                    "status": "FILLED",
                    "order_id": 987654,
                    "client_order_id": "ind-sell-1",
                },
            },
            {
                "event": "monitor_closed",
                "ts": "2026-10-14T10:03:01Z",
                "details": {"end_reason": "stopped_manual"},
            },
        ]

        trades = build_completed_trades(records)

        self.assertEqual(len(trades), 1)
        trade = trades[0]
        self.assertEqual(trade.exit_price, Decimal("104.0"))  # نُسب رغم g=-1
        self.assertEqual(trade.side, "SELL")
        self.assertTrue(trade.profit_available)
        self.assertEqual(trade.profit_pct, Decimal("4"))  # (104-100)/100*100


if __name__ == "__main__":
    unittest.main()
