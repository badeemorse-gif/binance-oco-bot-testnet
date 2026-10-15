# -*- coding: utf-8 -*-
"""اختبار عيب G1.63 (بلا شبكة، بلا Qt فعليّ).

يُثبت أنّ زرّ «تنفيذ الخروج الفوري» يُشعِر في كل حالة:
  - build_manual_exit_message: فرع «غير المنفَّذ» (placed=False) يعرض نتيجة واضحة
    بالسبب؛ ومسار المنفَّذ (placed=True/None) يبقى كما هو (الحقول القياسية) — لا انحدار.
  - manual_exit_record يحمل placed/reason.
  - build_manual_exit_fn يُطلِق notifier لكل ضغطة: PLACED مرّة واحدة (عبر
    execute_market_exit، بلا ازدواج)، وABORT (بوّابة/لا تحديد) مرّة واحدة (المسار الجديد).
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest
from decimal import Decimal
from types import SimpleNamespace

from ocobot.alerts.formatting import build_manual_exit_message
from ocobot.alerts.bridge import manual_exit_record, make_manual_exit_notifier
from ocobot.ui.manual_exit import build_manual_exit_fn


def _filters(tick="0.01", step="0.00001"):
    return SimpleNamespace(
        symbol="BTCUSDT", tick_size=Decimal(tick), step_size=Decimal(step),
        min_qty=None, min_notional=None, gap_ticks=1,
    )


class FakeMarketExitClient:
    def __init__(self, free="1.0", resting=()):
        self._free = Decimal(str(free))
        self._resting = list(resting)
        self.placed = []

    def get_open_sell_orders(self, symbol):
        return list(self._resting)

    def get_free_asset_qty(self, asset):
        return self._free

    def cancel_oco(self, symbol, order_list_id):
        return {"ok": True, "orderListId": order_list_id}

    def place_stop_loss_limit(self, symbol, quantity, stop_price, limit_price, client_order_id):
        self.placed.append(("STOP_LOSS_LIMIT", quantity, client_order_id))
        return {"orderId": 11, "status": "NEW"}

    def place_limit_sell(self, symbol, quantity, price, client_order_id):
        self.placed.append(("LIMIT", quantity, price, client_order_id))
        return {"orderId": 12, "status": "NEW"}

    def place_market_sell(self, symbol, quantity, client_order_id):
        self.placed.append(("MARKET", quantity, client_order_id))
        return {"orderId": 13, "status": "NEW"}


class _FakeNotifier:
    def __init__(self):
        self.texts = []

    def enqueue(self, text, **kwargs):
        self.texts.append(text)
        return True


class _FakeStore:
    def enabled_provider(self):
        return True


class ManualExitMessageTests(unittest.TestCase):
    def test_not_placed_shows_outcome_and_reason(self):
        rec = manual_exit_record({
            "action": "ABORT_PROTECTED", "placed": False, "symbol": "BTCUSDT",
        })
        self.assertIs(rec["details"]["placed"], False)
        msg = build_manual_exit_message(rec)
        self.assertIn("✋ *Manual Exit*", msg)
        self.assertIn("not placed", msg)
        self.assertIn("PROTECTED", msg)  # ABORT\_PROTECTED (مُهرَّب لـMarkdownV2)
        self.assertIn("a protective sell order already rests", msg)

    def test_placed_message_unchanged_standard_fields(self):
        rec = manual_exit_record({
            "action": "PLACED", "placed": True, "symbol": "BTCUSDT",
            "exit_side": "upper", "eff_qty": "0.5",
            "plan": {"price": "71000", "quantity": "0.5"},
            "reference_price": "70000", "client_order_id": "mex-x",
            "response": {"orderId": 12},
        })
        self.assertIs(rec["details"]["placed"], True)
        msg = build_manual_exit_message(rec)
        self.assertIn("✋ *Manual Exit*", msg)
        self.assertNotIn("not placed", msg)
        self.assertIn("Entry: ", msg)
        self.assertIn("Exit price: ", msg)
        self.assertIn("PnL%: ", msg)
        self.assertIn("70000", msg)   # entry
        self.assertIn("71000", msg)   # exit

    def test_record_carries_reason(self):
        rec = manual_exit_record({"action": "ABORT_GATE", "placed": False, "reason": "x"})
        self.assertEqual(rec["details"]["reason"], "x")


class BuildManualExitFnNotifyTests(unittest.TestCase):
    def _make(self, client, state, selected):
        fake = _FakeNotifier()
        emit = make_manual_exit_notifier(notifier=fake, store=_FakeStore())
        fn = build_manual_exit_fn(
            exit_broker=client,
            state_provider=lambda: state,
            selected_provider=lambda: selected,
            filters_fn=lambda s: _filters(),
            base_asset_fn=lambda s: "BTC",
            notifier_getter=lambda: emit,
            exit_side="upper",
            dry_run=False,
        )
        return fn, fake

    def test_placed_emits_exactly_once(self):
        client = FakeMarketExitClient(free="1.0", resting=())
        state = SimpleNamespace(reference_price=Decimal("70000"),
                                target_order_list_id=31, selected_oco=None)
        selected = SimpleNamespace(symbol="BTCUSDT", quantity=Decimal("0.5"),
                                   order_list_id=31, current_price=Decimal("70000"))
        fn, fake = self._make(client, state, selected)
        res = fn()
        self.assertEqual(res["action"], "PLACED")
        self.assertEqual(len(fake.texts), 1)                 # لا ازدواج
        self.assertIn("✋ *Manual Exit*", fake.texts[0])
        self.assertNotIn("not placed", fake.texts[0])

    def test_abort_gate_emits_exactly_once(self):
        # بيع حمائي قائم ⇒ البوّابة تمنع ⇒ ABORT_GATE (الحالة الشائعة التي كانت صامتة).
        client = FakeMarketExitClient(free="1.0", resting=[{"orderId": 1}])
        state = SimpleNamespace(reference_price=Decimal("70000"),
                                target_order_list_id=31, selected_oco=None)
        selected = SimpleNamespace(symbol="BTCUSDT", quantity=Decimal("0.5"),
                                   order_list_id=31, current_price=Decimal("70000"))
        fn, fake = self._make(client, state, selected)
        res = fn()
        self.assertEqual(res["action"], "ABORT_GATE")
        self.assertFalse(res["placed"])
        self.assertEqual(len(fake.texts), 1)                 # لم يعد صامتًا
        self.assertIn("not placed", fake.texts[0])

    def test_no_selection_emits(self):
        client = FakeMarketExitClient()
        fn, fake = self._make(client, SimpleNamespace(selected_oco=None), None)
        res = fn()
        self.assertEqual(res["action"], "ABORT_NO_SELECTION")
        self.assertEqual(len(fake.texts), 1)
        self.assertIn("not placed", fake.texts[0])


if __name__ == "__main__":
    unittest.main()
