"""اختبارات طبقة القراءة للصفقات المنتهية (G1.14 — step_2).

تُغطّي عبر fixtures JSONL اصطناعية (TemporaryDirectory):
  - صفقة كاملة بسلسلة تموضع 371236 -> 371452 -> 371600 مع trade_closed_fill:
    3 خطوات بالمعرّفات/الأسعار/التواقيع/المستويات الصحيحة، التقاط reference_price،
    وحساب profit_pct/profit_usd بدقّة، و profit_available == True.
  - صفقة منتهية بلا trade_closed_fill: exit_price=None، profit غير متاح (None).
  - monitor_start بلا monitor_closed (مفتوحة): تُستبعَد من المنتهية.
  - DismissStore: dismiss يُثبّت ويُرشّح عبر load_completed_trades، وبايتات ملف
    سجل التدقيق تبقى بلا تغيير بعد dismiss (إثبات أنّ الحذف لا يمسّ السجل).

قابلة للتشغيل عبر: python -m unittest tests.test_completed_trades_domain
"""
import json
import os
import tempfile
import unittest
from decimal import Decimal

from ocobot.domain.completed_trades import (
    CompletedTrade,
    DismissStore,
    PositioningStep,
    build_completed_trades,
    compute_profit,
    default_dismiss_path,
    load_completed_trades,
    parse_audit_jsonl,
)


def _line(event, details, ts):
    """يبني سطر JSONL واحدًا بنفس شكل AuditLog (Decimal كنصوص عبر default=str)."""
    return json.dumps(
        {"ts": ts, "event": event, "details": details},
        ensure_ascii=False,
        default=str,
    )


def _write_audit(lines):
    """يكتب أسطر JSONL إلى ملف داخل مجلّد مؤقّت ويعيد (dir, path)."""
    d = tempfile.mkdtemp()
    path = os.path.join(d, "ocobot_audit.jsonl")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return d, path


# سلسلة أحداث لصفقة كاملة 371236 -> 371452 -> 371600 مع fill نهائي.
def _full_trade_lines():
    return [
        _line("monitor_start", {
            "order_list_id": 371236, "symbol": "BTCUSDT",
            "trigger_pct": "3", "tp_pct": "4", "sl_pct": "2",
            "reference_price": Decimal("100.00"), "tolerance_pct": "0.1",
            "guard_pct": "1.0", "dry_run": False,
        }, "2026-01-01T00:00:00+00:00"),
        _line("draft_built", {
            "order_list_id": 371236, "symbol": "BTCUSDT",
            "tp_pct": "4", "sl_pct": "2",
            "tp_price": Decimal("104.00"), "stop_trigger": Decimal("98.00"),
            "stop_limit": Decimal("97.90"), "reference_price": Decimal("100.00"),
            "quantity": Decimal("2"), "dry_run": False,
        }, "2026-01-01T00:00:01+00:00"),
        # أول إعادة تموضع -> 371452
        _line("reposition_success", {
            "cancelled_order_list_id": 371236, "new_order_list_id": 371452,
            "symbol": "BTCUSDT", "tp_price": Decimal("109.00"),
            "stop_trigger": Decimal("103.00"), "stop_limit": Decimal("102.90"),
        }, "2026-01-01T00:00:10+00:00"),
        _line("repositioned", {
            "old_target": 371236, "new_target": 371452,
            "cursor": 1, "price": Decimal("105.00"),
        }, "2026-01-01T00:00:10+00:00"),
        _line("draft_built", {
            "order_list_id": 371452, "symbol": "BTCUSDT",
            "tp_pct": "4", "sl_pct": "2",
            "tp_price": Decimal("109.00"), "stop_trigger": Decimal("103.00"),
            "stop_limit": Decimal("102.90"), "reference_price": Decimal("105.00"),
            "quantity": Decimal("2"), "dry_run": False,
        }, "2026-01-01T00:00:11+00:00"),
        # ثاني إعادة تموضع -> 371600
        _line("reposition_success", {
            "cancelled_order_list_id": 371452, "new_order_list_id": 371600,
            "symbol": "BTCUSDT", "tp_price": Decimal("114.00"),
            "stop_trigger": Decimal("108.00"), "stop_limit": Decimal("107.90"),
        }, "2026-01-01T00:00:20+00:00"),
        _line("repositioned", {
            "old_target": 371452, "new_target": 371600,
            "cursor": 2, "price": Decimal("110.00"),
        }, "2026-01-01T00:00:20+00:00"),
        # fill نهائي ثم إغلاق
        _line("trade_closed_fill", {
            "order_list_id": 371600, "fill_price": Decimal("112.50"),
            "side": "SELL", "quantity": Decimal("2"),
        }, "2026-01-01T00:00:30+00:00"),
        _line("monitor_closed", {
            "reason": "take_profit_filled", "source": "ws",
        }, "2026-01-01T00:00:31+00:00"),
    ]


