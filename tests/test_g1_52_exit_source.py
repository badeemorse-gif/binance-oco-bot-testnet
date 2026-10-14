# -*- coding: utf-8 -*-
"""اختبار G1.52 (chunk_3): إصدار exit_source لكل وسيلة خروج.

يغطّي:
  - ``make_exit_source_recorder``: يسجّل exit_source للمصادر المسموح بها فقط،
    يتجاهل غير المعروف، وبلا أثر/خطأ عند ``audit=None``.
  - الخروج اليدوي (``run_manual_market_exit``): يُصدر ``MANUAL_EXIT`` لحظة الإطلاق
    الفعلي (``dry_run=False``) ولا يُصدر في المعاينة (``dry_run=True``) — opt-in.
  - شبكة أمان المركز (``GuardianSupervisor._intervene``): يُصدر
    ``POSITION_SAFETY_NET`` عبر ``exit_source_sink`` المحقون (opt-in).

(ملاحظة: الوسائل PRICE_BRACKET/BTC_FOLLOW/POSITION_SAFETY_NET تُسجَّل أصلًا في سجل
التدقيق عبر ``MonitoringEngine.note_exit_source`` منذ G1.46؛ هذا الاختبار يتحقّق من
آليّة الحقن المباشر الموحّدة التي يحتاجها MANUAL_EXIT بوجه خاص.)

مكتبة قياسية فقط. لا شبكة.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest
from decimal import Decimal
from types import SimpleNamespace

from ocobot.domain.completed_trades import make_exit_source_recorder


class FakeAuditLog:
    def __init__(self):
        self.records = []

    def record(self, event, details=None):
        self.records.append((event, details))
        return {"event": event, "details": details}


class MakeExitSourceRecorderTests(unittest.TestCase):
    def test_records_allowed_source(self):
        audit = FakeAuditLog()
        note = make_exit_source_recorder(audit)
        note("MANUAL_EXIT")
        self.assertEqual(audit.records, [("exit_source", {"source": "MANUAL_EXIT"})])

    def test_ignores_unknown_source(self):
        audit = FakeAuditLog()
        note = make_exit_source_recorder(audit)
        note("NOT_A_REAL_SOURCE")
        self.assertEqual(audit.records, [])

    def test_none_audit_is_safe(self):
        note = make_exit_source_recorder(None)
        note("MANUAL_EXIT")  # يجب ألّا يرمي


class ManualExitSourceTests(unittest.TestCase):
    def _run(self, *, dry_run, noter):
        from ocobot.ui.manual_exit import run_manual_market_exit
        try:
            run_manual_market_exit(
                client=object(),
                symbol="BTCUSDT",
                base_asset="BTC",
                free_base_qty=Decimal("1"),
                monitored_qty=Decimal("1"),
                has_resting_protective_sell=False,  # ⇒ البوّابة تسمح
                reference_price=Decimal("100"),
                filters=object(),
                dry_run=dry_run,
                bid_getter=None,
                exit_source_noter=noter,
            )
        except Exception:
            # قد يرمي مسار الخروج المُختبَر مع عميل زائف؛ لا يهمّنا هنا —
            # الوسم يحدث قبل استدعاء المنفّذ.
            pass

    def test_emits_manual_exit_on_live_launch(self):
        captured = []
        self._run(dry_run=False, noter=captured.append)
        self.assertEqual(captured, ["MANUAL_EXIT"])

    def test_no_emit_in_dry_run_preview(self):
        captured = []
        self._run(dry_run=True, noter=captured.append)
        self.assertEqual(captured, [])


class GuardianExitSourceTests(unittest.TestCase):
    def test_position_safety_net_emitted_via_sink(self):
        from ocobot.domain.guardian_supervisor import GuardianSupervisor
        from ocobot.domain.guardian import GuardianConfig

        class FakeEngine:
            def note_exit_source(self, source):
                pass

            def kill_switch(self):
                pass

        captured = []
        sup = GuardianSupervisor(
            state_provider=lambda: None,
            client=object(),
            alert_cb=lambda msg: None,
            config=GuardianConfig(),
            dry_run=True,
            reference_price_fn=lambda state: Decimal("100"),
            filters_fn=lambda symbol: {},
            exit_source_sink=captured.append,
        )
        decision = SimpleNamespace(
            protective_qty=Decimal("1"), reason="naked", naked_seconds=5
        )
        sup._intervene("BTCUSDT", "BTC", None, FakeEngine(), decision)
        self.assertEqual(captured, ["POSITION_SAFETY_NET"])


if __name__ == "__main__":
    unittest.main()
