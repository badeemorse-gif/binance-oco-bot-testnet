# -*- coding: utf-8 -*-
"""اختبار عيب G1.62 (بلا شبكة، بلا Qt).

يُثبت تغطية تنبيهات Telegram الكاملة لدورة المراقبة التي طلبها المستخدم:
  - build_monitor_closed_message: رسالة إغلاق موحّدة (خروج ببيع TP/SL أو إيقاف
    يدوي) تحمل سبب الإغلاق + النِّسب العاملة (تموضع/TP/SL) + نتيجة الصفقة%.
  - format_event يوجّه حدث monitor_closed.
  - AlertsAuditBridge: monitor_closed ضمن _ALERT_EVENTS ويُثرى من آخر
    monitor_start، فتصل رسالة إغلاق مكتملة الخانات بعد رسالة البدء.
  - حارس انحدار: app.py يمرّر notifier (make_market_exit_notifier) إلى قوس
    الخروج بالسعر — كان مفقودًا في الإنتاج ⇒ القوس صامت عند التدخّل.
"""
import os
import unittest

from ocobot.alerts.formatting import build_monitor_closed_message, format_event
from ocobot.alerts.bridge import AlertsAuditBridge, _ALERT_EVENTS


# سياق جلسة كامل (كما يكتبه المحرّك في سجلّ monitor_start).
_START_CTX = {
    "symbol": "BTCUSDT",
    "reference_price": "80000",
    "trigger_pct": "1",
    "tp_pct": "8",
    "sl_pct": "1",
    "trade_uid": "abcd1234",
    "session_no": 1,
    "order_list_id": 111,
}
# قيم مشتقّة متوقّعة: ref*(1±pct/100).
_TP = "86400"          # 80000 * 1.08
_SL = "79200"          # 80000 * 0.99
_ACTIVATION = "80800"  # 80000 * 1.01


class _FakeNotifier:
    def __init__(self):
        self.texts = []

    def enqueue(self, text, **kwargs):
        self.texts.append(text)
        return True


class _FakeStore:
    def enabled_provider(self):
        return True


class MonitorClosedMessageTests(unittest.TestCase):
    def test_completed_tp_shows_outcome_result_and_levels(self):
        record = {"event": "monitor_closed", "ts": "2026-10-15T12:00:00Z",
                  "details": {**_START_CTX,
                              "end_reason": "completed_tp",
                              "reason": "take-profit filled"}}
        msg = build_monitor_closed_message(record, state=None)
        self.assertIn("🏁", msg)
        self.assertIn("Monitor Closed", msg)
        self.assertIn("Symbol: BTCUSDT", msg)
        self.assertIn("Take Profit", msg)       # outcome
        self.assertIn("Result%: 8%", msg)        # ‪+tp_pct‬
        self.assertIn(_TP, msg)                  # TP level derived
        self.assertIn(_SL, msg)                  # SL level derived
        self.assertIn("80000", msg)              # reference price

    def test_completed_sl_shows_loss_outcome(self):
        record = {"event": "monitor_closed", "ts": "T",
                  "details": {**_START_CTX, "end_reason": "completed_sl"}}
        msg = build_monitor_closed_message(record, state=None)
        self.assertIn("Stop Loss", msg)
        self.assertIn(_SL, msg)
        self.assertIn("Result%:", msg)

    def test_stopped_manual_shows_outcome_without_result(self):
        record = {"event": "monitor_closed", "ts": "T",
                  "details": {**_START_CTX, "end_reason": "stopped_manual"}}
        msg = build_monitor_closed_message(record, state=None)
        self.assertIn("Stopped manually", msg)
        self.assertIn("Result%: —", msg)         # لا ربح/خسارة عند الإيقاف اليدوي

    def test_never_raises_on_garbage(self):
        self.assertIsInstance(build_monitor_closed_message(None), str)
        self.assertIsInstance(
            build_monitor_closed_message({"event": "monitor_closed"}), str)


class FormatEventRoutingTests(unittest.TestCase):
    def test_monitor_closed_in_alert_events(self):
        self.assertIn("monitor_closed", _ALERT_EVENTS)

    def test_format_event_routes_monitor_closed(self):
        record = {"event": "monitor_closed", "ts": "T",
                  "details": {**_START_CTX, "end_reason": "completed_tp"}}
        msg = format_event(record)
        self.assertIsNotNone(msg)
        self.assertIn("🏁", msg)


class BridgeMonitorClosedTests(unittest.TestCase):
    def test_bridge_emits_and_enriches_monitor_closed(self):
        records = [
            {"event": "monitor_start", "ts": "T1", "details": dict(_START_CTX)},
            {"event": "monitor_closed", "ts": "T2",
             "details": {"end_reason": "completed_tp", "reason": "tp filled"}},
        ]
        notifier = _FakeNotifier()
        bridge = AlertsAuditBridge(
            notifier=notifier, store=_FakeStore(),
            parse_fn=lambda _p: records, start_at_end=False,
        )
        n = bridge.poll_once()
        self.assertEqual(n, 2)
        closed_text = notifier.texts[1]
        self.assertIn("🏁", closed_text)
        self.assertIn("Symbol: BTCUSDT", closed_text)   # مُثرى من monitor_start
        self.assertIn("80000", closed_text)             # reference مُثراة
        self.assertIn(_TP, closed_text)                 # TP level مُثرى
        self.assertIn("Result%: 8%", closed_text)
        self.assertNotIn("Symbol: —", closed_text)


class BracketNotifierWiringRegressionTests(unittest.TestCase):
    """G1.62: قوس الخروج بالسعر كان يُنشأ في الإنتاج دون notifier ⇒ صامت.

    حارس انحدار على مستوى المصدر (بلا Qt): يتأكّد أنّ app.py يستورد
    make_market_exit_notifier ويمرّره إلى BracketExitWiring عبر notifier=.
    """
    def _app_src(self):
        here = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(here, "..", "ocobot", "ui", "app.py")
        with open(path, encoding="utf-8") as f:
            return f.read()

    def test_app_imports_market_exit_notifier(self):
        self.assertIn("make_market_exit_notifier", self._app_src())

    def test_bracket_wiring_receives_notifier(self):
        self.assertIn("notifier=_mk_bx_notifier(", self._app_src())


if __name__ == "__main__":
    unittest.main()
