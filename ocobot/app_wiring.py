"""OCOBot non-ui wiring helpers (G1.8).

وحدة تجميع غير-ui: تبني موفّر السعر الذي تحتاجه الواجهة دون أن تقع تحت
حارس الشبكة الخاص بطبقة ui. تعيد استخدام ``_build_feed`` من ``ocobot.cli``
(النقل الفعلي WS+REST يبقى هناك) ولا تحتوي على أي بدائيات شبكة مباشرة.
"""
from __future__ import annotations

import logging

from ocobot.cli import _build_feed

_LOG = logging.getLogger("ocobot.dynamic_exit")


class SelectionPriceProvider:
    """موفّر سعر يتتبّع رمز الأمر المختار (Testnet). get_price() بلا وسائط، ويعيد بناء PriceFeedController عند تغيّر الرمز."""

    def __init__(self, cfg, client):
        self._cfg = cfg
        self._client = client
        self._symbol = None
        self._feed = None

    def set_symbol(self, symbol):
        if symbol and symbol != self._symbol:
            self._symbol = symbol
            self._feed = _build_feed(self._cfg, self._client, symbol)

    @property
    def mode(self):
        return getattr(self._feed, "mode", None)

    def get_price(self):
        if self._feed is None:
            return None
        return self._feed.get_price()

    def __call__(self):
        return self.get_price()

class BtcPriceProvider:
    """موفّر سعر BTCUSDT حيّ (Testnet، قراءة فقط) مستقلّ عن وضع الحارس — fail-safe."""

    def __init__(self, cfg, client, symbol="BTCUSDT"):
        self._cfg = cfg
        self._client = client
        self._symbol = symbol
        self._feed = None

    def _ensure(self):
        if self._feed is None:
            try:
                self._feed = _build_feed(self._cfg, self._client, self._symbol)
            except Exception:
                self._feed = None

    @property
    def mode(self):
        return getattr(self._feed, "mode", None)

    def get_price(self):
        try:
            self._ensure()
            return self._feed.get_price() if self._feed is not None else None
        except Exception:
            return None

    def __call__(self):
        return self.get_price()


from ocobot.domain.exchange_info import ExchangeInfoService
from ocobot.domain.convert import ConvertExecutor


def build_convert_executor(client, audit=None):
    # G1.13: build a ConvertExecutor (mirror cli._build_executor)
    return ConvertExecutor(client, ExchangeInfoService(client), audit=audit)


def make_convert_cb(convert_executor, price_provider):
    # G1.13: convert_cb fetches a fresh LIVE price (D14) when reference_price is missing,
    # then delegates to ConvertExecutor.convert. No network here (price_provider is injected).
    def convert_cb(source, tp_pct, sl_pct, reference_price=None, dry_run=False):
        if reference_price is None or (isinstance(reference_price, str) and not reference_price.strip()):
            if hasattr(price_provider, "set_symbol"):
                price_provider.set_symbol(source.symbol)
            price = price_provider.get_price()
            if price is None:
                raise ValueError("LIVE_PRICE_UNAVAILABLE: تعذّر جلب السعر الحيّ (D14)")
            reference_price = price
        return convert_executor.convert(source, tp_pct, sl_pct, reference_price, dry_run=dry_run)
    return convert_cb


from ocobot.domain.completed_trades import build_fill_recorder


def make_fill_recorder_order_event(audit, prior_on_order_event=None):
    """G1.52: يبني ``on_order_event`` جاهزًا للحقن في ``UserDataStreamConsumer``.

    يلتقط أيّ تعبئة بيع (``executionReport`` بحالة ``FILLED`` و ``S == SELL``،
    سواء OCO أو أمر مستقل ``g == -1``) ويكتب ``trade_closed_fill`` append-only عبر
    ``audit``، مع الحفاظ على أيّ معالِج سابق (``prior_on_order_event``) يُنادى لكل
    حدث. تكامل opt-in بحت: ``prior_on_order_event=None`` سليم، ولا شبكة ولا hot_path.

    الاستعمال عند نقطة تجميع تُنشئ المستهلك:
        consumer = UserDataStreamConsumer(
            ..., on_order_event=make_fill_recorder_order_event(audit, prior),
        )
    """
    return build_fill_recorder(audit, prior_on_order_event)


