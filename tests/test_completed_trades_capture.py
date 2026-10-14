"""اختبارات التقاط إغلاق الصفقة (G1.14 step_4) — ``build_fill_recorder``.

تتحقّق هذه الاختبارات من مصنع المُسجّل ``build_fill_recorder`` في
``ocobot.domain.completed_trades``: أنّه يكتب حدث ``trade_closed_fill`` واحدًا
فقط عند تقرير تنفيذ FILLED، ويتجاهل غير ذلك، ويُنادي ``next_callback`` دائمًا،
ويبتلع أي استثناء من ``audit_log.record`` دون أن يرفعه.

مكتبة قياسية فقط (unittest, json, tempfile, os).
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest

from ocobot.core.audit_log import AuditLog
from ocobot.domain.completed_trades import build_fill_recorder


class FakeAuditLog:
    """سجلّ تدقيق زائف يلتقط (event, details) في قائمة بالذاكرة."""

    def __init__(self):
        self.records = []

    def record(self, event, details=None):
        self.records.append((event, details))
        return {"event": event, "details": details}


class RaisingAuditLog:
    """سجلّ تدقيق يرفع استثناءً عند ``record`` لاختبار نمط السلامة."""

    def record(self, event, details=None):
        raise RuntimeError("boom")


def _filled_event():
    return {
        "e": "executionReport",
        "X": "FILLED",
        "g": 123,
        "s": "BTCUSDT",
        "L": "27000.50",
        "S": "SELL",
        "z": "0.005",
        "i": 777,
        "c": "cli-777",
    }


class BuildFillRecorderTests(unittest.TestCase):
    def test_filled_execution_report_records_one_mapped_event(self):
        audit = FakeAuditLog()
        recorder = build_fill_recorder(audit)

        recorder(_filled_event())

        self.assertEqual(len(audit.records), 1)
        event_name, details = audit.records[0]
        self.assertEqual(event_name, "trade_closed_fill")
        self.assertEqual(
            details,
            {
                "order_list_id": 123,
                "symbol": "BTCUSDT",
                "fill_price": "27000.50",
                "side": "SELL",
                "quantity": "0.005",
                "status": "FILLED",
                "order_id": 777,
                "client_order_id": "cli-777",
            },
        )

    def test_non_terminal_status_records_nothing(self):
        audit = FakeAuditLog()
        recorder = build_fill_recorder(audit)

        event = _filled_event()
        event["X"] = "NEW"
        recorder(event)

        self.assertEqual(audit.records, [])

    def test_non_execution_report_records_nothing(self):
        audit = FakeAuditLog()
        recorder = build_fill_recorder(audit)

        event = _filled_event()
        event["e"] = "outboundAccountPosition"
        recorder(event)

        self.assertEqual(audit.records, [])

    def test_next_callback_always_called_for_filled(self):
        audit = FakeAuditLog()
        seen = []
        recorder = build_fill_recorder(audit, next_callback=seen.append)

        event = _filled_event()
        result = recorder(event)

        self.assertIsNone(result)
        self.assertEqual(seen, [event])

    def test_next_callback_always_called_for_non_filled(self):
        audit = FakeAuditLog()
        seen = []
        recorder = build_fill_recorder(audit, next_callback=seen.append)

        event = _filled_event()
        event["X"] = "NEW"
        result = recorder(event)

        self.assertIsNone(result)
        self.assertEqual(seen, [event])
        self.assertEqual(audit.records, [])

    def test_record_raising_is_swallowed_and_next_callback_still_called(self):
        audit = RaisingAuditLog()
        seen = []
        recorder = build_fill_recorder(audit, next_callback=seen.append)

        event = _filled_event()
        # يجب ألّا يُرفع أي استثناء.
        try:
            result = recorder(event)
        except Exception as exc:  # pragma: no cover - فشل الاختبار صراحةً
            self.fail("recorder propagated an exception: %r" % (exc,))

        self.assertIsNone(result)
        self.assertEqual(seen, [event])

    def test_real_audit_log_over_tempfile_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "audit.jsonl")
            audit = AuditLog(path)
            recorder = build_fill_recorder(audit)

            recorder(_filled_event())

            with open(path, "r", encoding="utf-8") as handle:
                lines = [ln for ln in handle.read().splitlines() if ln.strip()]

            self.assertEqual(len(lines), 1)
            entry = json.loads(lines[0])
            self.assertEqual(entry["event"], "trade_closed_fill")
            self.assertEqual(entry["details"]["order_list_id"], 123)
            self.assertEqual(entry["details"]["symbol"], "BTCUSDT")
            self.assertEqual(entry["details"]["fill_price"], "27000.50")
            self.assertEqual(entry["details"]["side"], "SELL")
            self.assertEqual(entry["details"]["quantity"], "0.005")
            self.assertEqual(entry["details"]["status"], "FILLED")


if __name__ == "__main__":
    unittest.main() 
