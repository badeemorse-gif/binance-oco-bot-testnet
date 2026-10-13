"""G1.13: طبقة الاختيار — تطبيع أمر بيع مستقل (غير OCO) إلى \"مرشّح تحويل\".

لا شبكة: عميل/قارئ/exchangeInfo كلّها fakes في الذاكرة.
ملاحظة: get_open_orders يُعيد dicts خام تمامًا كـ rest_client الحقيقي؛
read_all_open_sell_orders يستهلك dicts عبر .get()، لذا الـfake يُغذّي dicts،
وما يُمرّر لـ select_from_row كائن OpenSellOrder (عبر from_raw لنفس الـdict).
"""
import unittest
from decimal import Decimal
from types import SimpleNamespace

from ocobot.domain.models import OpenSellOrder, SelectedOCO
from ocobot.domain.selection import Selector


def _standalone(order_id=123, order_type="LIMIT", trailing_delta="", symbol="LSKUSDT"):
    """أمر بيع مستقل كـ dict خام (orderListId=-1)."""
    return {
        "symbol": symbol,
        "orderId": order_id,
        "orderListId": -1,
        "type": order_type,
        "side": "SELL",
        "price": "100",
        "stopPrice": "0",
        "trailingDelta": trailing_delta,
        "origQty": "1.5",
        "executedQty": "0.4",
        "status": "NEW",
        "time": 1,
    }


def _oco_legs_raw(order_list_id=555, symbol="LSKUSDT"):
    """ساقا OCO للبيع كـ dicts خام تتشاركان orderListId الموجب."""
    return [
        {
            "symbol": symbol, "orderId": order_list_id * 10 + 1,
            "orderListId": order_list_id, "type": "LIMIT_MAKER", "side": "SELL",
            "price": "110", "stopPrice": "0", "trailingDelta": "",
            "origQty": "1", "executedQty": "0", "status": "NEW", "time": 1,
        },
        {
            "symbol": symbol, "orderId": order_list_id * 10 + 2,
            "orderListId": order_list_id, "type": "STOP_LOSS_LIMIT", "side": "SELL",
            "price": "89", "stopPrice": "90", "trailingDelta": "",
            "origQty": "1", "executedQty": "0", "status": "NEW", "time": 1,
        },
    ]


def _oco_order_obj(order_list_id=42, symbol="LSKUSDT"):
    """صفّ OCO مدموج ككائن OpenSellOrder (لتمريره إلى select_from_row)."""
    return OpenSellOrder(
        symbol=symbol, orderId=None, orderListId=order_list_id, order_type="OCO",
        side="SELL", price="110", stopPrice="90", trailingDelta="", origQty="1",
        executedQty="0", status="NEW", time=1, is_oco=True,
        oco_group_id=order_list_id, badge="OCO",
    )


def _filters(symbol="LSKUSDT"):
    return SimpleNamespace(
        symbol=symbol, tick_size=Decimal("0.01"), step_size=Decimal("0.001"),
        min_qty=Decimal("0.001"), min_notional=Decimal("10"),
    )


class _FakeClient:
    """عميل في الذاكرة: get_open_orders يُعيد dicts خام (لا شبكة)."""

    def __init__(self, open_orders):
        self._open_orders = open_orders

    def get_open_orders(self, symbol=None):
        return self._open_orders


class _FakeReader:
    """OcoReader مزيّف: يحمل العميل الموقّع ويعيد OCO حقيقيًا للـ select."""

    def __init__(self, client, oco=None):
        self._client = client
        self._oco = oco or SimpleNamespace(
            order_list_id=31, symbol="LSKUSDT", quantity=Decimal("0.5"),
            tp_price=Decimal("70000"), stop_trigger=Decimal("58500"),
            stop_limit=Decimal("58000"), leg_ids=[11, 12], status="EXECUTING",
        )

    def get_oco(self, order_list_id):
        self._oco.order_list_id = order_list_id
        return self._oco


class _FakeExInfo:
    def __init__(self, filters):
        self._filters = filters

    def get_filters(self, symbol, force_refresh=False):
        return self._filters


def _selector(open_orders):
    client = _FakeClient(open_orders)
    return Selector(_FakeReader(client), _FakeExInfo(_filters()))


class TestSelectionG1_13(unittest.TestCase):
    def test_standalone_limit_becomes_convert_candidate(self):
        order = _standalone(order_id=123, order_type="LIMIT")
        selector = _selector([order])
        sel = selector.select_open_order(123)
        self.assertIsInstance(sel, SelectedOCO)
        self.assertTrue(sel.is_convert_candidate)
        self.assertEqual(sel.quantity, Decimal("1.1"))
        self.assertTrue(sel.quantity_locked)
        self.assertIsNone(sel.tp)
        self.assertIsNone(sel.stop_trigger)
        self.assertIsNone(sel.stop_limit)
        self.assertIsNone(sel.order_list_id)
        self.assertEqual(sel.source_order_type, "LIMIT")
        self.assertEqual(sel.source_order_id, 123)
        self.assertEqual(sel.leg_ids, [123])
        self.assertIsNone(sel.current_price)
        self.assertIs(selector.selected, sel)

    def test_trailing_standalone_preserves_trailing_delta(self):
        order = _standalone(order_id=200, order_type="STOP_LOSS_LIMIT",
                            trailing_delta="150")
        selector = _selector([order])
        sel = selector.select_open_order(200)
        self.assertTrue(sel.is_convert_candidate)
        self.assertIsNotNone(sel.trailing_delta)
        self.assertGreater(sel.trailing_delta, 0)
        self.assertEqual(sel.trailing_delta, 150)

    def test_select_open_order_not_found_raises(self):
        selector = _selector([_standalone(order_id=1)])
        with self.assertRaises(ValueError):
            selector.select_open_order(99999)

    def test_select_open_order_ignores_oco_rows(self):
        selector = _selector(_oco_legs_raw(order_list_id=555))
        with self.assertRaises(ValueError):
            selector.select_open_order(555)

    def test_regression_select_oco_is_normal_selection(self):
        selector = _selector([])
        sel = selector.select(31)
        self.assertFalse(sel.is_convert_candidate)
        self.assertIsNotNone(sel.order_list_id)
        self.assertEqual(sel.order_list_id, 31)
        self.assertEqual(sel.tp, Decimal("70000"))
        self.assertEqual(sel.stop_trigger, Decimal("58500"))
        self.assertEqual(sel.quantity, Decimal("0.5"))

    def test_select_from_row_dispatches_oco(self):
        selector = _selector([])
        row = _oco_order_obj(order_list_id=42)
        sel = selector.select_from_row(row)
        self.assertFalse(sel.is_convert_candidate)
        self.assertEqual(sel.order_list_id, 42)

    def test_select_from_row_dispatches_standalone(self):
        raw = _standalone(order_id=777, order_type="LIMIT")
        selector = _selector([raw])
        order_obj = OpenSellOrder.from_raw(raw)
        sel = selector.select_from_row(order_obj)
        self.assertTrue(sel.is_convert_candidate)
        self.assertEqual(sel.source_order_id, 777)
        self.assertIsNone(sel.order_list_id)


if __name__ == "__main__":
    unittest.main()