def build_recommendation_provider(klines_service, symbol_fn, *, interval="5m",
                                  limit=1000, filters_fn=None, params=None,
                                  atr_period=14, horizon=24,
                                  htf_interval="1h", htf_limit=500,
                                  ltf_interval="1m", ltf_limit=200, profile=None):
    """G1.60/G1.61: يبني دالة اقتراح نِسب بلا وسائط (تُسلَّم إلى runner.submit) فوق KlinesService.

    الشبكة (GET /api/v3/klines) تمرّ عبر العميل المُحقَن داخل KlinesService، وتُنفَّذ
    خارج خيط Qt عبر الرَنَر. symbol_fn يُعيد الرمز المختار حاليًا (أو None/فارغ ⇒ لا
    اقتراح وبلا نداء شبكة). لا hot_path ولا تنفيذ Live فعلي (ليست T16).

    G1.61 (معايرة السكالبنج): الأساس 5m (limit=1000, horizon=24) + سياق HTF 1h
    (limit≈500) + ضوضاء LTF 1m (limit≈200). عند غياب params يُبنى افتراض السكالبنج
    (objective=\"scalp\", c=0.25%, R=2, باند هادئ [0.3,0.9] عند 1h ATR%<0.6). التوقيع
    متوافق رجعيًا (كل الجديد kwargs بقيم افتراضية).
    """
    from ocobot.domain.rec_provider import make_recommendation_provider
    from ocobot.domain.recommender import RecommenderParams

    # G1.65 (opt-in): profile="champion" ⇒ بطل المُرشِّح المُتحقَّق forward (k_sl=5.0,
    # trigger_f=0.15, legacy). الافتراضي profile=None ⇒ بلا تغيير (يُبقى افتراض السكالبنج أدناه).
    if params is None and profile == "champion":
        from ocobot.domain.dynamic_exit import recommender_profile
        params = recommender_profile("champion")
    if params is None:
        params = RecommenderParams(
            objective="scalp", round_trip_cost_pct=0.25, rr_target=2.0,
            quiet_atr_pct=0.6, quiet_band_lo=0.3, quiet_band_hi=0.9)

    def _candles_fn(symbol):
        return klines_service.get_candles(symbol, interval=interval, limit=limit)

    def _htf_candles_fn(symbol):
        return klines_service.get_candles(symbol, interval=htf_interval, limit=htf_limit)

    def _ltf_candles_fn(symbol):
        return klines_service.get_candles(symbol, interval=ltf_interval, limit=ltf_limit)

    return make_recommendation_provider(
        _candles_fn, symbol_fn=symbol_fn, filters_fn=filters_fn, params=params,
        atr_period=atr_period, horizon=horizon,
        htf_candles_fn=_htf_candles_fn, ltf_candles_fn=_ltf_candles_fn)


def build_live_atr_pct_provider(klines_service, symbol_fn, *, atr_win=10,
                                interval="1m", limit=None, observer=None):
    """G1.65: يبني مزوّد ATR٪ حيّ **بلا وسائط** (يُحقَن في ``MonitoringEngine.live_atr_pct_provider``).

    يحسب ATR٪ الحيّ بنفس صيغة الباكتست المُتحقَّقة forward
    (``ocobot.domain.dynamic_exit.live_atr_pct`` ≡ ``exp_021_run._live_atr_pct``):
    متوسّط المدى الحقيقي لآخر ``atr_win`` شمعة 1m ÷ آخر إغلاق (المرجع الحيّ) ×100.
    الشبكة (GET /api/v3/klines) تمرّ عبر العميل المُحقَن داخل KlinesService. symbol_fn
    يُعيد الرمز المُراقَب حاليًّا (أو None/فارغ ⇒ 0.0 بلا نداء شبكة).

    fail-safe: يُعيد 0.0 عند نقص البيانات أو أي خطأ ⇒ يتراجع إلى بذرة التتبّع المتحفّظة
    (dist_min) فلا يكسر المراقبة أبدًا. وحدة وصل فقط: لا hot_path، لا تنفيذ Live فعلي،
    ولا يُستدعى أصلًا ما لم يكن الخروج المتكيّف مُفعَّلًا (DynamicExitConfig.enabled).
    """
    from ocobot.domain.dynamic_exit import live_atr_pct

    _win = int(atr_win) if atr_win else 10
    _limit = int(limit) if limit else max(_win + 5, 20)

    # G1.65 (increment #4): observability — عدّادات قراءة-فقط + تسجيل. **صفر تغيير سلوك**:
    # قيم الإرجاع مطابقة تمامًا لكل مسار (0.0/القيمة)؛ يُضاف فقط تصنيف سبب السقوط والتسجيل.
    # تُقرأ ``_provider.stats`` بوّابةً أثناء live-forward (المتوقَّع: failsafe == 0).
    stats = {
        "calls": 0, "ok": 0, "failsafe": 0,
        "last_value": 0.0, "last_reason": None,
        "failsafe_by_reason": {},
    }

    def _emit(ok, value, reason, symbol, n):
        # observability نفسها fail-safe: يجب ألّا تكسر المراقبة مهما حدث.
        try:
            stats["calls"] += 1
            stats["last_value"] = value
            stats["last_reason"] = reason
            if ok:
                stats["ok"] += 1
                _LOG.debug("live_atr_pct ok symbol=%s candles=%s value=%.6f",
                           symbol, n, value)
            else:
                stats["failsafe"] += 1
                stats["failsafe_by_reason"][reason] = \
                    stats["failsafe_by_reason"].get(reason, 0) + 1
                _LOG.warning("live_atr_pct FAIL-SAFE->0.0 reason=%s symbol=%s",
                             reason, symbol)
            if callable(observer):
                observer({"ok": ok, "value": value, "reason": reason,
                          "symbol": symbol, "candles": n})
        except Exception:
            pass

    def _provider():
        symbol = None
        try:
            symbol = symbol_fn() if callable(symbol_fn) else symbol_fn
            if not symbol:
                _emit(False, 0.0, "no_symbol", symbol, 0)
                return 0.0
            candles = klines_service.get_candles(symbol, interval=interval, limit=_limit)
            if not candles:
                _emit(False, 0.0, "empty_candles", symbol, 0)
                return 0.0
            highs = [c.high for c in candles]
            lows = [c.low for c in candles]
            closes = [c.close for c in candles]
            ref = closes[-1]
            value = float(live_atr_pct(highs, lows, closes, _win, ref))
            if value > 0.0:
                _emit(True, value, "ok", symbol, len(candles))
            else:
                _emit(False, 0.0, "zero_value", symbol, len(candles))
            return value
        except Exception as exc:
            _emit(False, 0.0, "exception", symbol, 0)
            _LOG.warning("live_atr_pct exception fail-safe: %r", exc)
            return 0.0  # المراقبة يجب ألّا تنكسر على خطأ المزوّد (fail-safe)

    _provider.stats = stats  # قراءة-فقط (مراقبة/بوّابة live-forward)
    return _provider
