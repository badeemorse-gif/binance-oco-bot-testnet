"""Selection context + read-only Dashboard (Deliverable 3.1/3.3, Deliverable 9).

- Selector: يختار OCO واحدًا بالـ orderListId ⇒ يؤسّس Live context (SelectedOCO)
  ويقرأ الفلاتر من exchangeInfo (P1؛ D8). لا يمسّ أي أمر آخر (P3) — قراءة فقط.
- DashboardSnapshot: بطاقات لوحة القيادة (قراءة فقط). قبل الاختيار كلها '—'.
  Current Price يبقى '—' حتى Market WS (T4) — لا Preview وهمي (D14).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ocobot.domain.exchange_info import ExchangeInfoService
from ocobot.domain.models import OpenSellOrder, SelectedOCO, fmt
from ocobot.domain.oco_reader import OcoReader
from ocobot.domain.open_orders_reader import read_all_open_sell_orders

DASH = "—"


class Selector:
    def __init__(self, reader: OcoReader, exchange_info: ExchangeInfoService):
        self._reader = reader
        self._exchange_info = exchange_info
        self._selected: Optional[SelectedOCO] = None

    @property
    def selected(self) -> Optional[SelectedOCO]:
        return self._selected

    def select(self, order_list_id: int) -> SelectedOCO:
        # P1: أعِد التحقق من هوية الأمر بالـ orderListId قبل تأسيس السياق
        oco = self._reader.get_oco(order_list_id)
        filters = self._exchange_info.get_filters(oco.symbol)  # D8: من exchangeInfo
        self._selected = SelectedOCO.from_oco(oco, filters=filters)
        return self._selected

    def select_open_order(self, order_id: int) -> SelectedOCO:
        """G1.13: يختار أمر بيع مستقل غير OCO ويطبّعه إلى "مرشّح تحويل".

        يُعاد استخدام العميل الموقّع الذي يحمله OcoReader (قراءة فقط). الكمية
        موروثة ومقفولة (D7)؛ لا تُحسَب أيّ أسعار TP/SL هنا (تأتي لاحقًا وقت
        التحويل من السعر الحيّ + النِّسب — D6/D14/D-G1.13-refprice).
        """
        client = getattr(self._reader, "_client", None)
        orders = read_all_open_sell_orders(client)
        order = next(
            (
                o
                for o in orders
                if (not o.is_oco) and o.orderId == order_id
            ),
            None,
        )
        if order is None:
            raise ValueError(
                f"لم يُعثر على أمر بيع مستقل بالمعرّف orderId={order_id}."
            )
        filters = self._exchange_info.get_filters(order.symbol)  # D8
        self._selected = SelectedOCO.from_open_sell_order(order, filters=filters)
        return self._selected

    def select_from_row(self, order: OpenSellOrder) -> SelectedOCO:
        """موزِّع يختار بحسب نوع الصف: OCO ⇒ select؛ وإلا ⇒ select_open_order."""
        if order.is_oco:
            return self.select(order.orderListId)
        return self.select_open_order(order.orderId)

    def clear(self) -> None:
        self._selected = None


@dataclass
class DashboardSnapshot:
    selected_oco: str = DASH
    symbol: str = DASH
    current_price: str = DASH       # يبقى '—' حتى Market WS (T4) — D14
    current_tp: str = DASH
    current_sl: str = DASH
    reference_price: str = DASH     # monitoring — T4
    next_trigger: str = DASH        # monitoring — T4
    monitoring_state: str = "IDLE"
    connection: str = DASH
    last_reposition: str = DASH
    environment: str = DASH

    def to_dict(self) -> dict:
        return {
            "selectedOco": self.selected_oco,
            "symbol": self.symbol,
            "currentPrice": self.current_price,
            "currentTp": self.current_tp,
            "currentSl": self.current_sl,
            "referencePrice": self.reference_price,
            "nextTrigger": self.next_trigger,
            "monitoringState": self.monitoring_state,
            "connection": self.connection,
            "lastReposition": self.last_reposition,
            "environment": self.environment,
        }


def build_dashboard(
    selected: Optional[SelectedOCO],
    environment: str = DASH,
    connection: str = DASH,
) -> DashboardSnapshot:
    snap = DashboardSnapshot(environment=environment, connection=connection)
    if selected is None:
        return snap  # كل الحقول '—' + "لم يُختَر أمر"
    # G1.13: مرشّح التحويل (أمر مستقل) ليس له orderListId بعد — عرض تلميح بدل None.
    if getattr(selected, "is_convert_candidate", False) or selected.order_list_id is None:
        snap.selected_oco = "سيُحوَّل إلى OCO"
    else:
        snap.selected_oco = str(selected.order_list_id)
    snap.symbol = selected.symbol
    snap.current_tp = fmt(selected.tp)
    snap.current_sl = fmt(selected.stop_trigger)
    snap.current_price = fmt(selected.current_price)  # '—' في M1
    return snap


def apply_monitoring(snap: DashboardSnapshot, monitoring_state) -> DashboardSnapshot:
    """يدمج حالة المراقبة الحيّة (M3) في لوحة القيادة (قراءة فقط)."""
    if monitoring_state is None:
        return snap
    d = monitoring_state.to_dict()
    snap.monitoring_state = d["state"]
    snap.reference_price = d["referencePrice"]
    ref = monitoring_state.reference_price
    trig = monitoring_state.trigger_pct
    if ref is not None and trig is not None:
        from decimal import Decimal
        activation = ref * (Decimal("1") + trig / Decimal("100"))
        snap.next_trigger = fmt(activation)
    if d.get("lastReposition"):
        lr = d["lastReposition"]
        snap.last_reposition = f"#{lr.get('cursor')} -> OCO {lr.get('newOrderListId')}"
    return snap
