"""Three-price calculation with dynamic tick/step filters (M2, D4–D8).

دوال خالصة على Decimal (لا I/O، لا شبكة):
  - round_to_tick / floor_to_step: مضاعفات نظيفة من الفلاتر (D8 — لا hardcode).
  - compute_levels: TP / Stop Trigger / Stop Limit من سعر مرجعي حيّ (D6/D5/D4).
  - max_available_stop: أكبر مضاعف tick أدنى من السعر الأخير بصرامة (D4).

النِّسب أرقام مئوية: Decimal("4") تعني 4%. كل المدخلات تُحوَّل عبر Decimal(str(x)).
لا يُختلَق أي سعر حيّ (D14): reference_price مُدخَل صريح في M2.
"""
from __future__ import annotations

from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

DEFAULT_GAP_TICKS = 1  # D5: المستخدم لا يُدخل الفجوة إطلاقًا


def _dec(value) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def round_to_tick(price, tick_size, rounding=ROUND_HALF_UP) -> Decimal:
    """يُقرّب السعر إلى أقرب مضاعف نظيف من tickSize (D8)."""
    price = _dec(price)
    tick = _dec(tick_size)
    if not tick:  # tick falsy → أعِد السعر كما هو
        return price
    steps = (price / tick).quantize(Decimal("1"), rounding=rounding)
    return (steps * tick).normalize() + Decimal("0")


def floor_to_step(qty, step_size) -> Decimal:
    """يُنزّل الكمية لأقرب مضاعف أدنى من stepSize (ROUND_DOWN، D7)."""
    qty = _dec(qty)
    step = _dec(step_size)
    if not step:
        return qty
    steps = (qty / step).quantize(Decimal("1"), rounding=ROUND_DOWN)
    return (steps * step).normalize() + Decimal("0")


def is_multiple_of(value, unit) -> bool:
    """هل value مضاعف تام لِـ unit؟ (فحص فلاتر D8)."""
    value = _dec(value)
    unit = _dec(unit)
    if not unit:
        return True
    return (value % unit) == 0


def compute_levels(reference_price, tp_pct, sl_pct, tick_size,
                   gap_ticks=DEFAULT_GAP_TICKS):
    """يحسب (tp, stop_trigger, stop_limit) من سعر مرجعي حيّ P (D6).

    TP           = round_to_tick(P*(1+tp_pct/100))     [ROUND_HALF_UP]
    Stop Trigger = round_to_tick(P*(1-sl_pct/100))     [ROUND_HALF_UP]
    Stop Limit   = Stop Trigger - gap_ticks*tick        [مضاعف tick أدنى بصرامة، D4]
    """
    p = _dec(reference_price)
    tp_pct = _dec(tp_pct)
    sl_pct = _dec(sl_pct)
    tick = _dec(tick_size)
    hundred = Decimal("100")

    tp = round_to_tick(p * (Decimal("1") + tp_pct / hundred), tick)
    stop_trigger = round_to_tick(p * (Decimal("1") - sl_pct / hundred), tick)

    gap = _dec(gap_ticks) * tick
    stop_limit = stop_trigger - gap
    # اضمن أن Stop Limit مضاعف tick صارم وأدنى من Trigger (D4)
    stop_limit = round_to_tick(stop_limit, tick, rounding=ROUND_DOWN)
    if tick and stop_limit >= stop_trigger:
        stop_limit = stop_trigger - tick
    return tp, stop_trigger, stop_limit


def max_available_stop(last_price, tick_size) -> Decimal:
    """أكبر مضاعف tick أدنى من last_price بصرامة (سقف Stop Trigger، D4)."""
    last = _dec(last_price)
    tick = _dec(tick_size)
    if not tick:
        return last
    floored = round_to_tick(last, tick, rounding=ROUND_DOWN)
    if floored >= last:
        floored = floored - tick
    return floored
