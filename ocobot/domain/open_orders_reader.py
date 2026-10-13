"""G1.13: قراءة كل أوامر البيع (LIMIT/STOP/TRAILING/OCO) في قائمة واحدة.
GET /api/v3/openOrders يعيد كل الأوامر المفتوحة بما فيها سيقان OCO.
orderListId == -1 => أمر مستقل ؛ > 0 => ساق OCO. سيقان OCO ذات نفس
orderListId تُدمج في صفّ واحد (ساقا OCO للبيع تتشاركان نفس الكمية)."""
from ocobot.domain.models import OpenSellOrder

_ABOVE_TYPES = {"LIMIT_MAKER", "TAKE_PROFIT", "TAKE_PROFIT_LIMIT", "LIMIT"}
_BELOW_TYPES = {"STOP_LOSS", "STOP_LOSS_LIMIT"}

def _merge_oco_group(order_list_id: int, legs: list) -> OpenSellOrder:
    first = legs[0]
    above = next((l for l in legs if str(l.get("type", "")).upper() in _ABOVE_TYPES), None)
    below = next((l for l in legs if str(l.get("type", "")).upper() in _BELOW_TYPES), None)
    return OpenSellOrder(
        symbol=str(first.get("symbol", "")),
        orderId=None,
        orderListId=order_list_id,
        order_type="OCO",
        side="SELL",
        price=str((above or first).get("price", "0")),
        stopPrice=str((below or first).get("stopPrice", "0")),
        trailingDelta="",
        origQty=str(first.get("origQty", "0")),      # ساقا OCO تتشاركان الكمية
        executedQty=str(first.get("executedQty", "0")),
        status=str(first.get("status", "")),
        time=first.get("time"),
        is_oco=True,
        oco_group_id=order_list_id,
        badge="OCO",
    )

def read_all_open_sell_orders(rest_client) -> list:
    raw_orders = rest_client.get_open_orders() or []
    sells = [o for o in raw_orders if str(o.get("side", "")).upper() == "SELL"]
    rows, oco_groups = [], {}
    for o in sells:
        olid = int(o.get("orderListId", -1))
        if olid == -1:
            rows.append(OpenSellOrder.from_raw(o))
        else:
            oco_groups.setdefault(olid, []).append(o)
    for olid, legs in oco_groups.items():
        rows.append(_merge_oco_group(olid, legs))
    return rows
