# -*- coding: utf-8 -*-
"""مزوّد اقتراح النِّسب (G1.60): candles/klines ⇒ recommender ⇒ Recommendation.

وحدة domain خالصة (بلا Qt، وبلا شبكة مباشرة هنا): تُجمِّع خط أنابيب التلخيص
(volatility_summary + excursion_stats + regime_summary) ثم recommend، وتوفّر مصنعًا
لدالة بلا وسائط تُسلَّم إلى AsyncRunner.submit من شاشة المراقبة؛ الشبكة — إن وُجدت —
تمرّ عبر عميل محقون (مثل KlinesService) خارج خيط Qt. اقتراح عرض/تتبّع فقط:
لا hot_path ولا تنفيذ Live فعلي (ليست T16).

تُعيد استخدام خط الأنابيب نفسه المستعمَل في domain/backtest._calibrate (نفس الدوال
والافتراضات) فلا تكرار لمنطق التلخيص.
"""
from __future__ import annotations

from typing import Callable, Optional

from ocobot.domain.excursion import LONG, excursion_stats
from ocobot.domain.recommender import Recommendation, recommend
from ocobot.domain.regime import regime_summary
from ocobot.domain.volatility import as_candles, volatility_summary

DEFAULT_ATR_PERIOD = 14
DEFAULT_HORIZON = 24


def recommendation_from_candles(candles, *, filters=None, reference_price=None,
                                params=None, atr_period: int = DEFAULT_ATR_PERIOD,
                                horizon: int = DEFAULT_HORIZON,
                                side: str = LONG) -> Optional[Recommendation]:
    """يحسب Recommendation من شموع (Candle list أو صفوف klines خام)؛ None لو تعذّر.

    as_candles مُحايد للتكرار (يمرّر Candle كما هو)، ودوال التلخيص تستدعيه داخليًا.
    reference_price الافتراضي = إغلاق آخر شمعة. يُعيد None عند غياب الشموع أو تعذّر
    توفّر أي مُدخل أساسي (recommend نفسها تُعيد None حينها).
    """
    rows = as_candles(candles) if candles is not None else []
    if not rows:
        return None
    vol = volatility_summary(rows, atr_period=atr_period)
    exc = excursion_stats(rows, horizon=horizon, side=side)
    reg = regime_summary(rows, period=atr_period)
    ref = reference_price if reference_price is not None else rows[-1].close
    return recommend(vol, exc, reg, filters, ref, params=params)


def make_recommendation_provider(candles_fn: Callable, *,
                                 symbol_fn: Optional[Callable] = None,
                                 filters_fn: Optional[Callable] = None,
                                 params=None,
                                 atr_period: int = DEFAULT_ATR_PERIOD,
                                 horizon: int = DEFAULT_HORIZON,
                                 side: str = LONG) -> Callable[[], Optional[Recommendation]]:
    """يُعيد دالة بلا وسائط تُنتج Recommendation (أو None) — تُسلَّم إلى runner.submit.

    - symbol_fn (اختياري): يُعيد الرمز المختار حاليًا؛ None/فارغ ⇒ تُعيد الدالة None
      بلا أي نداء على candles_fn (تفادي الجلب بلا رمز).
    - candles_fn: تُستدعى بـ symbol عند توفّر symbol_fn، وإلا بلا وسائط.
    - filters_fn (اختياري): symbol ⇒ SymbolFilters للقصّ على فلاتر العملة.
    """
    def _provider() -> Optional[Recommendation]:
        symbol = symbol_fn() if callable(symbol_fn) else None
        if callable(symbol_fn) and not symbol:
            return None
        candles = candles_fn(symbol) if callable(symbol_fn) else candles_fn()
        filters = filters_fn(symbol) if callable(filters_fn) else None
        return recommendation_from_candles(
            candles, filters=filters, params=params,
            atr_period=atr_period, horizon=horizon, side=side)

    return _provider
