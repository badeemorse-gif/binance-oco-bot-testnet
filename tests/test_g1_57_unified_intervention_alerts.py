"""G1.57 — unified intervention Telegram alerts + BTC-follow richness (offline).

يغطّي:
  * الرؤوس المميّزة الأربعة الصحيحة (🛡️ / 🧷 / ⬇️ / ✋).
  * وجود الحقول القياسية الموحّدة في كل رسالة (Symbol/Reason/Entry/Exit
    price/PnL%/Quantity/Order id/Client order id/Time).
  * صحّة PnL% (entry=100, exit=99 ⇒ "-1%").
  * رسالة BTC الثريّة كاملة الحقول + رسالة الخروج اليدوي الثريّة.
  * توجيه format_event لحدثَي btc_follow_intervention و manual_exit.
  * مُطلِقا make_btc_follow_notifier / make_manual_exit_notifier
    (enqueue مرّة واحدة عند التفعيل، صفر عند التعطيل، ابتلاع notifier رامٍ).
  * لقطة ثبات: build_monitor_start_message و build_reposition_message لسجلّ
    تمثيلي تطابق نصًّا مُجمّدًا حرفيًّا (حارس ضدّ أي تغيّر غير مقصود).

بلا شبكة وبلا Qt — fakes بسيطة على نمط test_g1_37_intervention_alerts.
"""
import unittest
from decimal import Decimal
from types import SimpleNamespace

from ocobot.alerts.formatting import (
    build_monitor_start_message,
    build_reposition_message,
    build_guardian_message,
    build_market_exit_message,
    build_btc_follow_message,
    build_manual_exit_message,
    format_event,
    _pnl_pct,
)
from ocobot.alerts.bridge import (
    btc_follow_record,
    manual_exit_record,
    make_btc_follow_notifier,
    make_manual_exit_notifier,
)


# ---------------------------------------------------------------------------
# fakes (mirroring the existing alerts tests)
# ---------------------------------------------------------------------------
class _FakeNotifier:
    def __init__(self):
        self.texts = []

    def enqueue(self, text, **kwargs):
        self.texts.append(text)
        return True


class _RaisingNotifier:
    def enqueue(self, text, **kwargs):
        raise RuntimeError("enqueue boom")


class _FakeStore:
    def __init__(self, enabled=True):
        self._enabled = enabled

    def enabled_provider(self):
        return self._enabled


class _Rec:
    """كائن MonitoringState-شبيه بسيط لتغذية القوالب (سمات فقط)."""

    def __init__(self, **kw):
        self.__dict__.update(kw)


# الحقول القياسية الموحّدة (نصوص الليبلات كما تظهر في الرسالة).
_STANDARD_LABELS = (
    "Symbol:", "Reason:", "Entry:", "Exit price:", "PnL%:",
    "Quantity:", "Order id:", "Client order id:", "Time:",
)


def _guardian_record():
    return {
        "event": "guardian_intervention",
        "ts": "2026-10-11T21:00:00Z",
        "details": {
            "symbol": "ETHUSDT",
            "reason": "naked beyond threshold",
            "action": "PLACED",
            "eff_qty": "5",
            "reference_price": "100",
            "emergency_sl_pct": "1",
            "client_order_id": "grd-xyz-1",
            "plan": {"quantity": "5", "stop_trigger": "99",
                     "stop_price": "99", "limit_price": "98.9"},
            "response": {"orderId": 4242},
        },
    }


def _market_exit_record(side="upper"):
    return {
        "event": "market_exit",
        "ts": "2026-10-11T22:30:00Z",
        "details": {
            "symbol": "LSKUSDT",
            "exit_side": side,
            "action": "PLACED",
            "eff_qty": "50",
            "reference_price": "100",
            "client_order_id": "bexit-1",
            "plan": {"quantity": "50", "type": "LIMIT", "stop_price": "97",
                     "limit_price": "98", "price": "99"},
            "response": {"orderId": 7777},
        },
    }


