"""مُرشِّح النِّسب التكيّفي (G1.56 · c4) — الربط النهائي.

وحدة domain خالصة (بلا I/O ولا شبكة): تجمع مخرجات volatility + excursion +
regime وتُنتج اقتراح tp_pct/sl_pct/trigger_pct + gap_ticks، مقصوصًا على:
  - فلاتر العملة (tickSize ⇒ أرضية «حركة ≥ عدّة ticks»)،
  - حارس السيولة/السبريد (قرار المنفّذ): توسيع trigger/gap وتحجيم TP،
  - أرضية الضوضاء من فريم منخفض (LTF) — فريمات هرمية،
  - أرضية الفلاش-كراش (G1.33) **مُحقَّنة** كبارامتر (لا تُختلَق هنا — P4)،
  - حدود دنيا/عليا قابلة للمعايرة.

الربط الأساسي (قابل للمعايرة):
  sl_pct      ≈ max(k_sl · ATR%,  P80(MAE))
  trigger_pct ≈ median(pullback) · trigger_f
  tp_pct      ≈ P75(MFE) · adx_factor(HTF)

المخرجات نِسب Decimal (مثل Decimal("4") = 4%) لتتوافق مع pricing.compute_levels.
الوحدة لا تقرّر شراء/بيع ولا تولّد إشارات — عرض/اقتراح فقط (التزام exclusions).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import List, Optional

from ocobot.domain import pricing
from ocobot.domain.excursion import ExcursionStats
from ocobot.domain.models import SymbolFilters
from ocobot.domain.regime import LiquidityState, RegimeSummary
from ocobot.domain.volatility import VolatilitySummary


@dataclass
class RecommenderParams:
    k_sl: float = 2.0            # معامل ATR لأرضية SL
    trigger_f: float = 0.7       # نسبة من median(pullback) للمُشغّل
    tp_min_pct: float = 0.3
    tp_max_pct: float = 50.0
    sl_min_pct: float = 0.3
    sl_max_pct: float = 50.0
    trigger_min_pct: float = 0.1
    trigger_max_pct: float = 20.0
    min_tp_ticks: int = 2        # TP/SL ≥ هذا العدد من ticks
    min_trigger_ticks: int = 2   # trigger ≥ هذا العدد من ticks
    gap_ticks: int = pricing.DEFAULT_GAP_TICKS
    # حارس السيولة
    wide_spread_trigger_mult: float = 2.0   # trigger ≥ mult × spread%
    thin_tp_haircut: float = 0.8            # تحجيم TP عند ضعف السيولة
    illiquid_extra_gap_ticks: int = 1
    decimals: int = 3            # دقّة تقريب النِّسب


@dataclass
class Recommendation:
    tp_pct: Decimal
    sl_pct: Decimal
    trigger_pct: Decimal
    gap_ticks: int
    rationale: dict = field(default_factory=dict)
    flags: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        from ocobot.domain.models import fmt
        return {
            "tpPct": fmt(self.tp_pct),
            "slPct": fmt(self.sl_pct),
            "triggerPct": fmt(self.trigger_pct),
            "gapTicks": self.gap_ticks,
            "flags": list(self.flags),
            "rationale": dict(self.rationale),
        }


def _pct_dec(value: float, decimals: int) -> Decimal:
    return Decimal(str(round(float(value), decimals)))


def _clamp(x: float, lo: float, hi: float):
    """يُعيد (value, hit) حيث hit ∈ {None,'min','max'}."""
    if x < lo:
        return lo, "min"
    if x > hi:
        return hi, "max"
    return x, None


def recommend(volatility: VolatilitySummary,
              excursion: ExcursionStats,
              regime: RegimeSummary,
              filters: Optional[SymbolFilters],
              reference_price,
              liquidity: Optional[LiquidityState] = None,
              params: Optional[RecommenderParams] = None,
              htf_regime: Optional[RegimeSummary] = None,
              ltf_atr_pct: Optional[float] = None,
              flash_crash_floor_pct: Optional[float] = None) -> Optional[Recommendation]:
    """يُنتج اقتراح نِسب، أو None إذا تعذّر توفّر أي مُدخل أساسي.

    - htf_regime: فريم أعلى لسياق الطموح (adx_factor للـTP)؛ غيابه ⇒ regime التشغيل.
    - ltf_atr_pct: تقلّب فريم منخفض كأرضية ضوضاء (trigger/sl لا يقلّان عنها).
    - flash_crash_floor_pct: أرضية G1.33 مُحقَّنة من المتصل (لا تُختلَق).
    """
    p = params or RecommenderParams()
    ref = float(reference_price) if reference_price else 0.0

    atr_pct = volatility.atr_pct
    if atr_pct is None:
        atr_pct = volatility.per_period_vol_pct
    p80_mae = excursion.p80_mae
    p75_mfe = excursion.p75_mfe
    med_pull = excursion.median_pullback

    # لا بدّ من مقياس عرض (ATR) أو توزيع حركة؛ وإلا لا اقتراح.
    if atr_pct is None and p75_mfe is None and p80_mae is None:
        return None

    flags: List[str] = []

    # عامل الطموح من الفريم الأعلى (سياق الاتجاه).
    adx_factor = (htf_regime or regime).adx_factor

    # --- الربط الخام ---
    sl_candidates = []
    if atr_pct is not None:
        sl_candidates.append(p.k_sl * atr_pct)
    if p80_mae is not None:
        sl_candidates.append(p80_mae)
    sl_raw = max(sl_candidates) if sl_candidates else (atr_pct or 1.0)

    if med_pull is not None:
        trigger_raw = med_pull * p.trigger_f
    elif atr_pct is not None:
        trigger_raw = atr_pct * 0.5
        flags.append("trigger_fallback_atr")
    else:
        trigger_raw = sl_raw * 0.5
        flags.append("trigger_fallback_sl")

    if p75_mfe is not None:
        tp_raw = p75_mfe * adx_factor
    elif atr_pct is not None:
        tp_raw = atr_pct * 1.5 * adx_factor
        flags.append("tp_fallback_atr")
    else:
        tp_raw = sl_raw * 1.5
        flags.append("tp_fallback_sl")

    rationale = {
        "atrPct": atr_pct, "p80Mae": p80_mae, "p75Mfe": p75_mfe,
        "medianPullback": med_pull, "adxFactor": adx_factor,
        "regimeLabel": regime.label,
    }

    # --- أرضية ضوضاء الفريم المنخفض (هرمية) ---
    if ltf_atr_pct is not None:
        if trigger_raw < ltf_atr_pct:
            trigger_raw = ltf_atr_pct
            flags.append("noise_floor_trigger")
        if sl_raw < ltf_atr_pct:
            sl_raw = ltf_atr_pct
            flags.append("noise_floor_sl")

    # --- أرضية الفلاش-كراش (مُحقَّنة، G1.33) ---
    if flash_crash_floor_pct is not None and sl_raw < flash_crash_floor_pct:
        sl_raw = flash_crash_floor_pct
        flags.append("flash_crash_floor")

    gap_ticks = p.gap_ticks

    # --- حارس السيولة/السبريد (قرار المنفّذ) ---
    if liquidity is not None:
        if liquidity.is_wide_spread and liquidity.spread_pct is not None:
            widened = liquidity.spread_pct * p.wide_spread_trigger_mult
            if trigger_raw < widened:
                trigger_raw = widened
            gap_ticks += p.illiquid_extra_gap_ticks
            flags.append("liquidity_wide_spread")
        if liquidity.is_thin:
            tp_raw *= p.thin_tp_haircut
            if "liquidity_wide_spread" not in flags:
                gap_ticks += p.illiquid_extra_gap_ticks
            flags.append("liquidity_thin")

    # --- أرضية الـticks (فلاتر العملة) ---
    tick_pct = 0.0
    if filters is not None and filters.tick_size and ref > 0:
        tick_pct = float(filters.tick_size) / ref * 100.0
        if tp_raw < p.min_tp_ticks * tick_pct:
            tp_raw = p.min_tp_ticks * tick_pct
            flags.append("tp_tick_floor")
        if sl_raw < p.min_tp_ticks * tick_pct:
            sl_raw = p.min_tp_ticks * tick_pct
            flags.append("sl_tick_floor")
        if trigger_raw < p.min_trigger_ticks * tick_pct:
            trigger_raw = p.min_trigger_ticks * tick_pct
            flags.append("trigger_tick_floor")
    rationale["tickPct"] = tick_pct

    # --- حدود دنيا/عليا ---
    tp_v, hit = _clamp(tp_raw, p.tp_min_pct, p.tp_max_pct)
    if hit:
        flags.append(f"tp_{hit}")
    sl_v, hit = _clamp(sl_raw, p.sl_min_pct, p.sl_max_pct)
    if hit:
        flags.append(f"sl_{hit}")
    tr_v, hit = _clamp(trigger_raw, p.trigger_min_pct, p.trigger_max_pct)
    if hit:
        flags.append(f"trigger_{hit}")

    tp_pct = _pct_dec(tp_v, p.decimals)
    sl_pct = _pct_dec(sl_v, p.decimals)
    trigger_pct = _pct_dec(tr_v, p.decimals)

    # --- تحقّق أن المستويات غير منهارة عند tick/السعر المرجعي ---
    if filters is not None and filters.tick_size and ref > 0:
        tp_price, stop_trigger, stop_limit = pricing.compute_levels(
            Decimal(str(ref)), tp_pct, sl_pct, filters.tick_size, gap_ticks)
        if not (tp_price > Decimal(str(ref)) > stop_trigger > stop_limit):
            flags.append("levels_degenerate")
        rationale["levels"] = {
            "tp": str(tp_price), "stopTrigger": str(stop_trigger),
            "stopLimit": str(stop_limit),
        }

    return Recommendation(tp_pct, sl_pct, trigger_pct, gap_ticks, rationale, flags)
