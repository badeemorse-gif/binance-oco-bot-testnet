"""طبقة النظام (Regime) + قياس السيولة/السبريد الخالص (G1.56 · c3).

وحدة domain خالصة (بلا I/O ولا شبكة):
  - `adx_dmi` (Wilder): قوة الاتجاه +DI/-DI/ADX ⇒ عامل scaling للـTP.
  - `choppiness_index`: 0..100؛ مرتفع=تذبذب/تجميع، منخفض=اتجاه.
  - `hurst_rs` + `variance_ratio`: ثبات/ارتداد العوائد (طبقة سياق).
  - طبقة السيولة/السبريد (قرار المنفّذ): قياسات `average_volume`,
    `spread_pct`, و`assess_liquidity` ⇒ تُستهلك كحارس قصّ في recommender (c4).

النِّسب float إحصائيًا. الاقتراحات التنفيذية (Decimal) تبقى في recommender/pricing.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence

from ocobot.domain.volatility import (Candle, _sample_variance, as_candles,
                                      true_ranges)

DEFAULT_PERIOD = 14
CHOP_TREND_MAX = 38.2    # < ⇒ اتجاه واضح
CHOP_RANGE_MIN = 61.8    # > ⇒ تذبذب/تجميع
ADX_TREND_MIN = 25.0     # ≥ ⇒ اتجاه قوي
ADX_WEAK_MAX = 20.0      # < ⇒ ضعيف/عديم اتجاه


def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


# ----------------------------- ADX / DMI -----------------------------

def adx_dmi(candles: Sequence[Candle], period: int = DEFAULT_PERIOD) -> Optional[tuple]:
    """(adx, plus_di, minus_di) بطريقة Wilder، أو None عند نقص البيانات.

    يتطلّب عدد شموع ≥ 2*period + 1.
    """
    if period <= 0:
        raise ValueError("period يجب أن يكون موجبًا")
    cs = list(candles)
    trs = true_ranges(cs)
    m = len(trs)
    if m < 2 * period:
        return None
    plus: List[float] = []
    minus: List[float] = []
    for prev, cur in zip(cs, cs[1:]):
        up = cur.high - prev.high
        down = prev.low - cur.low
        plus.append(up if (up > down and up > 0) else 0.0)
        minus.append(down if (down > up and down > 0) else 0.0)

    atr = sum(trs[:period])
    sp = sum(plus[:period])
    sm = sum(minus[:period])

    def _dx(atr_, sp_, sm_):
        pdi = 100.0 * sp_ / atr_ if atr_ > 0 else 0.0
        mdi = 100.0 * sm_ / atr_ if atr_ > 0 else 0.0
        denom = pdi + mdi
        dx = 100.0 * abs(pdi - mdi) / denom if denom > 0 else 0.0
        return pdi, mdi, dx

    pdi, mdi, dx = _dx(atr, sp, sm)
    dxs = [dx]
    for i in range(period, m):
        atr = atr - atr / period + trs[i]
        sp = sp - sp / period + plus[i]
        sm = sm - sm / period + minus[i]
        pdi, mdi, dx = _dx(atr, sp, sm)
        dxs.append(dx)

    if len(dxs) < period:
        return None
    adx = sum(dxs[:period]) / period
    for dx in dxs[period:]:
        adx = (adx * (period - 1) + dx) / period
    return adx, pdi, mdi


def adx(candles: Sequence[Candle], period: int = DEFAULT_PERIOD) -> Optional[float]:
    res = adx_dmi(candles, period)
    return None if res is None else res[0]


# --------------------------- Choppiness ---------------------------

def choppiness_index(candles: Sequence[Candle], period: int = DEFAULT_PERIOD) -> Optional[float]:
    """مؤشّر التذبذب 0..100 على آخر period شمعة. None عند نقص/مدى صفري."""
    if period < 2:
        raise ValueError("period يجب أن يكون ≥ 2")
    trs = true_ranges(candles)
    if len(trs) < period:
        return None
    window_trs = trs[-period:]
    window = list(candles)[-period:]
    sum_tr = sum(window_trs)
    hh = max(c.high for c in window)
    ll = min(c.low for c in window)
    rng = hh - ll
    if rng <= 0 or sum_tr <= 0:
        return None
    return 100.0 * math.log10(sum_tr / rng) / math.log10(period)


# --------------------- Hurst (R/S) + Variance-Ratio ---------------------

def _ols_slope(xs: Sequence[float], ys: Sequence[float]) -> Optional[float]:
    n = len(xs)
    if n < 2:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = sum((x - mx) ** 2 for x in xs)
    if den == 0:
        return None
    return num / den


def _rs(chunk: Sequence[float]) -> Optional[float]:
    n = len(chunk)
    if n < 2:
        return None
    mean = sum(chunk) / n
    cum = 0.0
    lo = math.inf
    hi = -math.inf
    for x in chunk:
        cum += x - mean
        lo = min(lo, cum)
        hi = max(hi, cum)
    rng = hi - lo
    s = math.sqrt(sum((x - mean) ** 2 for x in chunk) / n)
    if s == 0:
        return None
    return rng / s


def hurst_rs(series: Sequence[float], min_chunk: int = 8) -> Optional[float]:
    """أُسّ Hurst بطريقة rescaled-range (ميل log(R/S) مقابل log(n))."""
    x = list(series)
    n = len(x)
    if n < 2 * min_chunk:
        return None
    log_sizes: List[float] = []
    log_rs: List[float] = []
    size = min_chunk
    while size <= n // 2:
        k = n // size
        vals = []
        for j in range(k):
            rs = _rs(x[j * size:(j + 1) * size])
            if rs is not None and rs > 0:
                vals.append(rs)
        if vals:
            log_sizes.append(math.log(size))
            log_rs.append(math.log(sum(vals) / len(vals)))
        size *= 2
    if len(log_sizes) < 2:
        return None
    return _ols_slope(log_sizes, log_rs)


def variance_ratio(returns: Sequence[float], q: int = 2) -> Optional[float]:
    """Variance-Ratio VR(q): ≈1 عشوائي، >1 ثبات/اتجاه، <1 ارتداد."""
    if q < 2:
        raise ValueError("q يجب أن يكون ≥ 2")
    r = list(returns)
    n = len(r)
    if n < 2 * q:
        return None
    var1 = _sample_variance(r)
    if var1 == 0:
        return None
    k = n // q
    sums = [sum(r[i * q:(i + 1) * q]) for i in range(k)]
    if len(sums) < 2:
        return None
    varq = _sample_variance(sums)
    return varq / (q * var1)


# --------------------------- السيولة/السبريد ---------------------------

def spread_pct(bid: Optional[float], ask: Optional[float]) -> Optional[float]:
    """السبريد كنسبة مئوية من منتصف السعر، أو None عند غياب/لا صلاحية."""
    if bid is None or ask is None or bid <= 0 or ask <= 0 or ask < bid:
        return None
    mid = (bid + ask) / 2.0
    if mid <= 0:
        return None
    return (ask - bid) / mid * 100.0


def average_volume(candles: Sequence[Candle], quote: bool = False) -> Optional[float]:
    """متوسّط حجم التداول عبر النافذة. quote=True ⇒ تقدير حجم بالعملة المقابلة
    (volume × متوسّط (high+low+close)/3)."""
    cs = list(candles)
    if not cs:
        return None
    if not quote:
        return sum(c.volume for c in cs) / len(cs)
    acc = 0.0
    for c in cs:
        typical = (c.high + c.low + c.close) / 3.0
        acc += c.volume * typical
    return acc / len(cs)


@dataclass
class LiquidityState:
    avg_quote_volume: Optional[float]
    spread_pct: Optional[float]
    is_thin: bool
    is_wide_spread: bool

    @property
    def ok(self) -> bool:
        return not (self.is_thin or self.is_wide_spread)

    def to_dict(self) -> dict:
        return {
            "avgQuoteVolume": self.avg_quote_volume,
            "spreadPct": self.spread_pct,
            "isThin": self.is_thin,
            "isWideSpread": self.is_wide_spread,
            "ok": self.ok,
        }


def assess_liquidity(candles: Sequence[Candle],
                     bid: Optional[float] = None,
                     ask: Optional[float] = None,
                     min_quote_volume: Optional[float] = None,
                     max_spread_pct: Optional[float] = None) -> LiquidityState:
    """يقيس حالة السيولة/السبريد (قراءة فقط). الحدود اختيارية؛ غيابها ⇒ لا راية."""
    aqv = average_volume(candles, quote=True)
    sp = spread_pct(bid, ask)
    is_thin = (min_quote_volume is not None and aqv is not None
               and aqv < min_quote_volume)
    is_wide = (max_spread_pct is not None and sp is not None
               and sp > max_spread_pct)
    return LiquidityState(aqv, sp, bool(is_thin), bool(is_wide))


# ----------------------------- الملخّص -----------------------------

@dataclass
class RegimeSummary:
    n: int
    adx: Optional[float]
    plus_di: Optional[float]
    minus_di: Optional[float]
    choppiness: Optional[float]
    hurst: Optional[float]
    variance_ratio: Optional[float]

    @property
    def trend_strength(self) -> float:
        """قوّة الاتجاه في [0,1] من ADX (0 عند الغياب)."""
        if self.adx is None:
            return 0.0
        return _clamp(self.adx / 50.0, 0.0, 1.0)

    @property
    def adx_factor(self) -> float:
        """عامل scaling للطموح tp في [0.8, 1.3] (اتجاه أقوى ⇒ TP أطمح)."""
        return 0.8 + 0.5 * self.trend_strength

    @property
    def label(self) -> str:
        if self.adx is None:
            return "unknown"
        chop = self.choppiness
        if self.adx >= ADX_TREND_MIN and (chop is None or chop < CHOP_RANGE_MIN):
            return "trending"
        if (chop is not None and chop >= CHOP_RANGE_MIN) or self.adx < ADX_WEAK_MAX:
            return "ranging"
        return "transition"

    def to_dict(self) -> dict:
        return {
            "n": self.n,
            "adx": self.adx,
            "plusDi": self.plus_di,
            "minusDi": self.minus_di,
            "choppiness": self.choppiness,
            "hurst": self.hurst,
            "varianceRatio": self.variance_ratio,
            "trendStrength": self.trend_strength,
            "adxFactor": self.adx_factor,
            "label": self.label,
        }


def regime_summary(raw: Iterable, period: int = DEFAULT_PERIOD,
                   vr_q: int = 2) -> RegimeSummary:
    from ocobot.domain.volatility import closes, log_returns
    candles = as_candles(raw)
    dmi = adx_dmi(candles, period)
    rets = log_returns(closes(candles))
    try:
        vr = variance_ratio(rets, vr_q)
    except ValueError:
        vr = None
    return RegimeSummary(
        n=len(candles),
        adx=None if dmi is None else dmi[0],
        plus_di=None if dmi is None else dmi[1],
        minus_di=None if dmi is None else dmi[2],
        choppiness=choppiness_index(candles, period) if len(candles) > period else None,
        hurst=hurst_rs(rets),
        variance_ratio=vr,
    )
