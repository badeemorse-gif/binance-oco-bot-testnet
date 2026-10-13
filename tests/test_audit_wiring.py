"""اختبارات توصيل Audit Log (T6 / M4b) — WIRING فقط.

تتحقّق أن SafeExecutor وMonitoringEngine (والمسارات) تُنادي AuditLog.record
عبر sink اختياري متوافق-خلفيًا، وأن الإخفاء (D8) يبقى فعّالًا، وأن الملف
append-only. تُعيد استخدام fakes الموجودة (tests/_fakes.py و
tests/_fakes_monitoring.py) بنفس نمط بناء الاختبارات القائمة.
"""
import json
import os
import tempfile
import unittest
from decimal import Decimal

from ocobot.core.audit_log import AuditLog
from ocobot.core.errors import BinanceApiError
from ocobot.domain.exchange_info import ExchangeInfoService
from ocobot.domain.monitoring import GuardPolicy, MonitoringEngine
from ocobot.domain.oco_reader import OcoReader
from ocobot.domain.reposition import ExecutionState, SafeExecutor
from tests._fakes import FakeClient
from tests._fakes_monitoring import (
    FakeSafeExecutor,
    FakeSelectedOCO,
    make_result,
)


def _executor(client, audit=None, ids=None):
    exi = ExchangeInfoService(client, monotonic=lambda: 1.0)
    reader = OcoReader(client)
    if ids is not None:
        seq = iter(ids)
        id_factory = lambda prefix: next(seq)  # noqa: E731
    else:
        id_factory = None
    return SafeExecutor(client, reader, exi, id_factory=id_factory, audit=audit)


def _tmp_path():
    d = tempfile.mkdtemp()
    return os.path.join(d, "sub", "audit.jsonl")


def _read_lines(path):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as handle:
        return [ln for ln in handle.read().splitlines() if ln.strip()]


def _events(path):
    return [json.loads(ln)["event"] for ln in _read_lines(path)]


class TestSafeExecutorWiring(unittest.TestCase):
    def test_success_path_writes_before_cancel_then_after_create(self):
        path = _tmp_path()
        audit = AuditLog(path)
        client = FakeClient(new_order_list_id=99)
        result = _executor(client, audit=audit).execute(
            31, "4", "2", "60000", dry_run=False
        )
        self.assertEqual(result.state, ExecutionState.SUCCESS)

        lines = _read_lines(path)
        self.assertTrue(lines)
        # كل سطر JSON صالح بمفاتيح ts/event/details
        for line in lines:
            obj = json.loads(line)
            self.assertIn("ts", obj)
            self.assertIn("event", obj)
            self.assertIn("details", obj)

        events = [json.loads(ln)["event"] for ln in lines]
        self.assertIn("before_cancel", events)
        self.assertIn("after_create", events)
        self.assertIn("reposition_success", events)
        # before_cancel يسبق after_create
        self.assertLess(events.index("before_cancel"), events.index("after_create"))

    def test_gate_fail_writes_abort_and_no_after_create(self):
        path = _tmp_path()
        audit = AuditLog(path)
        # remaining ضئيل جدًا ⇒ partial_fill_abort عبر البوابة (لا كتابة)
        client = FakeClient(orig_qty="0.5", executed_qty="0.4999")
        result = _executor(client, audit=audit).execute(
            31, "4", "2", "0.05", dry_run=False
        )
        self.assertEqual(result.state, ExecutionState.ABORTED)

        events = _events(path)
        self.assertIn("abort", events)
        self.assertNotIn("after_create", events)

    def test_create_failure_writes_before_cancel_then_failed_needs_attention(self):
        path = _tmp_path()
        audit = AuditLog(path)
        client = FakeClient(create_error=BinanceApiError(-2010, "rejected", 400))
        result = _executor(client, audit=audit).execute(
            31, "4", "2", "60000", dry_run=False
        )
        self.assertEqual(result.state, ExecutionState.FAILED_NEEDS_ATTENTION)

        events = _events(path)
        self.assertIn("before_cancel", events)
        self.assertIn("failed_needs_attention", events)
        self.assertLess(
            events.index("before_cancel"), events.index("failed_needs_attention")
        )

    def test_backward_compatible_without_audit(self):
        # بلا sink: لا كسر ولا كتابة أي ملف
        client = FakeClient(new_order_list_id=99)
        result = _executor(client, audit=None).execute(
            31, "4", "2", "60000", dry_run=False
        )
        self.assertEqual(result.state, ExecutionState.SUCCESS)


class TestMonitoringEngineWiring(unittest.TestCase):
    def test_lifecycle_events_recorded(self):
        path = _tmp_path()
        audit = AuditLog(path)
        ex = FakeSafeExecutor(
            result=make_result(ExecutionState.SUCCESS, new_order_list_id=99,
                               cancelled_order_list_id=31)
        )
        eng = MonitoringEngine(ex, guard_policy=GuardPolicy.HALT_NOTIFY, audit=audit)
        eng.start(FakeSelectedOCO(), trigger_pct="1", tp_pct="4", sl_pct="2",
                  reference_price="100")
        eng.pause()
        eng.resume()
        eng.kill_switch()

        events = _events(path)
        for expected in ("monitor_start", "pause", "resume", "kill_switch"):
            self.assertIn(expected, events)


class TestRedactionHolds(unittest.TestCase):
    def test_no_secret_leaks_into_audit_file(self):
        path = _tmp_path()
        audit = AuditLog(path)
        secret = "RAWAPIKEY0123456789"
        sig = "deadBEEF0123456789abcdef"
        # مسار قد تظهر فيه أسرار في التفاصيل — الإخفاء داخل record يجب أن يزيلها
        audit.record("signed_request", {
            "headers": {"X-MBX-APIKEY": secret},
            "url": "https://x/api/v3/account?timestamp=1&signature=" + sig,
        })
        with open(path, "r", encoding="utf-8") as fh:
            raw = fh.read()
        self.assertNotIn(secret, raw)
        self.assertNotIn(sig, raw)
        self.assertIn("***", raw)


class TestAppendOnlyAcrossRuns(unittest.TestCase):
    def test_two_runs_share_path_and_append(self):
        path = _tmp_path()
        # الجولة الأولى: منفّذ ناجح
        audit1 = AuditLog(path)
        c1 = FakeClient(new_order_list_id=99)
        _executor(c1, audit=audit1).execute(31, "4", "2", "60000", dry_run=False)
        first_lines = _read_lines(path)
        self.assertTrue(first_lines)

        # الجولة الثانية: منفّذ آخر على نفس المسار — يُلحق لا يقتطع
        audit2 = AuditLog(path)
        c2 = FakeClient(new_order_list_id=150)
        _executor(c2, audit=audit2).execute(31, "4", "2", "60000", dry_run=False)
        all_lines = _read_lines(path)

        self.assertGreater(len(all_lines), len(first_lines))
        # الأسطر الأولى محفوظة كما هي (append-only)
        self.assertEqual(all_lines[: len(first_lines)], first_lines)


if __name__ == "__main__":
    unittest.main()
