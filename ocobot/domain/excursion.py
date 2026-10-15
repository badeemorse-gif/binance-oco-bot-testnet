"""تحليل حركة الصفقة الخالص: MFE/MAE + عمق الارتدادات (G1.56 · c2).

وحدة domain خالصة (بلا I/O ولا شبكة). المحرّك الأساسي لمُرشِّح النِّسب:
نقيس — عبر نوافذ أمامية على شموع تاريخية — توزيعات:
  - MFE: أقصى حركة مُواتية (%) ⇒ يغذّي طموح tp_pct (P75).
  - MAE: أقصى حركة معاكِسة (%) ⇒ يغذّي أرضية sl_pct (P80).
  - عمق الارتداد (pullback): أعمق تراجع من قمّة جارية داخل الحركة المُواتية
    ⇒ يغذّي trigger_pct (median).

الاصطلاح: كل القيم نِسب مئوية موجبة (مقدار). الجانب side ∈ {"long","short"}؛
الافتراضي "long" (قوس البوت: TP أعلى، SL أدنى). النِّسب تُحسب float إحصائيًا.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Sequence

from ocobot.domain.volatility import Candle, as_candles, percentile

LONG = "long"
SHORT = "short"


def _check_side(side: str) -> str:
    s = (side or "").lower()
    if s not in (LONG, SHORT):
        raise ValueError("side يجب أن يكون 'long' أو 'short'")
    return s


def favorable_pct(entry: float, price: float, side: str = LONG) -> float:
    """حركة مُواتية (%) لـ price مقابل entry (موجبة = ربح، سالبة = خسارة)."""
    side = _check_side(side)
    if entry <= 0 or price <= 0:
        return 0.0
    if side == LONG:
        return (price / entry - 1.0) * 100.0
    return (1.0 - price / entry) * 100.0


def mfe_mae(highs: Sequence[float], lows: Sequence[float],
            entry: float, side: str = LONG) -> Optional[tuple]:
    """(mfe_pct, mae_pct) كمقدارين موجبين على نافذة، أو None عند غياب البيانات."""
    side = _check_side(side)
    if entry <= 0 or not highs or not lows:
        return None
    hi = max(highs)
    lo = min(lows)
    if side == LONG:
        mfe = max(0.0, (hi / entry - 1.0) * 100.0)
        mae = max(0.0, (1.0 - lo / entry) * 100.0)
    else:
        mfe = max(0.0, (1.0 - lo / entry) * 100.0)
        mae = max(0.0, (hi / entry - 1.0) * 100.0)
    return mfe, mae


def max_pullback_pct(path: Sequence[float], side: str = LONG) -> float:
    """أعمق تراجع (%) من القمّة الجارية (long) / القاع الجاري (short) على مسار."""
    side = _check_side(side)
    if len(path) < 2:
        return 0.0
    worst = 0.0
    if side == LONG:
        peak = path[0]
        for p in path:
            if p > peak:
                peak = p
            if peak > 0:
                dd = (peak - p) / peak * 100.0
                if dd > worst:
                    worst = dd
    else:
        trough = path[0]
        for p in path:
            if p < trough:
                trough = p
            if trough > 0:
                up = (p - trough) / trough * 100.0
                if up > worst:
                    worst = up
    return worst


def pullback_depths(path: Sequence[float], side: str = LONG) -> List[float]:
    """كل أعماق الارتداد المحليّة (%) بين كل قمّتين جاريتين متعاقبتين.

    long: عند كل قمّة جديدة نُغلق التراجع السابق (إن وُجد قاع تحتها) ونسجّل
    عمقه = (القمّة السابقة − القاع)/القمّة السابقة ×100. التراجع المفتوح في
    النهاية يُسجَّل أيضًا. (مرآة للـshort.)
    """
    side = _check_side(side)
    depths: List[float] = []
    if len(path) < 2:
        return depths
    if side == LONG:
        peak = path[0]
        trough = path[0]
        for p in path[1:]:
            if p > peak:
                if trough < peak and peak > 0:
                    depths.append((peak - trough) / peak * 100.0)
                peak = p
                trough = p
            elif p < trough:
                trough = p
        if trough < peak and peak > 0:
            depths.append((peak - trough) / peak * 100.0)
    else:
        trough = path[0]
        peak = path[0]
        for p in path[1:]:
            if p < trough:
                if peak > trough and trough > 0:
                    depths.append((peak - trough) / trough * 100.0)
                trough = p
                peak = p
            elif p > peak:
                peak = p
        if peak > trough and trough > 0:
            depths.append((peak - trough) / trough * 100.0)
    return depths


@dataclass
class ExcursionSamples:
    mfe: List[float] = field(default_factory=list)
    mae: List[float] = field(default_factory=list)
    pullback: List[float] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.mfe)


def simulate_excursions(raw: Iterable, horizon: int, side: str = LONG,
                        step: int = 1) -> ExcursionSamples:
    """يبني توزيعات MFE/MAE/pullback بنوافذ أمامية بطول horizon.

    لكل بداية i (بخطوة step): entry = إغلاق الشمعة i، والنافذة هي الشموع
    (i+1 .. i+horizon). pullback يُحسب على مسار [entry, closes(window...)].
    """
    side = _check_side(side)
    if horizon <= 0:
        raise ValueError("horizon يجب أن يكون موجبًا")
    if step <= 0:
        raise ValueError("step يجب أن يكون موجبًا")
    candles = as_candles(raw)
    samples = ExcursionSamples()
    last_start = len(candles) - horizon - 1
    i = 0
    while i <= last_start:
        entry = candles[i].close
        window = candles[i + 1: i + 1 + horizon]
        mm = mfe_mae([c.high for c in window], [c.low for c in window], entry, side)
        if mm is not None:
            mfe, mae = mm
            samples.mfe.append(mfe)
            samples.mae.append(mae)
            path = [entry] + [c.close for c in window]
            samples.pullback.append(max_pullback_pct(path, side))
        i += step
    return samples


@dataclass
class ExcursionStats:
    count: int
    p50_mfe: Optional[float]
    p75_mfe: Optional[float]
    p90_mfe: Optional[float]
    p50_mae: Optional[float]
    p80_mae: Optional[float]
    p90_mae: Optional[float]
    median_pullback: Optional[float]
    p75_pullback: Optional[float]

    def to_dict(self) -> dict:
        return {
            "count": self.count,
            "p50Mfe": self.p50_mfe,
            "p75Mfe": self.p75_mfe,
            "p90Mfe": self.p90_mfe,
            "p50Mae": self.p50_mae,
            "p80Mae": self.p80_mae,
            "p90Mae": self.p90_mae,
            "medianPullback": self.median_pullback,
            "p75Pullback": self.p75_pullback,
        }


def summarize_excursions(samples: ExcursionSamples) -> ExcursionStats:
    """مئينات التوزيعات التي يستهلكها recommender (c4)."""
    return ExcursionStats(
        count=len(samples),
        p50_mfe=percentile(samples.mfe, 50),
        p75_mfe=percentile(samples.mfe, 75),
        p90_mfe=percentile(samples.mfe, 90),
        p50_mae=percentile(samples.mae, 50),
        p80_mae=percentile(samples.mae, 80),
        p90_mae=percentile(samples.mae, 90),
        median_pullback=percentile(samples.pullback, 50),
        p75_pullback=percentile(samples.pullback, 75),
    )


def excursion_stats(raw: Iterable, horizon: int, side: str = LONG,
                    step: int = 1) -> ExcursionStats:
    """اختصار: محاكاة ثم تلخيص في خطوة واحدة."""
    return summarize_excursions(simulate_excursions(raw, horizon, side, step))
