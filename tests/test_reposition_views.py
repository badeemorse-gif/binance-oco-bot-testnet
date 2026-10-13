"""اختبارات عرض المسودّة والتنفيذ (M2 / T3 — واجهة نصّية)."""
import unittest
from decimal import Decimal

from ocobot import views
from ocobot.domain.models import SymbolFilters
from ocobot.domain.reposition import (
    ExecutionResult,
    ExecutionState,
    ExecutionStep,
    GateResult,
    RepositionDraft,
)


def _filters():
    return SymbolFilters(
        symbol="BTCUSDT", tick_size=Decimal("0.01"), step_size=Decimal("0.0001"),
        min_qty=Decimal("0.001"), min_notional=Decimal("10"),
    )


def _draft():
    return RepositionDraft(
        symbol="BTCUSDT", quantity=Decimal("0.5"),
        tp_price=Decimal("62400"), stop_trigger=Decimal("58800"),
        stop_limit=Decimal("58799.99"), reference_price=Decimal("60000"),
        tp_pct=Decimal("4"), sl_pct=Decimal("2"), filters=_filters(),
        old_tp=Decimal("70000"), old_stop_trigger=Decimal("58500"),
        old_stop_limit=Decimal("58000"),
    )


def _steps(naked_done=True):
    return [
        ExecutionStep("verify", "① verify", "done"),
        ExecutionStep("price", "② price", "done"),
        ExecutionStep("recalc", "③ recalc", "done"),
        ExecutionStep("gate", "④ gate", "done"),
        ExecutionStep("cancel", "⑤ cancel", "done" if naked_done else "skipped", naked_window=True),
        ExecutionStep("create", "⑥ create", "done" if naked_done else "skipped", naked_window=True),
        ExecutionStep("confirm", "⑦ confirm", "done" if naked_done else "skipped"),
    ]


class TestRenderDraft(unittest.TestCase):
    def test_draft_shows_lock_readonly_arrow_and_strict_order(self):
        out = views.render_draft(_draft(), GateResult(ok=True))
        self.assertIn("\U0001f512", out)          # قفل الكمية
        self.assertIn("Read-only", out)
        self.assertIn("\u2192", out)               # old→new arrow
        self.assertIn("70000", out)                # القيمة القديمة لِ TP
        self.assertIn("62400", out)                # القيمة الجديدة لِ TP
        # سطر الترتيب الصارم موجود
        self.assertIn("Stop Limit", out)
        self.assertIn("Trigger", out)
        self.assertIn("Last", out)
        self.assertIn("TP", out)
        # ملاحظة P2
        self.assertIn("Activate", out)

    def test_draft_gate_failures_listed(self):
        gate = GateResult(ok=False, failures=["انتهاك الترتيب الصارم (D4): مثال"])
        out = views.render_draft(_draft(), gate)
        self.assertIn("انتهاك الترتيب", out)


class TestRenderExecution(unittest.TestCase):
    def test_execution_success_shows_naked_window_and_new_id(self):
        result = ExecutionResult(
            state=ExecutionState.SUCCESS, steps=_steps(),
            cancelled_order_list_id=31, new_order_list_id=99,
            messages=["نجحت إعادة التموضع"],
        )
        out = views.render_execution(result)
        self.assertIn("Naked Window", out)
        self.assertIn("SUCCESS", out)
        self.assertIn("99", out)                   # OCO الجديد
        self.assertIn("31", out)                   # المُلغى

    def test_execution_failed_needs_attention_manual_message(self):
        result = ExecutionResult(
            state=ExecutionState.FAILED_NEEDS_ATTENTION, steps=_steps(),
            cancelled_order_list_id=31,
            reason="تم إلغاء الأمر المحدد، لكن إنشاء البديل فشل — لا توجد إعادة محاولة تلقائية. تدخّل يدوي مطلوب.",
        )
        out = views.render_execution(result)
        self.assertIn("FAILED_NEEDS_ATTENTION", out)
        self.assertIn("تدخّل يدوي", out)

    def test_execution_aborted_shows_reason_and_original_intact(self):
        result = ExecutionResult(
            state=ExecutionState.ABORTED, steps=_steps(naked_done=False),
            reason="فشلت بوابة ما قبل الإلغاء",
        )
        out = views.render_execution(result)
        self.assertIn("ABORTED", out)
        self.assertIn("الأمر الأصلي سليم", out)


if __name__ == "__main__":
    unittest.main()
