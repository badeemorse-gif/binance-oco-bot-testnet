"""محوّل عميل الخروج بالسعر (Market Exit Broker Adapter) — G1.32b.

يوسّع ``GuardianBroker`` (قراءة أوامر البيع الحمائية + الرصيد الحرّ + وضع
``STOP_LOSS_LIMIT``) بما يحتاجه منفّذ الخروج G1.32a إضافةً:
  - ``cancel_oco``: إلغاء OCO قائم (``DELETE /api/v3/orderList``) لتحرير الرصيد.
  - ``place_limit_sell``: أمر ``LIMIT`` SELL (الخروج العلوي marketable).
  - ``place_market_sell``: أمر ``MARKET`` SELL (خيار متقدّم صريح فقط).

كلّها عبر ``signed_request`` لعميل REST الموجود دون أيّ تعديل له. إضافيّ بحت وخارج
المسار الحار؛ قابل للاختبار بمحاكاة عميل REST بلا شبكة.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict

from ocobot.core.guardian_broker import GuardianBroker
from ocobot.domain.models import fmt

PATH_ORDERLIST = "/api/v3/orderList"


def _dec(value) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value or 0))


class MarketExitBroker(GuardianBroker):
    """محوّل ملموس يحقّق عقد ``MarketExitClient`` فوق عميل REST موجود."""

    PATH_ORDERLIST = PATH_ORDERLIST

    def cancel_oco(self, symbol: str, order_list_id: int) -> Dict[str, Any]:
        params = [("symbol", symbol), ("orderListId", order_list_id)]
        return self._client.signed_request("DELETE", self.PATH_ORDERLIST, params)

    def place_limit_sell(self, symbol: str, quantity: Decimal, price: Decimal,
                         client_order_id: str) -> Dict[str, Any]:
        params = [
            ("symbol", symbol),
            ("side", "SELL"),
            ("type", "LIMIT"),
            ("timeInForce", "GTC"),
            ("quantity", fmt(_dec(quantity))),
            ("price", fmt(_dec(price))),
            ("newClientOrderId", client_order_id),
        ]
        return self._client.signed_request("POST", self.PATH_ORDER, params)

    def place_limit_sell_ioc(self, symbol: str, quantity: Decimal, price: Decimal,
                             client_order_id: str) -> Dict[str, Any]:
        # G1.49: LIMIT SELL بـ timeInForce=IOC (نفِّذ-أو-ألغِ) — ركيزة الـchase الموحّد:
        # ينفّذ فورًا ما أمكن عند/تحت أفضل BID ويُلغى الباقي (لا أمر راقد ⇒ لا تعليق
        # ولا بيع مزدوج). الردّ يحوي executedQty/status لقياس المنفَّذ.
        params = [
            ("symbol", symbol),
            ("side", "SELL"),
            ("type", "LIMIT"),
            ("timeInForce", "IOC"),
            ("quantity", fmt(_dec(quantity))),
            ("price", fmt(_dec(price))),
            ("newClientOrderId", client_order_id),
        ]
        return self._client.signed_request("POST", self.PATH_ORDER, params)

    def place_market_sell(self, symbol: str, quantity: Decimal,
                          client_order_id: str) -> Dict[str, Any]:
        params = [
            ("symbol", symbol),
            ("side", "SELL"),
            ("type", "MARKET"),
            ("quantity", fmt(_dec(quantity))),
            ("newClientOrderId", client_order_id),
        ]
        return self._client.signed_request("POST", self.PATH_ORDER, params)