def _btc_payload():
    return {
        "symbol": "ETHUSDT",
        "drop_pct": "3.5",
        "reason": "BTC drop confirmed",
        "result": {
            "action": "PLACED",
            "eff_qty": "5",
            "client_order_id": "btcg-1",
            "plan": {"price": "97", "quantity": "5"},
            "response": {"orderId": 4242},
        },
        "reference_price": "100",
    }


def _manual_result():
    return {
        "action": "PLACED",
        "symbol": "LSKUSDT",
        "exit_side": "upper",
        "eff_qty": "50",
        "client_order_id": "mex-1",
        "reference_price": "100",
        "plan": {"price": "99", "quantity": "50"},
        "response": {"orderId": 8888},
    }


# ---------------------------------------------------------------------------
# (1) الرؤوس المميّزة الأربعة
# ---------------------------------------------------------------------------
class TestHeaders(unittest.TestCase):
    def test_guardian_header(self):
        self.assertIn("🛡️ *Position Guardian*", build_guardian_message(_guardian_record()))

    def test_bracket_header_upper(self):
        msg = build_market_exit_message(_market_exit_record("upper"))
        self.assertIn("🧷 *Price Exit Bracket* \\(Upper\\)", msg)

    def test_bracket_header_lower(self):
        msg = build_market_exit_message(_market_exit_record("lower"))
        self.assertIn("🧷 *Price Exit Bracket* \\(Lower\\)", msg)

    def test_btc_header(self):
        self.assertIn("⬇️ *BTC\\-Follow Guard*", build_btc_follow_message(
            btc_follow_record(**_btc_payload())))

    def test_manual_header(self):
        self.assertIn("✋ *Manual Exit*", build_manual_exit_message(
            manual_exit_record(_manual_result())))


# ---------------------------------------------------------------------------
# (2) الحقول القياسية الموحّدة حاضرة في كل رسالة
# ---------------------------------------------------------------------------
class TestStandardFieldsPresent(unittest.TestCase):
    def _assert_labels(self, msg, labels):
        for label in labels:
            self.assertIn(label, msg)

    def test_guardian_has_standard_fields(self):
        # الحارس يحمل حقل Reason صراحةً إضافةً لبقية الحقول القياسية.
        self._assert_labels(build_guardian_message(_guardian_record()),
                            _STANDARD_LABELS)

    def test_bracket_has_standard_fields(self):
        # البراكِت يستعمل "Exit side:" بدل "Reason:" (حقول قائمة) + الحقول الجديدة.
        bracket_labels = tuple(
            lbl for lbl in _STANDARD_LABELS if lbl != "Reason:"
        ) + ("Exit side:",)
        self._assert_labels(build_market_exit_message(_market_exit_record()),
                            bracket_labels)

    def test_btc_has_standard_fields(self):
        self._assert_labels(build_btc_follow_message(
            btc_follow_record(**_btc_payload())), _STANDARD_LABELS)

    def test_manual_has_standard_fields(self):
        self._assert_labels(build_manual_exit_message(
            manual_exit_record(_manual_result())), _STANDARD_LABELS)


# ---------------------------------------------------------------------------
# (3) صحّة PnL%
# ---------------------------------------------------------------------------
class TestPnlPct(unittest.TestCase):
    def test_loss_one_percent(self):
        # entry=100 exit=99 ⇒ -1% (مُهرّب لـMarkdownV2 كـ"\\-1%")
        self.assertIn("-1%", _pnl_pct("100", "99"))

    def test_gain_one_percent(self):
        self.assertEqual(_pnl_pct("100", "101"), "1%")

    def test_missing_is_dash(self):
        self.assertEqual(_pnl_pct(None, "99"), "—")
        self.assertEqual(_pnl_pct("100", None), "—")

    def test_zero_entry_is_dash(self):
        self.assertEqual(_pnl_pct("0", "99"), "—")

    def test_guardian_message_shows_minus_one(self):
        # entry=reference_price=100, exit=stop_trigger=99 ⇒ -1%
        self.assertIn("-1%", build_guardian_message(_guardian_record()))