# صفقة منتهية بلا trade_closed_fill (معرّف ابتدائي مختلف).
def _no_fill_trade_lines():
    return [
        _line("monitor_start", {
            "order_list_id": 500001, "symbol": "ETHUSDT",
            "trigger_pct": "3", "tp_pct": "4", "sl_pct": "2",
            "reference_price": Decimal("50.00"), "tolerance_pct": "0.1",
            "guard_pct": "1.0", "dry_run": False,
        }, "2026-02-01T00:00:00+00:00"),
        _line("draft_built", {
            "order_list_id": 500001, "symbol": "ETHUSDT",
            "tp_pct": "4", "sl_pct": "2",
            "tp_price": Decimal("52.00"), "stop_trigger": Decimal("49.00"),
            "stop_limit": Decimal("48.90"), "reference_price": Decimal("50.00"),
            "quantity": Decimal("3"), "dry_run": False,
        }, "2026-02-01T00:00:01+00:00"),
        _line("monitor_closed", {"reason": "stopped"}, "2026-02-01T00:00:05+00:00"),
    ]


# صفقة مفتوحة (monitor_start بلا monitor_closed).
def _open_trade_lines():
    return [
        _line("monitor_start", {
            "order_list_id": 900001, "symbol": "SOLUSDT",
            "trigger_pct": "3", "tp_pct": "4", "sl_pct": "2",
            "reference_price": Decimal("10.00"), "tolerance_pct": "0.1",
            "guard_pct": "1.0", "dry_run": False,
        }, "2026-03-01T00:00:00+00:00"),
        _line("draft_built", {
            "order_list_id": 900001, "symbol": "SOLUSDT",
            "tp_pct": "4", "sl_pct": "2",
            "tp_price": Decimal("10.40"), "stop_trigger": Decimal("9.80"),
            "stop_limit": Decimal("9.79"), "reference_price": Decimal("10.00"),
            "quantity": Decimal("5"), "dry_run": False,
        }, "2026-03-01T00:00:01+00:00"),
    ]


class ParseAuditTests(unittest.TestCase):
    def test_missing_file_returns_empty(self):
        self.assertEqual(parse_audit_jsonl("does_not_exist_12345.jsonl"), [])

    def test_blank_and_corrupt_lines_skipped(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "a.jsonl")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n")
            fh.write("{not valid json\n")
            fh.write("   \n")
            fh.write('"a bare string"\n')  # ليس كائنًا -> يُتخطّى
            fh.write(json.dumps({"ts": "t", "event": "x", "details": {}}) + "\n")
        recs = parse_audit_jsonl(path)
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["event"], "x")


class ComputeProfitTests(unittest.TestCase):
    def test_none_when_exit_or_reference_missing(self):
        self.assertIsNone(compute_profit(Decimal("100"), None, Decimal("1")))
        self.assertIsNone(compute_profit(None, Decimal("110"), Decimal("1")))

    def test_pct_and_usd(self):
        usd, pct = compute_profit(Decimal("100"), Decimal("112.5"), Decimal("2"))
        self.assertEqual(pct, Decimal("12.5"))
        self.assertEqual(usd, Decimal("25.0"))

    def test_pct_without_quantity(self):
        usd, pct = compute_profit(Decimal("100"), Decimal("110"), None)
        self.assertIsNone(usd)
        self.assertEqual(pct, Decimal("10"))


