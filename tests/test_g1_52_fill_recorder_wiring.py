# -*- coding: utf-8 -*-
"""اختبار G1.52 (chunk_4): مُساعِد ربط مُسجّل التعبئة بـ on_order_event.

يثبت أنّ ``make_fill_recorder_order_event(audit, prior)`` يُنتج ``on_order_event``
جاهزًا للحقن في ``UserDataStreamConsumer``: يلتقط تعبئة البيع ويكتب
``trade_closed_fill`` عبر ``audit``، **ويحافظ على أيّ معالِج سابق** (يُنادى لكل
حدث)، و ``prior=None`` سليم.

مكتبة قياسية فقط (unittest). لا Qt ولا شبكة.
"""
from __future__ import annotations

import unittest


class FakeAuditLog:
    def __init__(self):
        self.records = []

    def record(self, event, details=None):
        self.records.append((event, details))
        return {"event": event, "details": details}


def _sell_fill():
    return {
        "e": "executionReport", "X": "FILLED", "S": "SELL", "g": -1,
        "s": "BTCUSDT", "L": "104.0", "z": "0.5", "i": 1, "c": "c1",
    }


class FillRecorderWiringTests(unittest.TestCase):
    def _make(self):
        from ocobot.app_wiring import make_fill_recorder_order_event
        return make_fill_recorder_order_event

    def test_records_sell_fill_and_preserves_prior(self):
        make = self._make()
        audit = FakeAuditLog()
        seen = []
        handler = make(audit, prior_on_order_event=seen.append)

        ev = _sell_fill()
        handler(ev)

        self.assertEqual(len(audit.records), 1)
        self.assertEqual(audit.records[0][0], "trade_closed_fill")
        self.assertEqual(seen, [ev])  # المعالِج السابق محفوظ ويُنادى

    def test_prior_called_for_non_fill_without_record(self):
        make = self._make()
        audit = FakeAuditLog()
        seen = []
        handler = make(audit, prior_on_order_event=seen.append)

        other = {"e": "outboundAccountPosition"}
        handler(other)

        self.assertEqual(audit.records, [])
        self.assertEqual(seen, [other])

    def test_prior_none_is_safe(self):
        make = self._make()
        audit = FakeAuditLog()
        handler = make(audit, prior_on_order_event=None)

        handler(_sell_fill())  # يجب ألّا يرمي

        self.assertEqual(len(audit.records), 1)


if __name__ == "__main__":
    unittest.main()