# ---------------------------------------------------------------------------
# (4) BTC الثريّة كاملة الحقول + Manual الثريّة
# ---------------------------------------------------------------------------
class TestBtcAndManualRichness(unittest.TestCase):
    def test_btc_full_fields(self):
        msg = build_btc_follow_message(btc_follow_record(**_btc_payload()))
        self.assertIn("⬇️", msg)
        self.assertIn("ETHUSDT", msg)              # symbol
        self.assertIn("BTC drop confirmed", msg)   # reason
        self.assertIn("3", msg)                    # drop_pct digit
        self.assertIn("Entry:", msg)
        self.assertIn("100", msg)                  # entry
        self.assertIn("97", msg)                   # exit price
        self.assertIn("-3%", msg)                  # PnL% (100→97)
        self.assertIn("5", msg)                    # quantity
        self.assertIn("4242", msg)                 # order id
        self.assertIn("btcg", msg)                 # client order id (escaped '-')

    def test_manual_full_fields(self):
        msg = build_manual_exit_message(manual_exit_record(_manual_result()))
        self.assertIn("✋", msg)
        self.assertIn("LSKUSDT", msg)
        self.assertIn("Manual exit", msg)          # reason
        self.assertIn("100", msg)                  # entry
        self.assertIn("99", msg)                   # exit price
        self.assertIn("-1%", msg)                  # PnL% (100→99)
        self.assertIn("50", msg)                   # quantity
        self.assertIn("8888", msg)                 # order id
        self.assertIn("mex", msg)                  # client order id (escaped '-')

    def test_builders_never_raise_on_garbage(self):
        self.assertTrue(build_btc_follow_message({}))
        self.assertTrue(build_btc_follow_message(None))
        self.assertTrue(build_manual_exit_message({}))
        self.assertTrue(build_manual_exit_message(None))


# ---------------------------------------------------------------------------
# (5) format_event routing للحدثين الجديدين
# ---------------------------------------------------------------------------
class TestFormatEventRouting(unittest.TestCase):
    def test_routes_btc_follow(self):
        msg = format_event(btc_follow_record(**_btc_payload()))
        self.assertIsNotNone(msg)
        self.assertIn("⬇️", msg)

    def test_routes_manual_exit(self):
        msg = format_event(manual_exit_record(_manual_result()))
        self.assertIsNotNone(msg)
        self.assertIn("✋", msg)

    def test_record_shapes(self):
        self.assertEqual(
            btc_follow_record(**_btc_payload())["event"], "btc_follow_intervention")
        self.assertEqual(
            manual_exit_record(_manual_result())["event"], "manual_exit")


# ---------------------------------------------------------------------------
# (6) emit adapters
# ---------------------------------------------------------------------------
class TestBtcFollowNotifier(unittest.TestCase):
    def test_placed_enqueues_once(self):
        notifier, store = _FakeNotifier(), _FakeStore(enabled=True)
        emit = make_btc_follow_notifier(notifier=notifier, store=store)
        emit(_btc_payload())
        self.assertEqual(len(notifier.texts), 1)
        self.assertIn("⬇️", notifier.texts[0])
        self.assertIn("ETHUSDT", notifier.texts[0])
        self.assertIn("4242", notifier.texts[0])

    def test_disabled_store_does_not_enqueue(self):
        notifier, store = _FakeNotifier(), _FakeStore(enabled=False)
        emit = make_btc_follow_notifier(notifier=notifier, store=store)
        emit(_btc_payload())
        self.assertEqual(len(notifier.texts), 0)

    def test_raising_enqueue_is_swallowed(self):
        emit = make_btc_follow_notifier(notifier=_RaisingNotifier(),
                                        store=_FakeStore(enabled=True))
        emit(_btc_payload())  # must not raise


