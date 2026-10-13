from __future__ import annotations
"""ocobot/domain/recovery.py — M4d Runtime Recovery (T8).

طبقة تنسيق تربط طبقة التخزين (core/state_store — T5) بقارئ الأوامر
(domain/oco_reader — T2) لاستئناف المراقبة بأمان بعد التعطّل.

مبدأ حاكم: لا كتابة عمياء عند الاستئناف — نطابق الحالة الفعلية للأمر عبر REST
(هوية orderListId، P1) قبل أي استئناف أو أي Cancel/Create. OCO مُغلق/غير موجود
خارجيًا ⇒ إيقاف + تنبيه بشري بدل الاستئناف الأعمى (D9/D10 بروح لا-إعادة-عمياء).
لا يُمَس أي OCO غير الأمر المحفوظ (P3). لا تلفيق لأي حالة/سعر (D14).
"""
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

from ..core.errors import OcoBotError
from ..core.failure_matrix import humanize
from ..core.state_store import PersistedState, MonitoringCheckpoint
from .monitoring import MonitoringState, MonitoringStateEnum

# حالات listOrderStatus التي تُعدّ "مفتوحة" وقابلة للاستئناف:
_OPEN_LIST_STATUSES = {"EXECUTING", "ALL_DONE_PENDING", "RESPONSE"}


class RecoveryDecision(Enum):
    NOTHING_TO_RESUME = "NOTHING_TO_RESUME"
    RESUME = "RESUME"
    HALT_EXTERNALLY_CLOSED = "HALT_EXTERNALLY_CLOSED"


@dataclass(frozen=True)
class RecoveryResult:
    decision: "RecoveryDecision"
    checkpoint: Optional[PersistedState] = None
    state: Optional[MonitoringState] = None
    live_oco: Any = None
    alert: Optional[str] = None

    @property
    def should_resume(self) -> bool:
        return self.decision is RecoveryDecision.RESUME


def _is_open(status: Any) -> bool:
    return str(status).upper() in _OPEN_LIST_STATUSES


def _reconstruct_state(cp: MonitoringCheckpoint) -> MonitoringState:
    """أعِد بناء MonitoringState من الـcheckpoint (أنواع صحيحة: Decimal/Enum/str).

    round-trip يساوي الأصل: الأرقام Decimal كما هي في الـcheckpoint (مُسلسَلة/مُستعادة
    عبر _str_to_dec في state_store)، والحالة enum من قيمتها النصّية، وباقي الحقول 1:1.
    """
    try:
        state_enum = MonitoringStateEnum(cp.state)
    except ValueError:
        state_enum = MonitoringStateEnum.DISCONNECTED
    return MonitoringState(
        enabled=bool(cp.enabled),
        state=state_enum,
        symbol=cp.symbol,
        reference_price=cp.reference_price,
        trigger_pct=cp.trigger_pct,
        tp_pct=cp.tp_pct,
        sl_pct=cp.sl_pct,
        latched=bool(cp.latched),
        in_flight=bool(cp.in_flight),
        target_order_list_id=cp.target_order_list_id,
        tolerance_pct=cp.tolerance_pct,
        guard_pct=cp.guard_pct,
        last_price=cp.last_price,
        last_reposition=cp.last_reposition,
        cursor=int(cp.cursor or 0),
    )


def recover(store, reader) -> RecoveryResult:
    """طابِق آخر checkpoint مع الحالة الفعلية عبر REST قبل الاستئناف. لا كتابة عمياء."""
    persisted = store.load()  # None على غياب/فساد الملف
    if persisted is None:
        return RecoveryResult(RecoveryDecision.NOTHING_TO_RESUME)
    cp = persisted.monitoring
    order_list_id = getattr(cp, "target_order_list_id", None)
    if cp is None or not getattr(cp, "enabled", False) or not order_list_id:
        return RecoveryResult(RecoveryDecision.NOTHING_TO_RESUME, checkpoint=persisted)
    # المطابقة أولًا عبر REST (P1). لا Cancel/Create قبل نجاحها.
    try:
        live = reader.get_oco(order_list_id)
    except OcoBotError as exc:
        return RecoveryResult(
            RecoveryDecision.HALT_EXTERNALLY_CLOSED,
            checkpoint=persisted,
            alert=humanize(exc) + " — تعذّر استئناف المراقبة: الأمر المحفوظ لم يَعُد موجودًا على المنصّة. لن يُستأنف شيء.",
        )
    if str(getattr(live, "order_list_id", "")) != str(order_list_id):
        return RecoveryResult(
            RecoveryDecision.HALT_EXTERNALLY_CLOSED,
            checkpoint=persisted,
            live_oco=live,
            alert=f"عدم تطابق هوية الأمر عند الاستئناف (المحفوظ {order_list_id} ≠ الفعلي {getattr(live,'order_list_id','?')}). إيقاف — لا استئناف أعمى.",
        )
    if not _is_open(getattr(live, "status", "")):
        return RecoveryResult(
            RecoveryDecision.HALT_EXTERNALLY_CLOSED,
            checkpoint=persisted,
            live_oco=live,
            alert=f"الأمر {order_list_id} أُغلق خارجيًا أثناء التعطّل (الحالة: {getattr(live,'status','?')}). إيقاف + تنبيه — لا استئناف أعمى.",
        )
    return RecoveryResult(
        RecoveryDecision.RESUME,
        checkpoint=persisted,
        state=_reconstruct_state(cp),
        live_oco=live,
    )
