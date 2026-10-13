"""اختبارات G1.30 (chunk_4) — محوّل عميل الوساطة (core/guardian_broker.py).

تُختبر بمحاكاة عميل REST في الذاكرة (بلا شبكة): كشف البيع الحمائي القائم، قراءة
الرصيد الحرّ، ووضع STOP_LOSS_LIMIT واحد عبر signed_request الموجود. تأكيد صريح
على غياب أيّ إلغاء.
"""
import unittest
from decimal import Decimal

from ocobot.core.guardian_broker import GuardianBroker, base_asset_of


class _FakeRest:
    """عميل REST محاكى: get_open_orders + get_account + signed_request فقط."""

    def __init__(self, open_orders=None, account=None):
        self._open_orders = list(open_orders or [])
        self._account = account or {"balances": []}
        self.signed_calls = []

    def get_open_orders(self, symbol=None):
        return list(self._open_orders)

    def get_account(self):
        return dict(self._account)

    def signed_request(self, method, path, params=None):
        self.signed_calls.append((method, path, dict(params or [])))
        return {"orderId": 777, "status": "NEW"}


class TestOpenSellOrdersDetection(unittest.TestCase):
    def test_detects_standalone_stop_and_oco_leg_only(self):
        orders = [
            {"symbol": "ETHUSDT", "side": "SELL", "type": "STOP_LOSS_LIMIT", "orderListId": -1},
            {"symbol": "ETHUSDT", "side": "SELL", "type": "LIMIT_MAKER", "orderListId": 50},  # رِجل OCO
            {"symbol": "ETHUSDT", "side": "SELL", "type": "LIMIT", "orderListId": -1},         # LIMIT بيع عادي (غير حمائي سفلي)
            {"symbol": "ETHUSDT", "side": "BUY", "type": "STOP_LOSS_LIMIT", "orderListId": -1}, # شراء ⇒ يُستبعد
            {"symbol": "BTCUSDT", "side": "SELL", "type": "STOP_LOSS_LIMIT", "orderListId": -1},# رمز آخر ⇒ يُستبعد
        ]
        broker = GuardianBroker(_FakeRest(open_orders=orders))
        protective = broker.get_open_sell_orders("ETHUSDT")
        # يُتوقَّع: الوقف المستقل + رِجل OCO = 2 (الرمز الصحيح فقط).
        types = sorted(o.get("type") for o in protective)
        self.assertEqual(len(protective), 2)
        self.assertIn("STOP_LOSS_LIMIT", types)
        self.assertIn("LIMIT_MAKER", types)

    def test_no_protective_returns_empty(self):
        orders = [
            {"symbol": "ETHUSDT", "side": "SELL", "type": "LIMIT", "orderListId": -1},
            {"symbol": "ETHUSDT", "side": "BUY", "type": "STOP_LOSS_LIMIT", "orderListId": -1},
        ]
        broker = GuardianBroker(_FakeRest(open_orders=orders))
        self.assertEqual(broker.get_open_sell_orders("ETHUSDT"), [])


class TestFreeAssetQty(unittest.TestCase):
    def test_reads_free_balance(self):
        account = {"balances": [
            {"asset": "ETH", "free": "2.5", "locked": "1.0"},
            {"asset": "USDT", "free": "100", "locked": "0"},
        ]}
        broker = GuardianBroker(_FakeRest(account=account))
        self.assertEqual(broker.get_free_asset_qty("ETH"), Decimal("2.5"))

    def test_missing_asset_returns_zero(self):
        broker = GuardianBroker(_FakeRest(account={"balances": []}))
        self.assertEqual(broker.get_free_asset_qty("ETH"), Decimal("0"))

    def test_empty_asset_returns_zero(self):
        broker = GuardianBroker(_FakeRest())
        self.assertEqual(broker.get_free_asset_qty(""), Decimal("0"))


class TestPlaceStopLossLimit(unittest.TestCase):
    def test_places_single_order_via_signed_request(self):
        rest = _FakeRest()
        broker = GuardianBroker(rest)
        resp = broker.place_stop_loss_limit(
            symbol="ETHUSDT",
            quantity=Decimal("5"),
            stop_price=Decimal("99.00"),
            limit_price=Decimal("98.99"),
            client_order_id="grd-1",
        )
        self.assertEqual(resp["orderId"], 777)
        # استدعاء واحد فقط، POST /api/v3/order، نوع STOP_LOSS_LIMIT.
        self.assertEqual(len(rest.signed_calls), 1)
        method, path, params = rest.signed_calls[0]
        self.assertEqual(method, "POST")
        self.assertEqual(path, "/api/v3/order")
        self.assertEqual(params["type"], "STOP_LOSS_LIMIT")
        self.assertEqual(params["side"], "SELL")
        self.assertEqual(params["newClientOrderId"], "grd-1")


class TestNeverCancels(unittest.TestCase):
    def test_broker_defines_no_cancel_methods(self):
        broker = GuardianBroker(_FakeRest())
        for name in ("cancel_order", "cancel_oco", "cancel", "delete_order", "cancel_all"):
            self.assertFalse(hasattr(broker, name))

    def test_place_path_does_not_issue_any_delete(self):
        rest = _FakeRest()
        broker = GuardianBroker(rest)
        broker.place_stop_loss_limit("ETHUSDT", Decimal("5"), Decimal("99"),
                                     Decimal("98.99"), "grd-2")
        self.assertFalse(any(m == "DELETE" for (m, _p, _q) in rest.signed_calls))


class TestBaseAssetOf(unittest.TestCase):
    def test_suffix_strip_fallback(self):
        self.assertEqual(base_asset_of("ETHUSDT"), "ETH")
        self.assertEqual(base_asset_of("BTCUSDT"), "BTC")
        self.assertEqual(base_asset_of("ETHBTC"), "ETH")

    def test_unknown_returns_none(self):
        self.assertIsNone(base_asset_of(""))
        self.assertIsNone(base_asset_of("XYZ"))

    def test_exchange_info_preferred(self):
        class _XI:
            def get_symbol(self, sym):
                return {"baseAsset": "FOO"}
        self.assertEqual(base_asset_of("FOOUSDT", exchange_info=_XI()), "FOO")


if __name__ == "__main__":
    unittest.main()
