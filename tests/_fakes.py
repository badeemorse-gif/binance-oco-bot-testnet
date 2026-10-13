"""Shared in-memory fakes for domain tests (no network)."""
from __future__ import annotations

from ocobot.core.errors import TransportError
from ocobot.core.environment import Environment


def list_obj(order_list_id=31, symbol="BTCUSDT"):
    return {
        "orderListId": order_list_id,
        "symbol": symbol,
        "listStatusType": "EXEC_STARTED",
        "listOrderStatus": "EXECUTING",
        "orders": [{"orderId": 11}, {"orderId": 12}],
    }


def leg(order_id, orig_qty="0.5", executed_qty="0"):
    if order_id == 11:  # TP leg (above): LIMIT_MAKER, no stopPrice
        return {
            "orderId": 11, "symbol": "BTCUSDT", "side": "SELL", "type": "LIMIT_MAKER",
            "price": "70000.00", "stopPrice": "0.00", "origQty": orig_qty,
            "executedQty": executed_qty, "status": "NEW", "clientOrderId": "tp",
        }
    return {  # STOP leg (below): STOP_LOSS_LIMIT with stopPrice (trigger) + price (limit)
        "orderId": 12, "symbol": "BTCUSDT", "side": "SELL", "type": "STOP_LOSS_LIMIT",
        "price": "58000.00", "stopPrice": "58500.00", "origQty": orig_qty,
        "executedQty": executed_qty, "status": "NEW", "clientOrderId": "sl",
    }


SYMBOL_OBJ = {
    "symbol": "BTCUSDT",
    "filters": [
        {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
        {"filterType": "LOT_SIZE", "stepSize": "0.0001", "minQty": "0.001"},
        {"filterType": "NOTIONAL", "minNotional": "10"},
    ],
}


class FakeClient:
    """Implements signed_request + public_request used by domain code.

    Backward-compatible: no-arg construction, ``self.calls`` stays a list of
    ``(path, params_dict)`` tuples (existing tests inspect it that way). M2 adds
    method-aware ``self.write_calls`` = list of ``(method, path, params_dict)`` and
    optional order-list write/idempotency behaviour via constructor kwargs.
    """

    def __init__(
        self,
        new_order_list_id=99,
        create_error=None,
        create_transport_error=False,
        cancel_error=None,
        exists_on_recheck=True,
        recheck_id=99,
        orig_qty="0.5",
        executed_qty="0",
    ):
        self.calls = []
        self.write_calls = []
        self.new_order_list_id = new_order_list_id
        self.create_error = create_error
        self.create_transport_error = create_transport_error
        self.cancel_error = cancel_error
        self.exists_on_recheck = exists_on_recheck
        self.recheck_id = recheck_id
        self.orig_qty = orig_qty
        self.executed_qty = executed_qty

    def signed_request(self, method, path, params=None):
        p = dict(params or [])
        # الشكل التاريخي محفوظ (path, params) كي تبقى الاختبارات القديمة تعمل
        self.calls.append((path, p))
        # تسجيل واعٍ بالـ method لتأكيدات M2 (ترتيب DELETE قبل POST … إلخ)
        self.write_calls.append((method, path, dict(params or [])))

        if path == "/api/v3/openOrderList":
            return [list_obj()]
        if path == "/api/v3/orderList" and method != "DELETE":
            if "listClientOrderId" in p:  # D10: recheck-before-retry
                return {
                    "orderListId": self.recheck_id if self.exists_on_recheck else -1,
                    "listClientOrderId": p["listClientOrderId"],
                }
            return list_obj(order_list_id=int(p["orderListId"]))
        # الشكل التاريخي (بدون method) لا يزال مدعومًا للاختبارات القديمة
        if path == "/api/v3/order":
            return leg(int(p["orderId"]), self.orig_qty, self.executed_qty)
        if method == "DELETE" and path == "/api/v3/orderList":
            if self.cancel_error:  # فشل الإلغاء / الأمر مفقود → ABORTED (D9)
                raise self.cancel_error
            return {"orderListId": int(p["orderListId"]), "listOrderStatus": "ALL_DONE"}
        if method == "POST" and path == "/api/v3/orderList/oco":
            if self.create_transport_error:  # ردّ ضائع → recheck واحد (D10)
                raise TransportError("lost")
            if self.create_error:  # فشل الإنشاء → FAILED_NEEDS_ATTENTION (D9)
                raise self.create_error
            return {
                "orderListId": self.new_order_list_id,
                "listClientOrderId": p.get("listClientOrderId"),
                "symbol": p.get("symbol"),
                "listOrderStatus": "EXECUTING",
            }
        raise AssertionError(f"unexpected signed path: {method} {path}")

    def cancel_calls(self):
        return [w for w in self.write_calls if w[0] == "DELETE"]

    def create_calls(self):
        return [w for w in self.write_calls if w[1] == "/api/v3/orderList/oco"]

    def recheck_calls(self):
        return [
            w for w in self.write_calls
            if w[0] == "GET" and w[1] == "/api/v3/orderList" and "listClientOrderId" in w[2]
        ]

    def public_request(self, method, path, params=None):
        self.calls.append((path, dict(params or [])))
        if path == "/api/v3/exchangeInfo":
            return {"symbols": [SYMBOL_OBJ]}
        raise AssertionError(f"unexpected public path: {path}")


# --- G1.15: fakes خفيفة لاختبارات واجهة الاتصال/الأوامر المفتوحة (بلا شبكة) ---

class FakeResult:
    def __init__(self, ok=True):
        self.ok = ok


class FakeOpenOrdersScreen:
    def __init__(self):
        self.refresh_called = 0

    def refresh(self, build_fn=None):
        self.refresh_called += 1


class FakeContent:
    def __init__(self, screens=None):
        self._screens = screens or {}

    def screen_for(self, key):
        return self._screens.get(key)


class FakeWindow:
    def __init__(self, connection_notifier, content):
        self.connection_notifier = connection_notifier
        self.content = content


class FakeCfg:
    def __init__(self, env=None, rest_base="https://testnet.binance.vision"):
        self.env = env if env is not None else Environment.TESTNET
        self._rest_base = rest_base

    def rest_base(self):
        return self._rest_base
