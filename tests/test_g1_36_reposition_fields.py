"""اختبار عيب G1.36 (بلا شبكة، بلا Qt).

يُثبت أنّ رسالة «🔁 Repositioned» تُعبَّأ خاناتها بنفس بيانات «🚀 Monitor Started»:
  - build_reposition_message يقرأ Session/Symbol/Reference/Activation/TP/SL من
    details أوّلًا (كما monitor_start)، فتُملأ حتى عندما state=None.
  - AlertsAuditBridge يحمل سياق آخر monitor_start ويدمجه في سجلّ repositioned
    التالي، فتصل الرسالة بكل الخانات معبّأة لا «—».
"""
import unittest

from ocobot.alerts.formatting import build_reposition_message
from ocobot.alerts.bridge import AlertsAuditBridge


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
# حقول سجلّ repositioned الخام (قبل الإثراء).
_REPO_DETAILS = {"old_target": 111, "new_target": 222, "cursor": 1, "price": "80500"}

# قيم مشتقّة متوقّعة: ref*(1±pct/100).
_TP = "86400"       # 80000 * 1.08
_SL = "79200"       # 80000 * 0.99
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


class RepositionFieldsTests(unittest.TestCase):
    def test_builder_fills_fields_from_details_without_state(self):
        record = {"event": "repositioned", "ts": "2026-10-11T21:00:00Z",
                  "details": {**_START_CTX, **_REPO_DETAILS}}
        msg = build_reposition_message(record, state=None)
        self.assertIn("🔁", msg)
        self.assertIn("Symbol: BTCUSDT", msg)
        self.assertIn("abcd1234", msg)      # Session #abcd1234.1
        self.assertIn("80000", msg)         # Reference price
        self.assertIn(_TP, msg)             # TP مشتقّة
        self.assertIn(_SL, msg)             # SL مشتقّة
        self.assertIn(_ACTIVATION, msg)     # Activation مشتقّة
        self.assertIn("222", msg)           # Order list (current)
        self.assertIn("80500", msg)         # Current price
        # لا خانات فارغة في الحقول المطلوبة.
        self.assertNotIn("Symbol: —", msg)
        self.assertNotIn("Reference price: —", msg)

    def test_builder_still_falls_back_to_state(self):
        # عند غياب الحقول من details، يرجع للسلوك القديم (state) — بلا انحدار.
        class _State:
            symbol = "ETHUSDT"
            trade_uid = "zzz9"
            session_no = 2
            reference_price = "2000"
            trigger_pct = "1"
            tp_pct = "8"
            sl_pct = "1"
            target_order_list_id = 999
            cursor = 3
            last_price = "2010"
            last_reposition = None
        record = {"event": "repositioned", "ts": "T", "details": dict(_REPO_DETAILS)}
        msg = build_reposition_message(record, state=_State())
        self.assertIn("Symbol: ETHUSDT", msg)
        self.assertIn("2000", msg)  # reference from state

    def test_bridge_enriches_repositioned_from_prior_monitor_start(self):
        records = [
            {"event": "monitor_start", "ts": "T1", "details": dict(_START_CTX)},
            {"event": "repositioned", "ts": "T2", "details": dict(_REPO_DETAILS)},
        ]
        notifier = _FakeNotifier()
        bridge = AlertsAuditBridge(
            notifier=notifier, store=_FakeStore(),
            parse_fn=lambda _path: records, start_at_end=False,
        )
        n = bridge.poll_once()
        self.assertEqual(n, 2)
        repo_text = notifier.texts[1]
        self.assertIn("🔁", repo_text)
        self.assertIn("Symbol: BTCUSDT", repo_text)
        self.assertIn("80000", repo_text)       # reference مُثراة من monitor_start
        self.assertIn(_TP, repo_text)
        self.assertIn(_SL, repo_text)
        self.assertIn(_ACTIVATION, repo_text)
        self.assertIn("222", repo_text)          # new order list (own-wins)
        self.assertIn("80500", repo_text)        # current price (own-wins)
        self.assertNotIn("Symbol: —", repo_text)
        self.assertNotIn("Reference price: —", repo_text)


if __name__ == "__main__":
    unittest.main()
