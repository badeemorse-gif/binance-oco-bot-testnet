"""OCO Reader — جلب الأوامر المفتوحة الحقيقية + تفاصيل OCO المحدد (Deliverable 2).

قراءة فقط (P2/P3): كل النداءات GET موقّعة.
  - GET /api/v3/openOrderList              → قوائم OCO المفتوحة (weight 3)
  - GET /api/v3/orderList?orderListId=     → إعادة التحقق من هوية OCO محدد (P1)
  - GET /api/v3/order?symbol=&orderId=     → تفاصيل الرِّجل (السعر/التريجر/الكمية)

المزج: رِجلان لكن 3 أسعار (D1). التصنيف بالاعتماد على stopPrice (symbol/side-agnostic).
"""
from __future__ import annotations

from decimal import Decimal
from typing import List, Optional

from ocobot.core.errors import OcoBotError
from ocobot.domain.models import OcoLeg, OcoOrder

PATH_OPEN_ORDER_LIST = "/api/v3/openOrderList"
PATH_ORDER_LIST = "/api/v3/orderList"
PATH_ORDER = "/api/v3/order"


class OcoReader:
    def __init__(self, client):
        self._client = client

    # ---- public API ----
    def list_open_ocos(self) -> List[OcoOrder]:
        lists = self._client.signed_request("GET", PATH_OPEN_ORDER_LIST) or []
        return [self._build_oco_order(obj) for obj in lists]

    def get_oco(self, order_list_id: int) -> OcoOrder:
        """إعادة التحقق من هوية OCO واحد بالـ orderListId (P1)."""
        obj = self._client.signed_request(
            "GET", PATH_ORDER_LIST, [("orderListId", int(order_list_id))]
        )
        if not obj or "orderListId" not in obj:
            raise OcoBotError(f"لم يُعثر على OCO بالمعرّف orderListId={order_list_id}.")
        return self._build_oco_order(obj)

    # ---- internals ----
    def _fetch_leg(self, symbol: str, order_id: int) -> OcoLeg:
        obj = self._client.signed_request(
            "GET", PATH_ORDER, [("symbol", symbol), ("orderId", int(order_id))]
        )
        return OcoLeg.from_api(obj)

    def _build_oco_order(self, list_obj: dict) -> OcoOrder:
        symbol = str(list_obj.get("symbol", ""))
        order_list_id = int(list_obj.get("orderListId"))
        leg_refs = list_obj.get("orders", []) or []

        legs: List[OcoLeg] = []
        for ref in leg_refs:
            oid = int(ref.get("orderId"))
            # إن كانت التفاصيل مضمّنة (price/type) استُخدمت مباشرة، وإلا استعلام مفصّل
            if any(k in ref for k in ("price", "type", "origQty", "stopPrice")):
                leg = OcoLeg.from_api(ref)
            else:
                leg = self._fetch_leg(symbol, oid)
            legs.append(leg)

        stop_leg = next((lg for lg in legs if lg.is_stop_leg()), None)
        tp_leg = next((lg for lg in legs if lg is not stop_leg), None)

        quantity = self._pick_quantity(legs)
        executed = max(
            [lg.executed_qty or Decimal("0") for lg in legs], default=Decimal("0")
        )

        return OcoOrder(
            order_list_id=order_list_id,
            symbol=symbol,
            status=str(list_obj.get("listOrderStatus", "")),
            list_status_type=str(list_obj.get("listStatusType", "")),
            quantity=quantity,
            tp_price=(tp_leg.price if tp_leg else None),
            stop_trigger=(stop_leg.stop_price if stop_leg else None),
            stop_limit=(stop_leg.price if stop_leg else None),
            leg_ids=[lg.order_id for lg in legs],
            executed_qty=executed,
            legs=legs,
        )

    @staticmethod
    def _pick_quantity(legs: List[OcoLeg]) -> Optional[Decimal]:
        qtys = [lg.orig_qty for lg in legs if lg.orig_qty is not None]
        return max(qtys) if qtys else None