class TestManualExitNotifier(unittest.TestCase):
    def test_placed_enqueues_once(self):
        notifier, store = _FakeNotifier(), _FakeStore(enabled=True)
        emit = make_manual_exit_notifier(notifier=notifier, store=store)
        emit(_manual_result())
        self.assertEqual(len(notifier.texts), 1)
        self.assertIn("✋", notifier.texts[0])
        self.assertIn("LSKUSDT", notifier.texts[0])
        self.assertIn("8888", notifier.texts[0])

    def test_disabled_store_does_not_enqueue(self):
        notifier, store = _FakeNotifier(), _FakeStore(enabled=False)
        emit = make_manual_exit_notifier(notifier=notifier, store=store)
        emit(_manual_result())
        self.assertEqual(len(notifier.texts), 0)

    def test_raising_enqueue_is_swallowed(self):
        emit = make_manual_exit_notifier(notifier=_RaisingNotifier(),
                                         store=_FakeStore(enabled=True))
        emit(_manual_result())  # must not raise


# ---------------------------------------------------------------------------
# (7) لقطة ثبات monitor_start / repositioned (حارس ضدّ أي تغيّر)
# ---------------------------------------------------------------------------
_FROZEN_MONITOR_START = (
    "🚀 *Monitor Started*\n"
    "\n"
    "Session: \\#ab12cd34\\.1\n"
    "Symbol: BTCUSDT\n"
    "Order list: 999\n"
    "\n"
    "Reference price: 100\n"
    "Last price: 🟡 —\n"
    "Activation \\(next\\): 101  \\(1%\\)\n"
    "\n"
    "TP: 🟢 102  \\(2%\\)\n"
    "SL: 🔴 99  \\(1%\\)\n"
    "\n"
    "Time: 2026\\-01\\-01T00:00:00Z"
)

_FROZEN_REPOSITION = (
    "🔁 *Repositioned*\n"
    "\n"
    "Session: \\#ab12cd34\\.2\n"
    "Symbol: BTCUSDT\n"
    "Order list \\(current\\): 1000\n"
    "Order list \\(previous\\): 999\n"
    "\n"
    "Current price: 🟡 101\n"
    "Previous price: 100\n"
    "Reference price: 100\n"
    "Activation \\(next\\): 101  \\(1%\\)\n"
    "\n"
    "TP: 🟢 102  \\(2%\\)\n"
    "SL: 🔴 99  \\(1%\\)\n"
    "\n"
    "Cursor: C3\n"
    "Time: 2026\\-01\\-01T00:05:00Z"
)


class TestFrozenSnapshotsUnchanged(unittest.TestCase):
    def test_monitor_start_byte_for_byte(self):
        rec = {
            "event": "monitor_start",
            "ts": "2026-01-01T00:00:00Z",
            "details": {
                "trade_uid": "ab12cd34", "session_no": 1, "symbol": "BTCUSDT",
                "order_list_id": 999, "reference_price": "100",
                "trigger_pct": "1", "tp_pct": "2", "sl_pct": "1",
            },
        }
        self.assertEqual(build_monitor_start_message(rec), _FROZEN_MONITOR_START)

    def test_reposition_byte_for_byte(self):
        state = _Rec(
            trade_uid="ab12cd34", session_no=2, symbol="BTCUSDT",
            reference_price="100", trigger_pct="1", tp_pct="2", sl_pct="1",
            last_price="101",
        )
        rec = {
            "event": "repositioned",
            "ts": "2026-01-01T00:05:00Z",
            "details": {"new_target": 1000, "old_target": 999,
                        "price": "101", "cursor": "C3"},
        }
        self.assertEqual(
            build_reposition_message(rec, state, prev_price="100"),
            _FROZEN_REPOSITION,
        )


if __name__ == "__main__":
    unittest.main()
