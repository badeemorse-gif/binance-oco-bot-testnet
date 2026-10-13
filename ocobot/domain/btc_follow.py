# -*- coding: utf-8 -*-
"""حارس هبوط BTC (BTC-follow guard) — منطق خالص (G1.44 / chunk_1).

وحدة **إضافية بحتة** ومنطق خالص فقط:
  - لا شبكة، لا أوامر فعلية، لا I/O ملفات، لا Qt/UI.
  - stdlib فقط (``decimal``، ``dataclasses``، ``enum``، ``typing``).
  - خارج المسار الحار تمامًا: لا تضع أوامر ولا تلمس عملة المراقبة؛ تُخرج
    قرارًا دفاعيًا (اقتراح تضييق ستوب) فقط، يتصرّف به المُشرِف لاحقًا (chunk_2+).

الفكرة: رصد انحدار BTC المتسارع المؤكّد خلال نافذة ثوانٍ (rate-of-change)
ثم اقتراح تضييق ستوب واقٍ للعملة المراقَبة — دفاعيًا لا سباقًا على القاع.
BTC هنا **مُدخَل خارجي للقراءة فقط**؛ لا يُخزَّن قرار ولا يُنفَّذ بيع في هذه الوحدة.

آلة الحالة (خالصة):
  IDLE  --(انحدار ضمن النافذة ≥ drop_pct)-->  ARMED (بدء نافذة التأكيد)
  ARMED --(مضى confirm_seconds والانحدار استمرّ)--> TIGHTEN ثم العودة إلى IDLE
  ARMED --(ارتدّ السعر: الانحدار < drop_pct)--> IDLE (هزّة وهمية؛ لا فعل)
القرار بلا أثر جانبي: ``evaluate`` تُعيد ``BtcFollowDecision`` حاملةً الحالة التالية.

fail-safe: بيانات ناقصة/غير كافية ⇒ NOOP وإعادة الحالة إلى IDLE (لا فعل عند فقد التغذية).
الحارس مُعطّل افتراضيًّا (``enabled=False``) ⇒ NOOP دائمًا.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Optional, Sequence, Tuple


class BtcFollowAction(str, Enum):
    """ما يقترحه الحارس على المُشرِف (قيم نصّية للتسلسل/التسجيل)."""

    NOOP = "NOOP"        # لا شيء (مُعطّل/تحت العتبة/بيانات ناقصة/هزّة وهمية)
    ARM = "ARM"          # رُصد انحدار؛ ضمن نافذة التأكيد (لا فعل بعد)
    TIGHTEN = "TIGHTEN"  # انحدار مؤكّد ⇒ اقتراح تضييق الستوب الواقي


class BtcFollowPhase(str, Enum):
    """طور آلة الحالة الداخلية."""

    IDLE = "IDLE"
    ARMED = "ARMED"


@dataclass(frozen=True)
class BtcFollowConfig:
    """إعدادات الحارس (خالصة، بلا حالة خارجية)."""

    enabled: bool = False                       # الافتراضي OFF
    drop_pct: Decimal = field(default_factory=lambda: Decimal("0.8"))             # عتبة الانحدار ضمن النافذة (%)
    window_seconds: float = 3.0                 # نافذة قياس rate-of-change (ثوانٍ)
    confirm_seconds: float = 1.0                # نافذة التأكيد/debounce (ثوانٍ)
    tighten_offset_pct: Decimal = field(default_factory=lambda: Decimal("0.2"))  # تلميح: بُعد الستوب المقترح تحت السعر (%)


@dataclass(frozen=True)
class BtcSample:
    """عيّنة سعر BTC: طابع زمني (ثوانٍ) + سعر."""

    ts: float
    price: Decimal


@dataclass(frozen=True)
class BtcFollowState:
    """الحالة الداخلية (طيّارة؛ لا تُستأنَف ضمن checkpoint)."""

    phase: BtcFollowPhase = BtcFollowPhase.IDLE
    armed_at: Optional[float] = None
    armed_ref_price: Optional[Decimal] = None


@dataclass(frozen=True)
class BtcFollowDecision:
    """قرار الحارس الناتج (بلا أثر جانبي)؛ ``state`` هي الحالة التالية."""

    action: BtcFollowAction
    phase: BtcFollowPhase
    drop_pct: Decimal
    reason: str
    state: BtcFollowState


_ZERO = Decimal("0")
_HUNDRED = Decimal("100")
_IDLE_STATE = BtcFollowState()


def _window_drop(
    samples: Sequence[BtcSample], now: float, window_seconds: float
) -> Optional[Tuple[Decimal, Decimal, Decimal]]:
    """يحسب أقصى انحدار ضمن النافذة الزمنية الخلفية.

    يُعيد ``(drop_pct, peak, current)`` أو ``None`` إن تعذّر (fail-safe):
    لا عيّنات كافية (< 2 داخل النافذة)، أو ذروة غير موجبة.
    ``drop_pct = (peak - current) / peak * 100`` حيث ``peak`` أعلى سعر ضمن
    النافذة و``current`` آخر عيّنة فيها.
    """
    if not samples:
        return None
    lo = now - window_seconds
    window = [s for s in samples if s.ts >= lo]
    if len(window) < 2:
        return None
    peak = max(s.price for s in window)
    current = window[-1].price
    if peak <= _ZERO:
        return None
    drop = (peak - current) / peak * _HUNDRED
    if drop < _ZERO:
        drop = _ZERO
    return drop, peak, current


def evaluate(
    samples: Sequence[BtcSample],
    cfg: BtcFollowConfig,
    state: BtcFollowState,
    now: float,
) -> BtcFollowDecision:
    """دالة خالصة: عيّنات BTC + إعدادات + حالة + الزمن ⇒ قرار الحارس.

    لا تضع أوامر ولا تمسّ عملة المراقبة؛ تُخرج اقتراحًا فقط.
    """
    # 0) مُعطّل ⇒ NOOP دائمًا وإعادة الحالة إلى IDLE.
    if not cfg.enabled:
        return BtcFollowDecision(
            action=BtcFollowAction.NOOP,
            phase=BtcFollowPhase.IDLE,
            drop_pct=_ZERO,
            reason="disabled",
            state=_IDLE_STATE,
        )

    # 1) fail-safe: بيانات ناقصة ⇒ NOOP وإعادة إلى IDLE (لا فعل عند فقد التغذية).
    wd = _window_drop(samples, now, cfg.window_seconds)
    if wd is None:
        return BtcFollowDecision(
            action=BtcFollowAction.NOOP,
            phase=BtcFollowPhase.IDLE,
            drop_pct=_ZERO,
            reason="insufficient_data",
            state=_IDLE_STATE,
        )
    drop, peak, _current = wd

    # 2) طور IDLE: رصد بدء الانحدار.
    if state.phase is not BtcFollowPhase.ARMED:
        if drop >= cfg.drop_pct:
            armed = BtcFollowState(
                phase=BtcFollowPhase.ARMED, armed_at=now, armed_ref_price=peak
            )
            return BtcFollowDecision(
                action=BtcFollowAction.ARM,
                phase=BtcFollowPhase.ARMED,
                drop_pct=drop,
                reason="drop_detected",
                state=armed,
            )
        return BtcFollowDecision(
            action=BtcFollowAction.NOOP,
            phase=BtcFollowPhase.IDLE,
            drop_pct=drop,
            reason="below_threshold",
            state=_IDLE_STATE,
        )

    # 3) طور ARMED: نافذة التأكيد (debounce).
    armed_at = state.armed_at if state.armed_at is not None else now
    elapsed = now - armed_at
    if elapsed >= cfg.confirm_seconds:
        if drop >= cfg.drop_pct:
            # انحدار مؤكّد ⇒ اقتراح تضييق؛ العودة إلى IDLE
            # (أحادي؛ قد يُعاد التسليح إن استمرّ الهبوط في التِّكات التالية).
            return BtcFollowDecision(
                action=BtcFollowAction.TIGHTEN,
                phase=BtcFollowPhase.IDLE,
                drop_pct=drop,
                reason="confirmed_drop",
                state=_IDLE_STATE,
            )
        # ارتدّ السعر ⇒ هزّة وهمية؛ لا فعل.
        return BtcFollowDecision(
            action=BtcFollowAction.NOOP,
            phase=BtcFollowPhase.IDLE,
            drop_pct=drop,
            reason="recovered_fakeout",
            state=_IDLE_STATE,
        )

    # ما زلنا داخل نافذة التأكيد ⇒ انتظار.
    return BtcFollowDecision(
        action=BtcFollowAction.ARM,
        phase=BtcFollowPhase.ARMED,
        drop_pct=drop,
        reason="confirming",
        state=state,
    )