class FullTradeTests(unittest.TestCase):
    def setUp(self):
        self.records = parse_audit_jsonl(_write_audit(_full_trade_lines())[1])
        trades = build_completed_trades(self.records)
        # هذا الـ fixture يحوي صفقة كاملة واحدة فقط.
        self.assertEqual(len(trades), 1)
        self.trade = trades[0]

    def test_three_positioning_steps_chain(self):
        ids = [s.order_list_id for s in self.trade.steps]
        self.assertEqual(ids, [371236, 371452, 371600])

    def test_step_prices_and_ts(self):
        s0, s1, s2 = self.trade.steps
        # الخطوة الأولى: سعرها = سعر بدء المراقبة.
        self.assertEqual(s0.price, Decimal("100.00"))
        self.assertEqual(s0.ts, "2026-01-01T00:00:00+00:00")
        # مستويات الخطوة الأولى من draft_built المطابق.
        self.assertEqual(s0.stop_trigger, Decimal("98.00"))
        self.assertEqual(s0.stop_limit, Decimal("97.90"))
        self.assertEqual(s0.sell_price, Decimal("104.00"))
        # خطوات إعادة التموضع: السعر من repositioned.price.
        self.assertEqual(s1.price, Decimal("105.00"))
        self.assertEqual(s1.ts, "2026-01-01T00:00:10+00:00")
        self.assertEqual(s1.stop_trigger, Decimal("103.00"))
        self.assertEqual(s1.stop_limit, Decimal("102.90"))
        self.assertEqual(s1.sell_price, Decimal("109.00"))
        self.assertEqual(s2.price, Decimal("110.00"))
        self.assertEqual(s2.ts, "2026-01-01T00:00:20+00:00")
        self.assertEqual(s2.stop_trigger, Decimal("108.00"))
        self.assertEqual(s2.stop_limit, Decimal("107.90"))
        self.assertEqual(s2.sell_price, Decimal("114.00"))

    def test_reference_price_captured(self):
        self.assertEqual(self.trade.reference_price, Decimal("100.00"))

    def test_close_fields(self):
        self.assertEqual(self.trade.closed_at, "2026-01-01T00:00:31+00:00")
        self.assertEqual(self.trade.close_reason, "take_profit_filled")
        self.assertEqual(self.trade.exit_price, Decimal("112.50"))
        self.assertEqual(self.trade.side, "SELL")
        self.assertEqual(self.trade.quantity, Decimal("2"))

    def test_profit_computed(self):
        self.assertTrue(self.trade.profit_available)
        self.assertEqual(self.trade.profit_pct, Decimal("12.50"))
        # (112.50 - 100.00) * 2 = 25.00
        self.assertEqual(self.trade.profit_usd, Decimal("25.00"))

    def test_trade_key_stable(self):
        self.assertEqual(self.trade.trade_key, "371236@2026-01-01T00:00:00+00:00")


class NoFillTradeTests(unittest.TestCase):
    def test_exit_price_none_and_profit_unavailable(self):
        _, path = _write_audit(_no_fill_trade_lines())
        trades = build_completed_trades(parse_audit_jsonl(path))
        self.assertEqual(len(trades), 1)
        t = trades[0]
        self.assertIsNone(t.exit_price)
        self.assertIsNone(t.side)
        self.assertFalse(t.profit_available)
        self.assertIsNone(t.profit_pct)
        self.assertIsNone(t.profit_usd)


class OpenTradeExcludedTests(unittest.TestCase):
    def test_open_trade_included_as_live(self):
        # G1.24 P2: الصفقة المفتوحة (بلا monitor_closed) تُدرَج الآن كصفقة LIVE
        # بدل استبعادها، مع status="live" ودون سعر/سبب خروج.
        _, path = _write_audit(_open_trade_lines())
        trades = build_completed_trades(parse_audit_jsonl(path))
        self.assertEqual(len(trades), 1)
        live = trades[0]
        self.assertEqual(live.status, "live")
        self.assertEqual(live.end_reason, "live")
        self.assertIsNone(live.exit_price)
        self.assertEqual(live.close_reason, "")
        self.assertFalse(live.profit_available)
        self.assertEqual(live.steps[0].order_list_id, 900001)

    def test_mixed_completed_and_live_returned(self):
        # G1.24 P2: المقطع المُغلق يظهر كـ closed والمفتوح يظهر كـ live.
        lines = _full_trade_lines() + _open_trade_lines()
        _, path = _write_audit(lines)
        trades = build_completed_trades(parse_audit_jsonl(path))
        self.assertEqual(len(trades), 2)
        by_status = {t.status: t for t in trades}
        self.assertIn("closed", by_status)
        self.assertIn("live", by_status)
        self.assertEqual(by_status["closed"].steps[0].order_list_id, 371236)
        self.assertEqual(by_status["live"].steps[0].order_list_id, 900001)


