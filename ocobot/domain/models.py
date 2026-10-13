"""Domain models for Read & Select (Deliverable 9 entities, M1 subset).

- SymbolFilters: قيم الفلاتر المقروءة من exchangeInfo (D8 — لا hardcode).
- OcoLeg: رِجل واحدة من قائمة OCO (تفاصيل الأمر الفعلية).
- OcoOrder: تمثيل OCO كامل (رِجلان لكن 3 أسعار — D1) لصف الجدول والتفاصيل.
- SelectedOCO: هوية الهدف المحدد (P1) + الكمية المقفولة (Read-only، D7).

القيم السعرية/الكمية تُخزَّن Decimal للدقة المالية.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import List, Optional


def _dec(value) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def fmt(value: Optional[Decimal]) -> str:
    """عرض بشري للأرقام: يزيل الأصفار الزائدة، و'—' عند الغياب."""
    if value is None:
        return "—"
    if isinstance(value, Decimal):
        normalized = value.normalize()
        # تجنّب الصيغة الأُسّية (E+) للأعداد الصحيحة الكبيرة
        text = format(normalized, "f")
        return text
    return str(value)


@dataclass
class SymbolFilters:
    symbol: str
    tick_size: Optional[Decimal] = None      # PRICE_FILTER
    step_size: Optional[Decimal] = None      # LOT_SIZE
    min_qty: Optional[Decimal] = None        # LOT_SIZE
    min_notional: Optional[Decimal] = None   # NOTIONAL / MIN_NOTIONAL
    updated_at: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "tickSize": fmt(self.tick_size),
            "stepSize": fmt(self.step_size),
            "minQty": fmt(self.min_qty),
            "minNotional": fmt(self.min_notional),
            "updatedAt": self.updated_at,
        }


@dataclass
class OcoLeg:
    order_id: int
    client_order_id: str = ""
    side: str = ""
    type: str = ""
    price: Optional[Decimal] = None
    stop_price: Optional[Decimal] = None
    orig_qty: Optional[Decimal] = None
    executed_qty: Optional[Decimal] = None
    status: str = ""

    @classmethod
    def from_api(cls, obj: dict) -> "OcoLeg":
        return cls(
            order_id=int(obj.get("orderId")),
            client_order_id=str(obj.get("clientOrderId", "")),
            side=str(obj.get("side", "")),
            type=str(obj.get("type", "")),
            price=_dec(obj.get("price")),
            stop_price=_dec(obj.get("stopPrice")),
            orig_qty=_dec(obj.get("origQty")),
            executed_qty=_dec(obj.get("executedQty")),
            status=str(obj.get("status", "")),
        )

    def is_stop_leg(self) -> bool:
        """الرِّجل ذات التريجر (stopPrice > 0)، مع fallback على النوع."""
        if self.stop_price is not None and self.stop_price > 0:
            return True
        return "STOP" in (self.type or "").upper()


@dataclass
class OcoOrder:
    order_list_id: int
    symbol: str
    status: str = ""                 # listOrderStatus
    list_status_type: str = ""       # listStatusType
    quantity: Optional[Decimal] = None       # الكمية المقفولة (origQty)
    tp_price: Optional[Decimal] = None       # Sale/TP (above leg)
    stop_trigger: Optional[Decimal] = None   # Stop Trigger (belowStopPrice)
    stop_limit: Optional[Decimal] = None     # Limit After Trigger (belowPrice)
    leg_ids: List[int] = field(default_factory=list)
    executed_qty: Optional[Decimal] = None
    legs: List[OcoLeg] = field(default_factory=list)

    @property
    def remaining_qty(self) -> Optional[Decimal]:
        if self.quantity is None:
            return None
        return self.quantity - (self.executed_qty or Decimal("0"))

    def to_row(self) -> dict:
        """صف جدول Open OCO Orders (screen B)."""
        return {
            "orderListId": self.order_list_id,
            "symbol": self.symbol,
            "status": self.status,
            "qty": fmt(self.quantity),
            "saleTp": fmt(self.tp_price),
            "stopTrigger": fmt(self.stop_trigger),
            "limitAfterTrigger": fmt(self.stop_limit),
        }


@dataclass
class SelectedOCO:
    """هوية الهدف المحدد (P1) — يؤسّس Live context."""
    order_list_id: int
    symbol: str
    quantity: Optional[Decimal] = None       # مقفولة (Read-only, D7)
    tp: Optional[Decimal] = None
    stop_trigger: Optional[Decimal] = None
    stop_limit: Optional[Decimal] = None
    leg_ids: List[int] = field(default_factory=list)
    status: str = ""
    current_price: Optional[Decimal] = None  # يبقى None حتى Market WS (T4) — D14
    filters: Optional[SymbolFilters] = None
    quantity_locked: bool = True
    # G1.13: حقول مرشّح التحويل (أمر بيع مستقل غير OCO) — اختيارية بقيم افتراضية
    # حتى تبقى from_oco وكل الاختبارات الحالية خضراء.
    source_order_id: Optional[int] = None
    source_order_type: Optional[str] = None
    trailing_delta: Optional[int] = None
    is_convert_candidate: bool = False
    # G1.13 (EDIT 1): يحمل كائن أمر البيع الأصلي كاملًا (ConvertExecutor.convert
    # يحتاج OpenSellOrder وليس المعرّف فقط). additive فقط — repr/compare مُعطَّلان
    # لتفادي أيّ أثر على السلوك/التسلسل الحالي.
    source_order: Optional["OpenSellOrder"] = field(default=None, repr=False, compare=False)

    @classmethod
    def from_oco(cls, oco: OcoOrder, filters: Optional[SymbolFilters] = None) -> "SelectedOCO":
        return cls(
            order_list_id=oco.order_list_id,
            symbol=oco.symbol,
            quantity=oco.quantity,
            tp=oco.tp_price,
            stop_trigger=oco.stop_trigger,
            stop_limit=oco.stop_limit,
            leg_ids=list(oco.leg_ids),
            status=oco.status,
            filters=filters,
        )

    @classmethod
    def from_open_sell_order(
        cls, order: "OpenSellOrder", filters: Optional[SymbolFilters] = None
    ) -> "SelectedOCO":
        """يبني سياق "مرشّح تحويل" من أمر بيع مستقل غير OCO (G1.13).

        الكمية موروثة ومقفولة للقراءة فقط (D7): quantity = origQty - executedQty.
        لا يُحسَب هنا أيّ TP/SL — تُحسَب لاحقًا وقت التحويل من السعر الحيّ الحقيقي
        + النِّسب المئوية التي يُدخلها المستخدم (D6 نِسب فقط، D14 سعر حيّ،
        D-G1.13-refprice)، لذا tp/stop_trigger/stop_limit تبقى None هنا ولا تُمَسّ
        أيّة أسعار.
        """
        orig = _dec(order.origQty) or Decimal("0")
        executed = _dec(order.executedQty) or Decimal("0")
        remaining = orig - executed
        trailing = None
        td = _dec(order.trailingDelta)
        if td is not None:
            trailing = int(td)
        return cls(
            order_list_id=None,
            symbol=order.symbol,
            quantity=remaining,
            tp=None,
            stop_trigger=None,
            stop_limit=None,
            leg_ids=[order.orderId],
            status=order.status,
            current_price=None,
            filters=filters,
            quantity_locked=True,
            source_order_id=order.orderId,
            source_order_type=order.order_type,
            trailing_delta=trailing,
            is_convert_candidate=True,
            source_order=order,
        )

    def to_dict(self) -> dict:
        return {
            "orderListId": self.order_list_id,
            "symbol": self.symbol,
            "quantity": fmt(self.quantity),
            "quantityLocked": self.quantity_locked,
            "tp": fmt(self.tp),
            "stopTrigger": fmt(self.stop_trigger),
            "stopLimit": fmt(self.stop_limit),
            "legIds": self.leg_ids,
            "status": self.status,
            "currentPrice": fmt(self.current_price),
            "filters": self.filters.to_dict() if self.filters else None,
        }


# --- G1.13: unified open-sell-order model (additive) ---
_SELL_TYPE_BADGES = {
    "LIMIT": "LIMIT", "LIMIT_MAKER": "LIMIT_MAKER",
    "STOP_LOSS": "STOP_LOSS", "STOP_LOSS_LIMIT": "STOP_LOSS_LIMIT",
    "TAKE_PROFIT": "TAKE_PROFIT", "TAKE_PROFIT_LIMIT": "TAKE_PROFIT_LIMIT",
}

def _has_trailing(raw: dict) -> bool:
    td = raw.get("trailingDelta")
    try:
        return td is not None and int(td) > 0
    except (TypeError, ValueError):
        return False

def classify_badge(raw: dict) -> str:
    otype = str(raw.get("type", "")).upper()
    badge = _SELL_TYPE_BADGES.get(otype, otype or "UNKNOWN")
    if _has_trailing(raw):
        badge = f"{badge} · TRAILING"
    return badge

@dataclass
class OpenSellOrder:
    symbol: str
    orderId: Optional[int]
    orderListId: int
    order_type: str
    side: str
    price: str
    stopPrice: str
    trailingDelta: str
    origQty: str
    executedQty: str
    status: str
    time: Optional[int]
    is_oco: bool
    oco_group_id: Optional[int]
    badge: str

    @classmethod
    def from_raw(cls, raw: dict) -> "OpenSellOrder":
        # Binance returns numeric fields as strings; keep them as-is.
        olid = int(raw.get("orderListId", -1))
        return cls(
            symbol=str(raw.get("symbol", "")),
            orderId=raw.get("orderId"),
            orderListId=olid,
            order_type=str(raw.get("type", "")).upper(),
            side=str(raw.get("side", "")).upper(),
            price=str(raw.get("price", "0")),
            stopPrice=str(raw.get("stopPrice", "0")),
            trailingDelta=str(raw.get("trailingDelta", "") or ""),
            origQty=str(raw.get("origQty", "0")),
            executedQty=str(raw.get("executedQty", "0")),
            status=str(raw.get("status", "")),
            time=raw.get("time"),
            is_oco=(olid != -1),
            oco_group_id=(olid if olid != -1 else None),
            badge=("OCO" if olid != -1 else classify_badge(raw)),
        )

