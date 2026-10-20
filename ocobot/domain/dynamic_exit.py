# -*- coding: utf-8 -*-
"""الخروج المتكيّف (G1.65) — تطبيق إنتاجي مُعلَّم لمخرجات مسار التجارب G1.64.

وحدة domain خالصة (بلا I/O ولا شبكة ولا Qt): تجسّد **صيغة الخروج المُتحقَّقة forward**
(EXP-021→EXP-024C داخل G1.64، بوّابة forward W3 = MET) للتتبّع المتكيّف مع حجم الموجة
«wave_adaptive» + رافعة القفل «lock_base». منقولة حرفيًّا من منطق
``backtest_lab/g1_64_ratio_filter/exp_021_run.py::resim_1m_wave`` (الخطوة 3):

    مسافة التتبّع%   = clamp(wave_k · ATR%_live(atr_win، على القمّة), dist_min, dist_max)
    أرضية القفل      = lf = min(lock_cap, lock_base + lock_slope · g)   (عند g > 0)
    سعر أرضية القفل  = fill · (1 + lf · g / 100)            # g = نسبة الركضة% من الدخول إلى القمّة
    الستوب (رتيب)    = max(prev_stop, peak·(1 − dist/100), سعر أرضية القفل, قفل BE بعد BE_TRIGGER)

البروتوكول wadapt_tight هو البطل المُتحقَّق؛ القيمة الافتراضية لـ``lock_base`` هنا **0.80**
(قرار G1.65 الاحترافي: قويّة ومُتحقَّقة forward دون تبنّي حافة 0.95). كل القيم قابلة للضبط.

**لا تُغيِّر هذه الوحدة أيّ سلوك تلقائيًّا**: إنّها دوال خالصة + إعداد ``DynamicExitConfig``
افتراضه ``enabled=False`` و ``recommender_profile="baseline"`` (= السلوك الحالي تمامًا). وصل
المنطق في حلقة reposition/monitoring الحيّة متروك لمرحلة لاحقة (increment #2) خلف هذا الـflag.
لا hot_path، لا Live/testnet، لا رأس مال.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Optional, Sequence

from ocobot.domain.recommender import RecommenderParams


@dataclass(frozen=True)
class WaveAdaptiveParams:
    """معاملات التتبّع المتكيّف wave_adaptive (بروتوكول wadapt_tight، lock_base=0.80 لـG1.65)."""
    atr_win: int = 10
    wave_k: float = 1.5
    dist_min: float = 0.5
    dist_max: float = 3.0
    lock_base: float = 0.80       # G1.65: 0.80 (البطل التجريبي كان 0.60؛ انظر wadapt_tight_backtest)
    lock_slope: float = 0.040
    lock_cap: float = 0.88
    be_trigger_pct: float = 1.0   # من EXP-019 (BE_TRIGGER)
    be_buffer_pct: float = 0.30   # من EXP-019 (BE_BUFFER)


# البروتوكول الافتراضي لـG1.65 (lock_base=0.80).
WADAPT_TIGHT = WaveAdaptiveParams()

# نسخة مطابقة لبطل التجارب حرفيًّا (lock_base=0.60) — لتثبيت التكافؤ مع exp_021_run في الاختبارات.
WADAPT_TIGHT_BACKTEST = WaveAdaptiveParams(lock_base=0.60)

# بروفايل بطل المُرشِّح المُتحقَّق forward (EXP-009→EXP-024C): legacy + k_sl=5.0 + trigger_f=0.15.
CHAMPION_RECOMMENDER = RecommenderParams(k_sl=5.0, trigger_f=0.15, objective="legacy")


def trail_distance_pct(live_atr_pct: float, p: WaveAdaptiveParams = WADAPT_TIGHT) -> float:
    """مسافة التتبّع% = clamp(wave_k · ATR%_live, dist_min, dist_max)."""
    dist = p.wave_k * float(live_atr_pct)
    if dist < p.dist_min:
        return p.dist_min
    if dist > p.dist_max:
        return p.dist_max
    return dist


def lock_floor_frac(run_up_pct: float, p: WaveAdaptiveParams = WADAPT_TIGHT) -> float:
    """حصّة الموجة المقفولة lf = min(lock_cap, lock_base + lock_slope · g). صفر عند g ≤ 0."""
    g = float(run_up_pct)
    if g <= 0:
        return 0.0
    lf = p.lock_base + p.lock_slope * g
    if lf > p.lock_cap:
        return p.lock_cap
    return lf


def live_atr_pct(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float],
                 atr_win: int, ref: float) -> float:
    """ATR٪ حيّ سببي: متوسّط المدى الحقيقي لآخر atr_win شمعة ÷ ref (القمّة) ×100.

    يطابق ``exp_021_run._live_atr_pct``: المدى الحقيقي = max(hi−lo, |hi−pc|, |lo−pc|)
    حيث pc = إغلاق الشمعة السابقة. يُعيد 0.0 عند غياب بيانات كافية أو ref ≤ 0.
    """
    n = len(highs)
    if n == 0 or ref <= 0 or atr_win <= 0:
        return 0.0
    k = n - 1
    start = k - atr_win + 1
    if start < 1:
        start = 1
    pc = closes[start - 1]
    s = 0.0
    c = 0
    for i in range(start, k + 1):
        hi, lo, cl = highs[i], lows[i], closes[i]
        tr = hi - lo
        d1 = hi - pc if hi >= pc else pc - hi
        d2 = lo - pc if lo >= pc else pc - lo
        if d1 > tr:
            tr = d1
        if d2 > tr:
            tr = d2
        s += tr
        c += 1
        pc = cl
    if c == 0:
        return 0.0
    return 100.0 * (s / c) / ref


def next_stop(fill: float, peak: float, prev_stop: float, live_atr_pct_value: float,
              p: WaveAdaptiveParams = WADAPT_TIGHT) -> float:
    """الستوب المتحرّك الرتيب الجديد (مطابق للخطوة 3 في exp_021_run.resim_1m_wave).

    - chandelier: peak·(1 − dist/100)
    - أرضية القفل: fill·(1 + lf·g/100) عند g>0
    - أرضية BE: fill·(1 + be_buffer/100) متى بلغت القمّة fill·(1 + be_trigger/100)
    - رتيب: لا ينزل أبدًا تحت prev_stop.
    """
    if fill <= 0:
        return prev_stop
    g = (peak / fill - 1.0) * 100.0
    dist = trail_distance_pct(live_atr_pct_value, p)
    ns = peak * (1.0 - dist / 100.0)
    if g > 0:
        lf = lock_floor_frac(g, p)
        if lf > 0:
            floor = fill * (1.0 + (lf * g) / 100.0)
            if floor > ns:
                ns = floor
    be_trigger_price = fill * (1.0 + p.be_trigger_pct / 100.0)
    be_lock_price = fill * (1.0 + p.be_buffer_pct / 100.0)
    if peak >= be_trigger_price and be_lock_price > ns:
        ns = be_lock_price
    return ns if ns > prev_stop else prev_stop


def shadow_divergence(reference, peak, prev_stop, live_atr_pct_value,
                      current_sl_pct, p: WaveAdaptiveParams = WADAPT_TIGHT) -> dict:
    """سجلّ شادو (حساب خالص، بلا أثر): ماذا كان الخروج التكيّف سيفعل مقابل الحالي.

    يطابق صيغة ``reposition.SafeExecutor.build_draft`` عند التفعيل (fill = reference):
    ``eff_sl_pct = (1 − next_stop(reference, peak, prev_stop, atr)/reference)·100``.
    يُعيد قاموسًا JSON-safe للمقارنة/التسجيل (divergence_pct = التكيّف − الحالي).
    """
    ref = float(reference)
    atr = float(live_atr_pct_value)
    ns = next_stop(ref, float(peak), float(prev_stop), atr, p)
    adaptive_eff_sl_pct = (1.0 - ns / ref) * 100.0 if ref > 0 else None
    cur = float(current_sl_pct)
    divergence = (adaptive_eff_sl_pct - cur) if adaptive_eff_sl_pct is not None else None
    return {
        "live_atr_pct": atr,
        "trail_dist_pct": trail_distance_pct(atr, p),
        "reference": ref,
        "peak": float(peak),
        "prev_stop": float(prev_stop),
        "adaptive_next_stop": ns,
        "adaptive_eff_sl_pct": adaptive_eff_sl_pct,
        "current_sl_pct": cur,
        "divergence_pct": divergence,
    }


def recommender_profile(name: str = "baseline") -> Optional[RecommenderParams]:
    """بروفايل المُرشِّح: ``"baseline"`` ⇒ None (لا تجاوز — يُبقي افتراض موقع النداء كما هو)،
    ``"champion"`` ⇒ نسخة من CHAMPION_RECOMMENDER (k_sl=5.0, trigger_f=0.15, legacy)."""
    if name == "baseline":
        return None
    if name == "champion":
        return replace(CHAMPION_RECOMMENDER)
    raise ValueError(f"unknown recommender_profile: {name!r}")


@dataclass(frozen=True)
class DynamicExitConfig:
    """إعداد G1.65 — الافتراضي = السلوك الحالي تمامًا (معطّل)."""
    enabled: bool = False
    preset: str = "wadapt_tight"
    lock_base: float = 0.80
    recommender_profile: str = "baseline"

    def params(self) -> WaveAdaptiveParams:
        """WaveAdaptiveParams الفعّالة (البروتوكول مع تجاوز lock_base من الإعداد)."""
        if self.preset == "wadapt_tight":
            return replace(WADAPT_TIGHT, lock_base=self.lock_base)
        raise ValueError(f"unknown preset: {self.preset!r}")

    def recommender(self) -> Optional[RecommenderParams]:
        """بروفايل المُرشِّح الفعّال (None = بلا تجاوز)."""
        return recommender_profile(self.recommender_profile)
