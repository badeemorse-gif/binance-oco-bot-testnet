"""اختبارات G1.30 (chunk_2) — منفّذ الوقف الحمائي (guardian_exec.py).

تُختبر الوحدة بمحاكاة عميل في الذاكرة (يسجّل الاستدعاءات، بلا شبكة):
  - بيع حمائي قائم ⇒ ABORT_PROTECTED، وعدم استدعاء place_stop_loss_limit إطلاقًا.
  - رصيد حرّ < qty ⇒ eff_qty مقصورة على الرصيد (الكمية المُخطّطة = floored free).
  - رصيد حرّ = 0 ⇒ ABORT_NO_FREE_QTY، بلا وضع.
  - dry_run=True ⇒ DRY_RUN، يعيد الخطّة، بلا وضع.
  - dry_run=False، مركز عارٍ، free>=qty ⇒ PLACED مرّة واحدة فقط، بـ stop_price مضاعف
    tick، و limit_price أدنى من stop_trigger بصرامة، والكمية مُنزَّلة لـ step،
    و client_order_id المُعطى.
  - تأكيد أنّ العميل لا يملك/لا يُستدعى منه أيّ إلغاء (المنفّذ لا يُلغي أبدًا).
"""
import unittest
from decimal import Decimal
from types import SimpleNamespace

from ocobot.domain.guardian_exec import (
    ProtectiveStopClient,
    place_protective_stop,
    plan_protective_stop,
)


def _filters(symbol="ETHUSDT"):
    return SimpleNamespace(
        symbol=symbol,
        tick_size=Decimal("0.01"),
        step_size=Decimal("0.001"),
        min_qty=Decimal("0.001"),
        min_notional=Decimal("10"),
    )


class _FakeClient:
    """عميل محاكاة في الذاكرة: يسجّل الاستدعاءات ولا يلمس الشبكة.

    لا يُعرّف أيّ دالة إلغاء إطلاقًا؛ أيّ محاولة إلغاء من المنفّذ ستفشل.
    """

    def __init__(self, open_orders=None, free="0"):
        self._open_orders = list(open_orders or [])
        self._free = Decimal(str(free))
        self.calls = []
        self.place_calls = []

    def get_open_sell_orders(self, symbol):
        self.calls.append(("get_open_sell_orders", symbol))
        return list(self._open_orders)

    def get_free_asset_qty(self, asset):
        self.calls.append(("get_free_asset_qty", asset))
        return self._free

    def place_stop_loss_limit(self, symbol, quantity, stop_price,
                              limit_price, client_order_id):
        self.calls.append(("place_stop_loss_limit", symbol))
        self.place_calls.append({
            "symbol": symbol,
            "quantity": quantity,
            "stop_price": stop_price,
            "limit_price": limit_price,
            "client_order_id": client_order_id,
        })
        return {"orderId": 4242, "status": "NEW", "clientOrderId": client_order_id}


class TestReconcileDoubleSellGuard(unittest.TestCase):
    def test_resting_sell_present_aborts_and_no_place(self):
        c = _FakeClient(open_orders=[{"orderId": 1}], free="5")
        r = place_protective_stop(
            c, "ETHUSDT", "ETH",
            reference_price=Decimal("100"), qty=Decimal("5"),
            emergency_sl_pct=Decimal("1"), filters=_filters(),
            client_order_id="prot-1", dry_run=False,
        )
        self.assertEqual(r["action"], "ABORT_PROTECTED")
        self.assertFalse(r["placed"])
        self.assertEqual(len(c.place_calls), 0)
        self.assertFalse(
            any(call[0] == "place_stop_loss_limit" for call in c.calls)
        )


class TestFreeBalanceCapping(unittest.TestCase):
    def test_free_less_than_qty_caps_eff_qty(self):
        # رصيد حرّ 2.3456 < qty 5 ⇒ eff_qty=2.3456، مُنزَّلة لـ step=0.001 ⇒ 2.345
        c = _FakeClient(open_orders=[], free="2.3456")
        r = place_protective_stop(
            c, "ETHUSDT", "ETH",
            reference_price=Decimal("100"), qty=Decimal("5"),
            emergency_sl_pct=Decimal("1"), filters=_filters(),
            client_order_id="prot-2", dry_run=True,
        )
        self.assertEqual(r["action"], "DRY_RUN")
        self.assertEqual(r["eff_qty"], Decimal("2.3456"))
        self.assertEqual(r["plan"]["quantity"], Decimal("2.345"))

    def test_zero_free_aborts_no_free_qty(self):
        c = _FakeClient(open_orders=[], free="0")
        r = place_protective_stop(
            c, "ETHUSDT", "ETH",
            reference_price=Decimal("100"), qty=Decimal("5"),
            emergency_sl_pct=Decimal("1"), filters=_filters(),
            client_order_id="prot-3", dry_run=False,
        )
        self.assertEqual(r["action"], "ABORT_NO_FREE_QTY")
        self.assertFalse(r["placed"])
        self.assertEqual(len(c.place_calls), 0)


