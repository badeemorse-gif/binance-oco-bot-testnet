import unittest
from decimal import Decimal
from types import SimpleNamespace

from ocobot.domain.models import OpenSellOrder
from ocobot.domain.convert import ConvertExecutor
from ocobot.domain.reposition import ExecutionState


def _filters(min_notional="10"):
    return SimpleNamespace(symbol="LSKUSDT", tick_size=Decimal("0.01"),
                           step_size=Decimal("0.001"), min_qty=Decimal("0.001"),
                           min_notional=Decimal(min_notional))

class _FakeExInfo:
    def __init__(self, f): self._f = f
    def get_filters(self, symbol, force_refresh=False): return self._f

class _FakeClient:
    def __init__(self, post_error=None, recheck=None):
        self.calls = []; self._post_error = post_error; self._recheck = recheck or {}
    def signed_request(self, method, path, params=None):
        self.calls.append((method, path))
        if method == "POST" and path == "/api/v3/orderList/oco":
            if self._post_error is not None: raise self._post_error
            return {"orderListId": 999}
        if method == "GET" and path == "/api/v3/orderList": return self._recheck
        return {}
    def cancel_order(self, symbol, orderId=None, origClientOrderId=None):
        self.calls.append(("cancel_order", symbol)); return {}

def _standalone(t="LIMIT"):
    return OpenSellOrder(symbol="LSKUSDT", orderId=123, orderListId=-1, order_type=t,
        side="SELL", price="100", stopPrice="0", trailingDelta="", origQty="1",
        executedQty="0", status="NEW", time=1, is_oco=False, oco_group_id=None, badge=t)

def _oco():
    return OpenSellOrder(symbol="LSKUSDT", orderId=None, orderListId=555, order_type="OCO",
        side="SELL", price="110", stopPrice="90", trailingDelta="", origQty="1",
        executedQty="0", status="NEW", time=1, is_oco=True, oco_group_id=555, badge="OCO")

class TestConvertExecutor(unittest.TestCase):
    def test_standalone_success(self):
        c = _FakeClient(); ex = ConvertExecutor(c, _FakeExInfo(_filters()))
        r = ex.convert(_standalone(), Decimal("4"), Decimal("2"), Decimal("100"))
        self.assertEqual(r.state, ExecutionState.SUCCESS)
        self.assertEqual(r.new_order_list_id, 999)
        self.assertTrue(any(x[0] == "cancel_order" for x in c.calls))
        self.assertTrue(any(x == ("POST", "/api/v3/orderList/oco") for x in c.calls))

    def test_oco_uses_orderlist_cancel(self):
        c = _FakeClient(); ex = ConvertExecutor(c, _FakeExInfo(_filters()))
        r = ex.convert(_oco(), Decimal("4"), Decimal("2"), Decimal("100"))
        self.assertEqual(r.state, ExecutionState.SUCCESS)
        self.assertTrue(any(x == ("DELETE", "/api/v3/orderList") for x in c.calls))
        self.assertFalse(any(x[0] == "cancel_order" for x in c.calls))

    def test_dry_run_no_writes(self):
        c = _FakeClient(); ex = ConvertExecutor(c, _FakeExInfo(_filters()))
        r = ex.convert(_standalone(), Decimal("4"), Decimal("2"), Decimal("100"), dry_run=True)
        self.assertEqual(r.state, ExecutionState.GATE_PASSED)
        self.assertFalse(any(x[0] in ("POST", "DELETE", "cancel_order") for x in c.calls))

    def test_gate_failure_no_cancel(self):
        c = _FakeClient(); ex = ConvertExecutor(c, _FakeExInfo(_filters(min_notional="100000")))
        r = ex.convert(_standalone(), Decimal("4"), Decimal("2"), Decimal("100"))
        self.assertEqual(r.state, ExecutionState.ABORTED)
        self.assertFalse(any(x[0] in ("POST", "DELETE", "cancel_order") for x in c.calls))

    def test_cancel_failure_no_create(self):
        c = _FakeClient()
        def boom(*a, **k): raise RuntimeError("cancel failed")
        c.cancel_order = boom
        ex = ConvertExecutor(c, _FakeExInfo(_filters()))
        r = ex.convert(_standalone(), Decimal("4"), Decimal("2"), Decimal("100"))
        self.assertEqual(r.state, ExecutionState.ABORTED)
        self.assertFalse(any(x[0] == "POST" for x in c.calls))

    def test_create_lost_recheck_success(self):
        c = _FakeClient(post_error=RuntimeError("lost"), recheck={"orderListId": 777})
        ex = ConvertExecutor(c, _FakeExInfo(_filters()))
        r = ex.convert(_standalone(), Decimal("4"), Decimal("2"), Decimal("100"))
        self.assertEqual(r.state, ExecutionState.SUCCESS)
        self.assertEqual(r.new_order_list_id, 777)

    def test_create_failed_needs_attention(self):
        c = _FakeClient(post_error=RuntimeError("rejected"), recheck={})
        ex = ConvertExecutor(c, _FakeExInfo(_filters()))
        r = ex.convert(_standalone(), Decimal("4"), Decimal("2"), Decimal("100"))
        self.assertEqual(r.state, ExecutionState.FAILED_NEEDS_ATTENTION)
        self.assertIsNone(r.new_order_list_id)

if __name__ == "__main__":
    unittest.main()
