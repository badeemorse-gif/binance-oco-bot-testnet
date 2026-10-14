"""OCOBot non-ui wiring helpers (G1.8).

وحدة تجميع غير-ui: تبني موفّر السعر الذي تحتاجه الواجهة دون أن تقع تحت
حارس الشبكة الخاص بطبقة ui. تعيد استخدام ``_build_feed`` من ``ocobot.cli``
(النقل الفعلي WS+REST يبقى هناك) ولا تحتوي على أي بدائيات شبكة مباشرة.
"""
from __future__ import annotations

from ocobot.cli import _build_feed


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
