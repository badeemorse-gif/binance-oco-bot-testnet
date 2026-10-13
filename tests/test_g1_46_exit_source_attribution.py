"""اختبارات إسناد مصدر الخروج (exit_source) للوسائل الأربع — G1.46.

نموذج قراءة خالص فوق سجلّ تدقيق JSONL اصطناعي (TemporaryDirectory): كل صفقة
مُغلقة تُسنَد لإحدى الوسائل الأربع
(MONITORING | PRICE_BRACKET | BTC_FOLLOW | POSITION_SAFETY_NET) عبر آخر علامة
``exit_source`` داخل مقطع الصفقة (monitor_start → monitor_closed). غياب العلامة
⇒ MONITORING (توافق خلفي مع السجلّات القديمة). عرض فقط — لا مساس بأي منطق تنفيذ.

قابلة للتشغيل عبر: python -m unittest tests.test_g1_46_exit_source_attribution
"""
import json
import os
import tempfile
import unittest
from decimal import Decimal

from ocobot.domain.completed_trades import (
    build_completed_trades,
    parse_audit_jsonl,
)


def _line(event, details, ts):
    """سطر JSONL واحد بنفس شكل AuditLog (Decimal كنصوص عبر default=str)."""
    return json.dumps(
        {"ts": ts, "event": event, "details": details},
        ensure_ascii=False,
        default=str,
    )


def _write_audit(lines):
    """يكتب أسطر JSONL إلى ملف داخل مجلّد مؤقّت ويعيد path."""
    d = tempfile.mkdtemp()
    path = os.path.join(d, "ocobot_audit.jsonl")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return path


def _parse(lines):
    return parse_audit_jsonl(_write_audit(lines))


def _closed_segment(order_list_id, symbol, sources, *, closed=True, base_sec=0):
    """مقطع صفقة واحد: monitor_start ثم علامات exit_source (0..n) ثم
    monitor_closed (إن ``closed``). ``sources`` قائمة قيم exit_source بالترتيب.
    """
    def ts(sec):
        return "2026-05-01T00:00:%02d+00:00" % (base_sec + sec)

    lines = [
        _line(
            "monitor_start",
            {
                "order_list_id": order_list_id,
                "symbol": symbol,
                "trigger_pct": "3",
                "tp_pct": "4",
                "sl_pct": "2",
                "reference_price": Decimal("100.00"),
                "tolerance_pct": "0.1",
                "guard_pct": "1.0",
                "dry_run": False,
            },
            ts(0),
        )
    ]
    for i, src in enumerate(sources, start=1):
        lines.append(_line("exit_source", {"source": src}, ts(i)))
    if closed:
        lines.append(
            _line(
                "monitor_closed",
                {"end_reason": "completed_sl", "reason": "stopped"},
                ts(len(sources) + 1),
            )
        )
    return lines


def _only_trade(lines):
    trades = build_completed_trades(_parse(lines))
    assert len(trades) == 1, "expected exactly one trade, got %d" % len(trades)
    return trades[0]


class ExitSourceAttributionTests(unittest.TestCase):
    def test_monitoring_is_default_without_marker(self):
        """لا علامة exit_source ⇒ الإسناد الافتراضي MONITORING."""
        trade = _only_trade(_closed_segment(5001, "BTCUSDT", []))
        self.assertEqual(trade.status, "closed")
        self.assertEqual(trade.exit_source, "MONITORING")

    def test_price_bracket_attribution(self):
        trade = _only_trade(_closed_segment(5002, "BTCUSDT", ["PRICE_BRACKET"]))
        self.assertEqual(trade.exit_source, "PRICE_BRACKET")

    def test_btc_follow_attribution(self):
        trade = _only_trade(_closed_segment(5003, "BTCUSDT", ["BTC_FOLLOW"]))
        self.assertEqual(trade.exit_source, "BTC_FOLLOW")

    def test_position_safety_net_attribution(self):
        trade = _only_trade(
            _closed_segment(5004, "BTCUSDT", ["POSITION_SAFETY_NET"])
        )
        self.assertEqual(trade.exit_source, "POSITION_SAFETY_NET")

    def test_last_marker_wins_within_segment(self):
        """عند تعدّد العلامات داخل المقطع ⇒ الأخيرة تفوز."""
        trade = _only_trade(
            _closed_segment(5005, "BTCUSDT", ["BTC_FOLLOW", "POSITION_SAFETY_NET"])
        )
        self.assertEqual(trade.exit_source, "POSITION_SAFETY_NET")

    def test_invalid_marker_falls_back_to_monitoring(self):
        """قيمة exit_source غير معروفة ⇒ تجاهلها والعودة إلى MONITORING."""
        trade = _only_trade(_closed_segment(5006, "BTCUSDT", ["GARBAGE_X"]))
        self.assertEqual(trade.exit_source, "MONITORING")

    def test_backward_compat_old_log_without_markers(self):
        """سجلّ قديم (صفقتان مغلقتان بلا أي علامة) ⇒ كلاهما MONITORING."""
        lines = _closed_segment(5007, "BTCUSDT", [], base_sec=0)
        lines += _closed_segment(5008, "ETHUSDT", [], base_sec=10)
        trades = build_completed_trades(_parse(lines))
        self.assertEqual(len(trades), 2)
        self.assertTrue(all(t.exit_source == "MONITORING" for t in trades))

    def test_live_open_trade_has_empty_exit_source(self):
        """صفقة مفتوحة (بلا monitor_closed) ⇒ exit_source فارغ (لا خروج بعد)."""
        lines = _closed_segment(5009, "BTCUSDT", [], closed=False)
        trades = build_completed_trades(_parse(lines))
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].status, "live")
        self.assertEqual(trades[0].exit_source, "")

    def test_attribution_isolated_per_segment(self):
        """علامة في مقطع لا تتسرّب إلى المقطع التالي."""
        lines = _closed_segment(5010, "BTCUSDT", ["PRICE_BRACKET"], base_sec=0)
        lines += _closed_segment(5011, "BTCUSDT", [], base_sec=10)
        trades = build_completed_trades(_parse(lines))
        self.assertEqual(len(trades), 2)
        by_src = {t.exit_source for t in trades}
        self.assertEqual(by_src, {"PRICE_BRACKET", "MONITORING"})


if __name__ == "__main__":
    unittest.main()
