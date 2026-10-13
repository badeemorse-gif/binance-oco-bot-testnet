"""شبكة أمان المركز (Position Guardian) — منطق خالص (G1.30 / chunk_1).

هذه الوحدة **إضافية بحتة** ومنطق خالص فقط:
  - لا شبكة، لا أوامر فعلية، لا I/O ملفات، لا Qt/UI.
  - لا تستورد أي وحدة وساطة/نقل/واجهة؛ تعتمد على stdlib فقط
    (``decimal``، ``dataclasses``، ``enum``، ``typing``).
  - خارج المسار الحار تمامًا (on_price_tick / SafeExecutor / reposition /
    create_oco): لا تُستدعى منه ولا تمسّه إطلاقًا.

القرار يُحسَب من لقطة ساكنة (``GuardianSnapshot``) + إعدادات
(``GuardianConfig``) عبر الدالة الخالصة ``evaluate`` التي تُعيد
``GuardianDecision`` — بلا أي أثر جانبي.

منع البيع المزدوج (structural double-sell guard):
  1. ``has_resting_protective_sell`` يمنع أي تدخّل عندما يوجد بيع حمائي قائم،
     فلا يُضاف أمر بيع ثانٍ أبدًا.
  2. ``protective_qty = min(free_base_qty, monitored_qty)`` يقصر الكمية على
     الرصيد الحرّ فعلًا والمُراقَب فقط؛ فإن كان الرصيد مقفولًا (أمر قائم يقفله)
     كان ``free_base_qty`` صفرًا والقرار NOOP.
هذان القيدان بنيويّان يمنعان البيع المزدوج دون الاعتماد على توقيت.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum


class GuardianAction(str, Enum):
    """ما ينبغي للمُشرِف فعله بناءً على اللقطة (قيم نصّية للتسلسل/التسجيل)."""

    INTERVENE = "INTERVENE"
    WAIT = "WAIT"
    NOOP = "NOOP"


@dataclass(frozen=True)
class GuardianConfig:
    """إعدادات الحارس (خالصة، بلا حالة خارجية).

    ``threshold_seconds``: مدة العُري المسموح بها قبل التدخّل (ثوانٍ).
    ``emergency_sl_pct``: نسبة الوقف الطارئ — تُخزَّن لأجزاء لاحقة (chunk_2+)
    لحساب السعر؛ لا يحسب chunk_1 أي سعر.
    """

    threshold_seconds: float = 4.0
    emergency_sl_pct: Decimal = field(default_factory=lambda: Decimal("1.0"))


@dataclass(frozen=True)
class GuardianSnapshot:
    """لقطة ساكنة لحالة عملة المراقبة النشطة (مدخلات خالصة لـ``evaluate``)."""

    symbol: str
    state: str  # قيمة MonitoringStateEnum كنصّ (مثل "FAILED_NEEDS_ATTENTION")
    in_flight: bool
    naked_seconds: float
    has_resting_protective_sell: bool
    free_base_qty: Decimal
    monitored_qty: Decimal


@dataclass(frozen=True)
class GuardianDecision:
    """قرار الحارس الناتج (بلا أثر جانبي)."""

    action: GuardianAction
    protective_qty: Decimal
    reason: str


_ZERO = Decimal("0")


def evaluate(snap: GuardianSnapshot, cfg: GuardianConfig) -> GuardianDecision:
    """دالة خالصة: تحوّل لقطة + إعدادات إلى قرار الحارس.

    المنطق (بالترتيب الصارم):
      1. بيع حمائي قائم ⇒ NOOP (منع البيع المزدوج).
      2. ``qty = min(free_base_qty, monitored_qty)``؛ إن كان ``<= 0`` ⇒ NOOP
         (الرصيد مقفول أو لا مركز).
      3. المركز عارٍ وله كمية حماية حرّة:
         - الحالة ``FAILED_NEEDS_ATTENTION`` ⇒ INTERVENE بكمية ``qty``.
         - جارٍ تموضع صحّي (``in_flight`` و ``naked_seconds < threshold``) ⇒ WAIT.
         - ``naked_seconds >= threshold`` ⇒ INTERVENE بكمية ``qty``.
         - غير ذلك (تحت العتبة) ⇒ WAIT.
    """
    # 1) منع البيع المزدوج: بيع حمائي قائم ⇒ لا تدخّل إطلاقًا.
    if snap.has_resting_protective_sell:
        return GuardianDecision(
            action=GuardianAction.NOOP,
            protective_qty=_ZERO,
            reason="protected: resting sell present",
        )

    # 2) الكمية القابلة للحماية = الأقل من (الرصيد الحرّ، الكمية المُراقَبة).
    qty = min(snap.free_base_qty, snap.monitored_qty)
    if qty <= _ZERO:
        return GuardianDecision(
            action=GuardianAction.NOOP,
            protective_qty=_ZERO,
            reason="no free protectable qty (locked or no position)",
        )

    # 3) المركز عارٍ وله كمية حماية حرّة.
    if snap.state == "FAILED_NEEDS_ATTENTION":
        return GuardianDecision(
            action=GuardianAction.INTERVENE,
            protective_qty=qty,
            reason="failed_needs_attention",
        )

    if snap.in_flight and snap.naked_seconds < cfg.threshold_seconds:
        return GuardianDecision(
            action=GuardianAction.WAIT,
            protective_qty=_ZERO,
            reason="healthy reposition in progress",
        )

    if snap.naked_seconds >= cfg.threshold_seconds:
        return GuardianDecision(
            action=GuardianAction.INTERVENE,
            protective_qty=qty,
            reason="naked beyond threshold",
        )

    return GuardianDecision(
        action=GuardianAction.WAIT,
        protective_qty=_ZERO,
        reason="below threshold",
    )