class DismissStoreTests(unittest.TestCase):
    def test_dismiss_persists_and_is_dismissed(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "ocobot_completed_dismissed.json")
        store = DismissStore(path)
        self.assertEqual(store.load(), set())
        self.assertFalse(store.is_dismissed("k1"))
        store.dismiss("k1")
        self.assertTrue(DismissStore(path).is_dismissed("k1"))

    def test_corrupt_dismiss_file_treated_empty(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "dismiss.json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        self.assertEqual(DismissStore(path).load(), set())

    def test_load_completed_filters_dismissed_and_audit_bytes_unchanged(self):
        d, audit_path = _write_audit(_full_trade_lines() + _no_fill_trade_lines())

        with open(audit_path, "rb") as fh:
            before = fh.read()

        trades = load_completed_trades(audit_path)
        self.assertEqual(len(trades), 2)
        # اختر مفتاح الصفقة الكاملة لإخفائها.
        target = next(t for t in trades if t.steps[0].order_list_id == 371236)

        dismiss_path = default_dismiss_path(audit_path)
        DismissStore(dismiss_path).dismiss(target.trade_key)

        remaining = load_completed_trades(audit_path)
        remaining_keys = {t.trade_key for t in remaining}
        self.assertNotIn(target.trade_key, remaining_keys)
        self.assertEqual(len(remaining), 1)

        # إثبات: بايتات سجل التدقيق لم تتغيّر بعد dismiss.
        with open(audit_path, "rb") as fh:
            after = fh.read()
        self.assertEqual(before, after)


class TradeLabelFormatTests(unittest.TestCase):
    """يقفل صيغة ``_trade_label`` الجديدة وتسميات سبب الإنهاء (G1.23 — دون شبكة/Qt).

    اختبار وحدة نقيّ (offline): يستورد الدوال المستوى-الموديولي من
    ``ocobot.ui.completed_trades`` ويستدعيها مباشرة دون إنشاء أي widget من Qt.
    المسار المتّبع: الاستيراد يعمل بلا شاشة Qt فعليّة، لذا لا حاجة لـ importorskip؛
    لو تعذّر الاستيراد بسبب Qt مستقبلًا فسيُتخطّى هذا الصنف بنظافة عبر setUpClass.
    """

    @classmethod
    def setUpClass(cls):
        try:
            from ocobot.ui.completed_trades import (  # noqa: WPS433
                END_REASON_LABELS,
                _end_reason_label,
                _trade_label,
            )
        except Exception as exc:  # pragma: no cover - يُتخطّى عند غياب Qt
            raise unittest.SkipTest(
                "تعذّر استيراد ocobot.ui.completed_trades (Qt؟): %s" % exc
            )
        cls._trade_label = staticmethod(_trade_label)
        cls._end_reason_label = staticmethod(_end_reason_label)
        cls.END_REASON_LABELS = END_REASON_LABELS

    def _make_trade(self, session_id, end_reason):
        """يبني CompletedTrade بالحد الأدنى من الحقول اللازمة لـ _trade_label.

        نفس أسلوب البناء المباشر لـ CompletedTrade المستخدم عبر طبقة الـ domain؛
        القيم غير المؤثّرة على التسمية تُترك فارغة/غير متاحة (profit_available=False).
        """
        return CompletedTrade(
            trade_key="k@%s" % (session_id or "legacy"),
            symbol="BTCUSDT",
            reference_price=None,
            opened_at="2026-01-01T00:00:00+00:00",
            closed_at="2026-01-01T00:00:31+00:00",
            close_reason="take_profit_filled",
            exit_price=None,
            side=None,
            quantity=None,
            profit_available=False,
            session_id=session_id,
            end_reason=end_reason,
        )

    def test_new_trade_label_starts_with_session_and_has_arabic_reason(self):
        trade = self._make_trade("#aaaa1111.1", "stopped_manual")
        label = type(self)._trade_label(trade)
        self.assertTrue(
            label.startswith("#aaaa1111.1"),
            "يجب أن تبدأ التسمية بمعرّف الجلسة: %r" % label,
        )
        self.assertIn("موقوفة (يدوي)", label)

    def test_legacy_trade_label_no_session_prefix_has_arabic_reason(self):
        trade = self._make_trade("", "completed_tp")
        label = type(self)._trade_label(trade)
        self.assertFalse(
            label.startswith("#"),
            "صفقة قديمة بلا session_id يجب ألّا تبدأ بـ #: %r" % label,
        )
        self.assertIn("اكتملت (جني ربح)", label)

    def test_end_reason_label_mappings(self):
        self.assertEqual(
            type(self)._end_reason_label("stopped_other"), "موقوفة (أخرى)"
        )
        self.assertEqual(type(self)._end_reason_label(""), "—")


if __name__ == "__main__":
    unittest.main()