class TestDryRun(unittest.TestCase):
    def test_dry_run_returns_plan_and_places_nothing(self):
        c = _FakeClient(open_orders=[], free="5")
        r = place_protective_stop(
            c, "ETHUSDT", "ETH",
            reference_price=Decimal("100"), qty=Decimal("5"),
            emergency_sl_pct=Decimal("1"), filters=_filters(),
            client_order_id="prot-4", dry_run=True,
        )
        self.assertEqual(r["action"], "DRY_RUN")
        self.assertFalse(r["placed"])
        self.assertIn("plan", r)
        self.assertEqual(len(c.place_calls), 0)


class TestPlaced(unittest.TestCase):
    def test_naked_places_exactly_once_with_correct_params(self):
        c = _FakeClient(open_orders=[], free="5")
        r = place_protective_stop(
            c, "ETHUSDT", "ETH",
            reference_price=Decimal("100"), qty=Decimal("5"),
            emergency_sl_pct=Decimal("1"), filters=_filters(),
            client_order_id="prot-5", dry_run=False,
        )
        self.assertEqual(r["action"], "PLACED")
        self.assertTrue(r["placed"])
        # وُضع مرّة واحدة فقط
        self.assertEqual(len(c.place_calls), 1)
        pc = c.place_calls[0]

        tick = Decimal("0.01")
        step = Decimal("0.001")
        # stop_trigger = 100 * (1 - 1/100) = 99.00، مضاعف tick
        self.assertEqual(pc["stop_price"], Decimal("99.00"))
        self.assertEqual((pc["stop_price"] % tick), Decimal("0"))
        # limit_price أدنى من stop_trigger بصرامة
        self.assertLess(pc["limit_price"], pc["stop_price"])
        self.assertEqual((pc["limit_price"] % tick), Decimal("0"))
        # الكمية مُنزَّلة لـ step
        self.assertEqual((pc["quantity"] % step), Decimal("0"))
        self.assertEqual(pc["quantity"], Decimal("5"))
        # client_order_id المُعطى
        self.assertEqual(pc["client_order_id"], "prot-5")
        self.assertEqual(r["response"]["clientOrderId"], "prot-5")

    def test_plan_is_pure_and_consistent(self):
        plan = plan_protective_stop(
            Decimal("100"), Decimal("5"), Decimal("1"), _filters()
        )
        self.assertEqual(plan["stop_trigger"], Decimal("99.00"))
        self.assertLess(plan["stop_limit"], plan["stop_trigger"])
        self.assertEqual(plan["type"], "STOP_LOSS_LIMIT")
        self.assertEqual(plan["side"], "SELL")


class TestNeverCancels(unittest.TestCase):
    def test_executor_never_calls_any_cancel(self):
        # العميل المحاكى لا يُعرّف أيّ دالة إلغاء إطلاقًا.
        for name in ("cancel_order", "cancel_oco", "cancel", "delete_order",
                     "cancel_all"):
            self.assertFalse(hasattr(_FakeClient(), name))
        # العقد (Protocol) نفسه لا يُعلن أيّ دالة إلغاء.
        proto_members = set(dir(ProtectiveStopClient))
        for name in ("cancel_order", "cancel_oco", "cancel", "delete_order"):
            self.assertNotIn(name, proto_members)

        # مسار PLACED الكامل: لا استدعاء إلغاء في سجلّ الاستدعاءات.
        c = _FakeClient(open_orders=[], free="5")
        place_protective_stop(
            c, "ETHUSDT", "ETH",
            reference_price=Decimal("100"), qty=Decimal("5"),
            emergency_sl_pct=Decimal("1"), filters=_filters(),
            client_order_id="prot-6", dry_run=False,
        )
        self.assertFalse(
            any("cancel" in call[0].lower() or "delete" in call[0].lower()
                for call in c.calls)
        )


if __name__ == "__main__":
    unittest.main()
