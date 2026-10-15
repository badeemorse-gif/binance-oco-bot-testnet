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
                                side: str = LONG,
                                htf_candles=None, ltf_candles=None) -> Optional[Recommendation]:
    """يحسب Recommendation من شموع (Candle list أو صفوف klines خام)؛ None لو تعذّر.

    as_candles مُحايد للتكرار (يمرّر Candle كما هو)، ودوال التلخيص تستدعيه داخليًا.
    reference_price الافتراضي = إغلاق آخر شمعة. يُعيد None عند غياب الشموع أو تعذّر
    توفّر أي مُدخل أساسي (recommend نفسها تُعيد None حينها).

    - htf_candles (اختياري، 1h): منها htf_regime (adx_factor) و htf_atr_pct (اختبار
      الهدوء في فرع السكالبنج). غيابها ⇒ السلوك الحالي بلا تغيير.
    - ltf_candles (اختياري، 1m): منها ltf_atr_pct (أرضية الضوضاء).
    """
    rows = as_candles(candles) if candles is not None else []
    if not rows:
        return None
    vol = volatility_summary(rows, atr_period=atr_period)
    exc = excursion_stats(rows, horizon=horizon, side=side)
    reg = regime_summary(rows, period=atr_period)
    ref = reference_price if reference_price is not None else rows[-1].close

    htf_regime = None
    htf_atr_pct = None
    if htf_candles is not None:
        htf_rows = as_candles(htf_candles)
        if htf_rows:
            htf_regime = regime_summary(htf_rows, period=atr_period)
            htf_atr_pct = volatility_summary(htf_rows, atr_period=atr_period).atr_pct
    ltf_atr_pct = None
    if ltf_candles is not None:
        ltf_rows = as_candles(ltf_candles)
        if ltf_rows:
            ltf_atr_pct = volatility_summary(ltf_rows, atr_period=atr_period).atr_pct

    return recommend(vol, exc, reg, filters, ref, params=params,
                     htf_regime=htf_regime, ltf_atr_pct=ltf_atr_pct,
                     htf_atr_pct=htf_atr_pct)


def make_recommendation_provider(candles_fn: Callable, *,
                                 symbol_fn: Optional[Callable] = None,
                                 filters_fn: Optional[Callable] = None,
                                 params=None,
                                 atr_period: int = DEFAULT_ATR_PERIOD,
                                 horizon: int = DEFAULT_HORIZON,
                                 side: str = LONG,
                                 htf_candles_fn: Optional[Callable] = None,
                                 ltf_candles_fn: Optional[Callable] = None
                                 ) -> Callable[[], Optional[Recommendation]]:
    """يُعيد دالة بلا وسائط تُنتج Recommendation (أو None) — تُسلَّم إلى runner.submit.

    - symbol_fn (اختياري): يُعيد الرمز المختار حاليًا؛ None/فارغ ⇒ تُعيد الدالة None
      بلا أي نداء على candles_fn (تفادي الجلب بلا رمز).
    - candles_fn: تُستدعى بـ symbol عند توفّر symbol_fn، وإلا بلا وسائط.
    - filters_fn (اختياري): symbol ⇒ SymbolFilters للقصّ على فلاتر العملة.
    - htf_candles_fn / ltf_candles_fn (اختياري): شموع فريم أعلى (1h) / أدنى (1m)
      للمعايرة الهرمية؛ غيابها ⇒ السلوك الحالي بلا تغيير. تُستدعى كـ candles_fn
      (بـ symbol عند توفّر symbol_fn، وإلا بلا وسائط).
    """
    def _call(fn, symbol):
        if not callable(fn):
            return None
        return fn(symbol) if callable(symbol_fn) else fn()

    def _provider() -> Optional[Recommendation]:
        symbol = symbol_fn() if callable(symbol_fn) else None
        if callable(symbol_fn) and not symbol:
            return None
        # نجلب الفريمات الهرمية (HTF/LTF) أوّلًا ثم الأساس أخيرًا، فيبقى آخر نداء
        # get_candles هو فريم الأساس (توافق رجعي مع متوقّعات المتصلين/الاختبارات).
        filters = filters_fn(symbol) if callable(filters_fn) else None
        htf_candles = _call(htf_candles_fn, symbol)
        ltf_candles = _call(ltf_candles_fn, symbol)
        candles = candles_fn(symbol) if callable(symbol_fn) else candles_fn()
        return recommendation_from_candles(
            candles, filters=filters, params=params,
            atr_period=atr_period, horizon=horizon, side=side,
            htf_candles=htf_candles, ltf_candles=ltf_candles)

    return _provider
