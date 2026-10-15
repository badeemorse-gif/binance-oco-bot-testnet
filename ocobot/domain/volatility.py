"""مقدِّرات تقلّب خالصة للعملة (G1.56 · c1).

وحدة domain خالصة (بلا I/O ولا شبكة): تحسب مقاييس تقلّب من شموع OHLC
لاستخدامها لاحقًا في recommender لاقتراح tp_pct/sl_pct/trigger_pct.

- `atr_pct` (Wilder) = مقياس «العرض» الأساسي (نسبة مئوية من آخر إغلاق).
- `yang_zhang_vol` (OHLC) = المقدّر الأساسي للتقلّب لكل فترة؛ واحتياطًا
  Garman-Klass / Parkinson / Rogers-Satchell / إغلاق-لإغلاق.
- `ewma_vol` (RiskMetrics، λ≈0.94) + مئين التقلّب (`percentile_rank`).

ملاحظة وحدات: على خلاف أسعار/كميات التنفيذ (Decimal، §الدقة المالية)، هذه
مقدّرات إحصائية تُحسب بـ float (لوغاريتمات/جذور). النِّسب تُعاد كأرقام مئوية
(مثل 4.0 تعني 4%) تماشيًا مع اصطلاح pricing.compute_levels.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, List, NamedTuple, Optional, Sequence

DEFAULT_ATR_PERIOD = 14
DEFAULT_EWMA_LAMBDA = 0.94


class Candle(NamedTuple):
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


def _f(value) -> float:
    return value if isinstance(value, float) else float(value)


def as_candles(raw: Iterable) -> List[Candle]:
    """يحوّل مُدخلات متنوّعة إلى List[Candle] (float).

    يقبل: Candle؛ dict بمفاتيح open/high/low/close(/volume) أو o/h/l/c(/v)؛
    قائمة klines من Binance (الطول ≥ 6 ⇒ الفهارس 1..5)؛ أو tuple بطول 4 أو 5
    على الترتيب (open, high, low, close[, volume]).
    """
    out: List[Candle] = []
    for item in raw:
        if isinstance(item, Candle):
            out.append(item)
            continue
        if isinstance(item, dict):
            o = item.get("open", item.get("o"))
            h = item.get("high", item.get("h"))
            lo = item.get("low", item.get("l"))
            c = item.get("close", item.get("c"))
            v = item.get("volume", item.get("v", 0.0))
            out.append(Candle(_f(o), _f(h), _f(lo), _f(c), _f(v or 0.0)))
            continue
        if isinstance(item, (list, tuple)):
            n = len(item)
            if n >= 6:  # Binance kline: [openTime, o, h, l, c, v, ...]
                out.append(Candle(_f(item[1]), _f(item[2]), _f(item[3]),
                                  _f(item[4]), _f(item[5])))
            elif n == 5:
                out.append(Candle(_f(item[0]), _f(item[1]), _f(item[2]),
                                  _f(item[3]), _f(item[4])))
            elif n == 4:
                out.append(Candle(_f(item[0]), _f(item[1]), _f(item[2]),
                                  _f(item[3]), 0.0))
            else:
                raise ValueError(f"شكل شمعة غير مدعوم (طول={n})")
            continue
        raise ValueError(f"نوع شمعة غير مدعوم: {type(item)!r}")
    return out


def closes(candles: Sequence[Candle]) -> List[float]:
    return [c.close for c in candles]


def log_returns(values: Sequence[float]) -> List[float]:
    """عوائد لوغاريتمية إغلاق-لإغلاق؛ يتجاهل أي قيمة غير موجبة."""
    out: List[float] = []
    for prev, cur in zip(values, values[1:]):
        if prev > 0 and cur > 0:
            out.append(math.log(cur / prev))
    return out


# ----------------------------- ATR (Wilder) -----------------------------

def true_ranges(candles: Sequence[Candle]) -> List[float]:
    """True Range لكل شمعة بدءًا من الثانية (تحتاج إغلاق الشمعة السابقة)."""
    trs: List[float] = []
    for prev, cur in zip(candles, candles[1:]):
        tr = max(
            cur.high - cur.low,
            abs(cur.high - prev.close),
            abs(cur.low - prev.close),
        )
        trs.append(tr)
    return trs


def atr_wilder(candles: Sequence[Candle], period: int = DEFAULT_ATR_PERIOD) -> Optional[float]:
    """ATR مطلق بتنعيم Wilder. يتطلّب عدد شموع ≥ period+1، وإلا None."""
    if period <= 0:
        raise ValueError("period يجب أن يكون موجبًا")
    trs = true_ranges(candles)
    if len(trs) < period:
        return None
    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return atr


def atr_pct(candles: Sequence[Candle], period: int = DEFAULT_ATR_PERIOD) -> Optional[float]:
    """ATR كنسبة مئوية من آخر إغلاق (مقياس «العرض» الأساسي)."""
    atr = atr_wilder(candles, period)
    if atr is None:
        return None
    last = candles[-1].close
    if last <= 0:
        return None
    return atr / last * 100.0


# -------------------- مقدّرات تقلّب OHLC لكل فترة --------------------

def parkinson_vol(candles: Sequence[Candle]) -> Optional[float]:
    """تقلّب Parkinson (كسر لكل فترة) من المدى عالٍ/منخفض."""
    acc = 0.0
    n = 0
    k = 1.0 / (4.0 * math.log(2.0))
    for c in candles:
        if c.high > 0 and c.low > 0:
            r = math.log(c.high / c.low)
            acc += k * r * r
            n += 1
    if n == 0:
        return None
    return math.sqrt(acc / n)


def garman_klass_vol(candles: Sequence[Candle]) -> Optional[float]:
    """تقلّب Garman-Klass (كسر لكل فترة)."""
    acc = 0.0
    n = 0
    two_ln2_minus_1 = 2.0 * math.log(2.0) - 1.0
    for c in candles:
        if c.high > 0 and c.low > 0 and c.open > 0 and c.close > 0:
            hl = math.log(c.high / c.low)
            co = math.log(c.close / c.open)
            acc += 0.5 * hl * hl - two_ln2_minus_1 * co * co
            n += 1
    if n == 0:
        return None
    var = acc / n
    return math.sqrt(var) if var > 0 else 0.0


def rogers_satchell_vol(candles: Sequence[Candle]) -> Optional[float]:
    """تقلّب Rogers-Satchell (كسر لكل فترة، لا يتأثّر بالانجراف)."""
    acc = 0.0
    n = 0
    for c in candles:
        if c.high > 0 and c.low > 0 and c.open > 0 and c.close > 0:
            acc += (math.log(c.high / c.close) * math.log(c.high / c.open)
                    + math.log(c.low / c.close) * math.log(c.low / c.open))
            n += 1
    if n == 0:
        return None
    var = acc / n
    return math.sqrt(var) if var > 0 else 0.0


def yang_zhang_vol(candles: Sequence[Candle]) -> Optional[float]:
    """تقلّب Yang-Zhang (كسر لكل فترة): overnight + k·open + (1-k)·RS.

    يتطلّب ≥ 3 شموع (لحساب تباين العيّنة للجزأين). None عند النقص.
    """
    cs = list(candles)
    if len(cs) < 3:
        return None
    overnight: List[float] = []  # ln(O_i / C_{i-1})
    open_close: List[float] = []  # ln(C_i / O_i)
    rs: List[float] = []
    for prev, cur in zip(cs, cs[1:]):
        if min(prev.close, cur.open, cur.high, cur.low, cur.close) <= 0:
            continue
        overnight.append(math.log(cur.open / prev.close))
        open_close.append(math.log(cur.close / cur.open))
        rs.append(math.log(cur.high / cur.close) * math.log(cur.high / cur.open)
                  + math.log(cur.low / cur.close) * math.log(cur.low / cur.open))
    n = len(overnight)
    if n < 2:
        return None
    var_o = _sample_variance(overnight)
    var_c = _sample_variance(open_close)
    var_rs = sum(rs) / n
    k = 0.34 / (1.0 + (n + 1) / (n - 1))
    var_yz = var_o + k * var_c + (1.0 - k) * var_rs
    return math.sqrt(var_yz) if var_yz > 0 else 0.0


def close_to_close_vol(candles: Sequence[Candle]) -> Optional[float]:
    """الانحراف المعياري لعوائد الإغلاق اللوغاريتمية (كسر لكل فترة)."""
    rets = log_returns(closes(candles))
    if len(rets) < 2:
        return None
    return math.sqrt(_sample_variance(rets))


def _sample_variance(values: Sequence[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    return sum((x - mean) ** 2 for x in values) / (n - 1)


# ------------------------------- EWMA --------------------------------

def ewma_vol(returns: Sequence[float], lam: float = DEFAULT_EWMA_LAMBDA) -> Optional[float]:
    """تقلّب EWMA (RiskMetrics): σ²_t = λ·σ²_{t-1} + (1-λ)·r²_{t-1}.

    البذرة σ²_0 = r_0². يُعيد الجذر (كسر لكل فترة). None عند غياب العوائد.
    """
    if not 0.0 < lam < 1.0:
        raise ValueError("lam يجب أن يكون في (0,1)")
    if not returns:
        return None
    var = returns[0] ** 2
    for r in returns[1:]:
        var = lam * var + (1.0 - lam) * r * r
    return math.sqrt(var) if var > 0 else 0.0


def ewma_vol_from_candles(candles: Sequence[Candle],
                          lam: float = DEFAULT_EWMA_LAMBDA) -> Optional[float]:
    return ewma_vol(log_returns(closes(candles)), lam)


# ----------------------------- المئينات -----------------------------

def percentile(data: Sequence[float], q: float) -> Optional[float]:
    """المئين q∈[0,100] بالاستيفاء الخطّي (طريقة numpy الافتراضية)."""
    if not data:
        return None
    if not 0.0 <= q <= 100.0:
        raise ValueError("q يجب أن يكون في [0,100]")
    xs = sorted(data)
    if len(xs) == 1:
        return xs[0]
    pos = (q / 100.0) * (len(xs) - 1)
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return xs[lo]
    frac = pos - lo
    return xs[lo] * (1.0 - frac) + xs[hi] * frac


def percentile_rank(data: Sequence[float], value: float) -> Optional[float]:
    """ترتيب مئيني لـ value ضمن data كـ كسر في [0,1] (≤ value / n)."""
    if not data:
        return None
    count = sum(1 for x in data if x <= value)
    return count / len(data)


# --------------------------- الملخّص المجمَّع ---------------------------

@dataclass
class VolatilitySummary:
    n: int
    last_close: Optional[float]
    atr_abs: Optional[float]
    atr_pct: Optional[float]
    yang_zhang: Optional[float]
    garman_klass: Optional[float]
    parkinson: Optional[float]
    rogers_satchell: Optional[float]
    close_to_close: Optional[float]
    ewma: Optional[float]

    @property
    def per_period_vol(self) -> Optional[float]:
        """أفضل مقدّر تقلّب لكل فترة متاح (YZ ⇒ GK ⇒ Parkinson ⇒ C2C)."""
        for v in (self.yang_zhang, self.garman_klass,
                  self.parkinson, self.close_to_close):
            if v is not None:
                return v
        return None

    @property
    def per_period_vol_pct(self) -> Optional[float]:
        v = self.per_period_vol
        return None if v is None else v * 100.0

    def to_dict(self) -> dict:
        return {
            "n": self.n,
            "lastClose": self.last_close,
            "atrAbs": self.atr_abs,
            "atrPct": self.atr_pct,
            "yangZhang": self.yang_zhang,
            "garmanKlass": self.garman_klass,
            "parkinson": self.parkinson,
            "rogersSatchell": self.rogers_satchell,
            "closeToClose": self.close_to_close,
            "ewma": self.ewma,
            "perPeriodVolPct": self.per_period_vol_pct,
        }


def volatility_summary(raw: Iterable,
                       atr_period: int = DEFAULT_ATR_PERIOD,
                       ewma_lambda: float = DEFAULT_EWMA_LAMBDA) -> VolatilitySummary:
    """يجمع كل المقدّرات في بنية واحدة (كل حقل Optional عند نقص البيانات)."""
    candles = as_candles(raw)
    return VolatilitySummary(
        n=len(candles),
        last_close=candles[-1].close if candles else None,
        atr_abs=atr_wilder(candles, atr_period),
        atr_pct=atr_pct(candles, atr_period),
        yang_zhang=yang_zhang_vol(candles),
        garman_klass=garman_klass_vol(candles),
        parkinson=parkinson_vol(candles),
        rogers_satchell=rogers_satchell_vol(candles),
        close_to_close=close_to_close_vol(candles),
        ewma=ewma_vol_from_candles(candles, ewma_lambda),
    )
