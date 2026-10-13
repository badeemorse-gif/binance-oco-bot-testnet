"""حالة الحارس للعرض (Guardian UI Status) — G1.31 / chunk_1.

نموذج خالص (stdlib فقط، بلا Qt/شبكة/ملفات) يمثّل حالة Position Guardian
للعرض في الواجهة، مع مخزن حالة خفيف يُشعِر المستمعين (listeners) عند التغيّر —
حتى تشترك طبقة الواجهة دون أن يمسّ النموذج أيّ I/O.

هذه الوحدة **إضافية بحتة**: لا تمسّ المسار الحار ولا تستورد أيّ وحدة
وساطة/نقل/واجهة. تعتمد على ``dataclasses`` و ``enum`` و ``typing`` فقط.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Callable, List, Optional


class GuardianMode(str, Enum):
    """وضع تشغيل الحارس كما يختاره المستخدم من الواجهة (يطابق OCOBOT_GUARDIAN)."""

    OFF = "off"          # مطفأ: لا يراقب ولا يتدخّل.
    OBSERVE = "observe"  # مراقبة فقط: يكتشف وينبّه، بلا وضع أمر (dry_run).
    LIVE = "live"        # تدخّل فعلي: يضع وقفًا حمائيًّا عند العُري الممتدّ.


class GuardianUiState(str, Enum):
    """الحالة المعروضة في الواجهة."""

    DISABLED = "disabled"      # مطفأ (الوضع OFF).
    SLEEPING = "sleeping"      # نائم: مفعّل ويراقب، لا عُري.
    WATCHING = "watching"      # رصد عُري: يعدّ ثواني العُري تحت العتبة.
    INTERVENED = "intervened"  # تدخّل: وضع وقفًا حمائيًّا وأوقف المراقبة.


@dataclass(frozen=True)
class LastAction:
    """آخر إجراء/حدث للحارس (نصوص للعرض فقط — بلا حساب)."""

    ts: str
    action: str
    reason: str = ""
    qty: str = ""
    price: str = ""


@dataclass(frozen=True)
class GuardianStatus:
    """لقطة حالة الحارس المعروضة."""

    mode: GuardianMode = GuardianMode.OFF
    state: GuardianUiState = GuardianUiState.DISABLED
    last_action: Optional[LastAction] = None
    updated_at: str = ""


class GuardianStatusStore:
    """مخزن حالة خفيف يحمل الحالة الحالية ويُشعِر المستمعين عند التغيّر.

    stdlib فقط؛ المستمعون دوال بسيطة ``Callable[[GuardianStatus], None]``.
    لا I/O ولا Qt — طبقة الواجهة تشترك وتترجم الحالة لعناصر مرئية.
    """

    def __init__(self, initial: Optional[GuardianStatus] = None):
        self._status = initial if initial is not None else GuardianStatus()
        self._listeners: List[Callable[[GuardianStatus], None]] = []

    @property
    def status(self) -> GuardianStatus:
        return self._status

    def subscribe(self, listener: Callable[[GuardianStatus], None]) -> Callable[[], None]:
        """يسجّل مستمعًا ويُشعِره فورًا بالحالة الحالية؛ يعيد دالة إلغاء اشتراك."""
        self._listeners.append(listener)
        try:
            listener(self._status)
        except Exception:
            pass

        def _unsubscribe() -> None:
            try:
                self._listeners.remove(listener)
            except ValueError:
                pass

        return _unsubscribe

    def set(self, status: GuardianStatus) -> None:
        self._status = status
        self._notify()

    def update(self, **changes) -> GuardianStatus:
        self._status = replace(self._status, **changes)
        self._notify()
        return self._status

    def _notify(self) -> None:
        for listener in list(self._listeners):
            try:
                listener(self._status)
            except Exception:
                # عزل أيّ مستمع فاشل حتى لا يكسر البقية.
                pass
