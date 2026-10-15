"""معايرة/Backtest بأسلوب Walk-Forward (G1.56 · c8) — خالص.

يعيد استخدام منطق النِّسب (recommender) خارج العيّنة: يعاير على نافذة تدريب ثم
يقيس على نافذة اختبار **لاحقة** مقياسين يخدمان الهدف:
  - early_exit_rate: نسبة الصفقات التي خرجت وهي تلتقط أقلّ من حصّة معتبرة من
    أقصى حركة مُواتية متاحة (MFE) ⇒ «خروج مبكر».
  - avg_mfe_capture: متوسّط نسبة الحركة المُواتية الملتقَطة من MFE.

نموذج الخروج تبسيط أمين (TP/SL) لقياس «عدم الخروج المبكر»؛ منطق التموضع/التتبّع
الكامل خارج هذا المقياس (لا hot_path). كل الحساب float إحصائيًا وبلا شبكة.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence

from ocobot.domain.excursion import LONG, SHORT, _check_side
from ocobot.domain.volatility import Candle, as_candles

DEFAULT_EARLY_CAPTURE_FRAC = 0.5


@dataclass
class TradeResult:
    exit_reason: str          # tp|sl|time
    outcome_pct: float
    potential_mfe_pct: float
    captured_favorable_pct: float
    mfe_capture: float        # [0,1]
    early_exit: bool
    bars: int


def simulate_trade(entry: float, highs: Sequence[float], lows: Sequence[float],
                   closes: Sequence[float], tp_pct: float, sl_pct: float,
                   side: str = LONG,
                   early_capture_frac: float = DEFAULT_EARLY_CAPTURE_FRAC) -> Optional[TradeResult]:
    """يحاكي صفقة واحدة على نافذة أمامية بنموذج TP/SL (SL أولًا عند التعادل)."""
    side = _check_side(side)
    if entry <= 0 or not highs:
        return None
    n = len(highs)
    if side == LONG:
        tp_price = entry * (1.0 + tp_pct / 100.0)
        sl_price = entry * (1.0 - sl_pct / 100.0)
    else:
        tp_price = entry * (1.0 - tp_pct / 100.0)
        sl_price = entry * (1.0 + sl_pct / 100.0)

    exit_reason = "time"
    outcome = 0.0
    bars = n
    for k in range(n):
        hi, lo = highs[k], lows[k]
        if side == LONG:
            hit_sl = lo <= sl_price
            hit_tp = hi >= tp_price
        else:
            hit_sl = hi >= sl_price
            hit_tp = lo <= tp_price
        if hit_sl:  # تحفّظ: SL أولًا عند حدوثهما بالشمعة نفسها
            exit_reason, outcome, bars = "sl", -sl_pct, k + 1
            break
        if hit_tp:
            exit_reason, outcome, bars = "tp", tp_pct, k + 1
            break
    else:
        last = closes[-1] if closes else entry
        outcome = ((last / entry - 1.0) if side == LONG
                   else (1.0 - last / entry)) * 100.0

    if side == LONG:
        potential = max(0.0, (max(highs) / entry - 1.0) * 100.0)
    else:
        potential = max(0.0, (1.0 - min(lows) / entry) * 100.0)
    captured = max(0.0, outcome)
    mfe_capture = 1.0 if potential <= 0 else min(1.0, captured / potential)
    early_exit = potential > 0 and captured < early_capture_frac * potential
    return TradeResult(exit_reason, outcome, potential, captured,
                       mfe_capture, early_exit, bars)


def collect_trades(raw: Iterable, tp_pct: float, sl_pct: float, horizon: int,
                   side: str = LONG, step: int = 1,
                   early_capture_frac: float = DEFAULT_EARLY_CAPTURE_FRAC) -> List[TradeResult]:
    side = _check_side(side)
    if horizon <= 0 or step <= 0:
        raise ValueError("horizon/step يجب أن يكونا موجبين")
    candles = as_candles(raw)
    trades: List[TradeResult] = []
    last_start = len(candles) - horizon - 1
    i = 0
    while i <= last_start:
        entry = candles[i].close
        window = candles[i + 1: i + 1 + horizon]
        tr = simulate_trade(entry, [c.high for c in window], [c.low for c in window],
                            [c.close for c in window], tp_pct, sl_pct, side,
                            early_capture_frac)
        if tr is not None:
            trades.append(tr)
        i += step
    return trades


@dataclass
class BacktestMetrics:
    n_trades: int
    early_exit_rate: Optional[float]
    avg_mfe_capture: Optional[float]
    avg_outcome_pct: Optional[float]
    tp_rate: Optional[float]
    sl_rate: Optional[float]
    time_rate: Optional[float]

    def to_dict(self) -> dict:
        return {
            "nTrades": self.n_trades,
            "earlyExitRate": self.early_exit_rate,
            "avgMfeCapture": self.avg_mfe_capture,
            "avgOutcomePct": self.avg_outcome_pct,
            "tpRate": self.tp_rate,
            "slRate": self.sl_rate,
            "timeRate": self.time_rate,
        }


def metrics_from_trades(trades: Sequence[TradeResult]) -> BacktestMetrics:
    n = len(trades)
    if n == 0:
        return BacktestMetrics(0, None, None, None, None, None, None)
    early = sum(1 for t in trades if t.early_exit) / n
    cap = sum(t.mfe_capture for t in trades) / n
    out = sum(t.outcome_pct for t in trades) / n
    tp = sum(1 for t in trades if t.exit_reason == "tp") / n
    sl = sum(1 for t in trades if t.exit_reason == "sl") / n
    tm = sum(1 for t in trades if t.exit_reason == "time") / n
    return BacktestMetrics(n, early, cap, out, tp, sl, tm)


def evaluate_policy(raw: Iterable, tp_pct: float, sl_pct: float, horizon: int,
                    side: str = LONG, step: int = 1,
                    early_capture_frac: float = DEFAULT_EARLY_CAPTURE_FRAC) -> BacktestMetrics:
    return metrics_from_trades(
        collect_trades(raw, tp_pct, sl_pct, horizon, side, step, early_capture_frac))


@dataclass
class WalkForwardResult:
    folds: int
    recommended: BacktestMetrics
    baseline: Optional[BacktestMetrics]
    params: dict

    def to_dict(self) -> dict:
        return {
            "folds": self.folds,
            "recommended": self.recommended.to_dict(),
            "baseline": None if self.baseline is None else self.baseline.to_dict(),
            "params": dict(self.params),
        }


def _calibrate(train_candles, horizon, side, params, atr_period, vr_q):
    """يعاير اقتراح النِّسب على نافذة التدريب؛ يُعيد (tp_pct, sl_pct) float أو None."""
    from ocobot.domain.excursion import excursion_stats
    from ocobot.domain.recommender import recommend
    from ocobot.domain.regime import regime_summary
    from ocobot.domain.volatility import volatility_summary
    vol = volatility_summary(train_candles, atr_period=atr_period)
    exc = excursion_stats(train_candles, horizon=horizon, side=side)
    reg = regime_summary(train_candles, period=atr_period, vr_q=vr_q)
    ref = train_candles[-1].close if train_candles else 0.0
    rec = recommend(vol, exc, reg, None, ref, params=params)
    if rec is None:
        return None
    return float(rec.tp_pct), float(rec.sl_pct)


def walk_forward(raw: Iterable, train_size: int, test_size: int, horizon: int,
                 side: str = LONG, step: int = 1, params=None,
                 baseline: Optional[tuple] = None, atr_period: int = 14,
                 vr_q: int = 2,
                 early_capture_frac: float = DEFAULT_EARLY_CAPTURE_FRAC) -> WalkForwardResult:
    """تقييم Walk-Forward: معايرة على التدريب ⇒ قياس على اختبار لاحق (مجمَّع)."""
    from ocobot.domain.recommender import RecommenderParams
    side = _check_side(side)
    if train_size <= 0 or test_size <= 0 or horizon <= 0:
        raise ValueError("train_size/test_size/horizon يجب أن تكون موجبة")
    params = params or RecommenderParams()
    candles = as_candles(raw)
    rec_trades: List[TradeResult] = []
    base_trades: List[TradeResult] = []
    folds = 0
    s = 0
    while s + train_size + test_size <= len(candles):
        train = candles[s:s + train_size]
        test = candles[s + train_size:s + train_size + test_size]
        calib = _calibrate(train, horizon, side, params, atr_period, vr_q)
        if calib is not None:
            folds += 1
            tp, sl = calib
            rec_trades.extend(collect_trades(test, tp, sl, horizon, side, step,
                                             early_capture_frac))
            if baseline is not None:
                b_tp, b_sl = baseline
                base_trades.extend(collect_trades(test, b_tp, b_sl, horizon, side,
                                                  step, early_capture_frac))
        s += test_size

    return WalkForwardResult(
        folds=folds,
        recommended=metrics_from_trades(rec_trades),
        baseline=(metrics_from_trades(base_trades) if baseline is not None else None),
        params={"trainSize": train_size, "testSize": test_size,
                "horizon": horizon, "side": side, "step": step,
                "baseline": baseline},
    )
