"""محوّل عميل الوساطة لشبكة أمان المركز (Guardian Broker Adapter) — G1.30 / chunk_3.

هذه الوحدة **إضافية بحتة** وخارج المسار الحار تمامًا:
  - لا تمسّ ولا تستورد ``on_price_tick`` / ``MonitoringEngine.start`` /
    ``SafeExecutor.execute`` / ``create_oco`` / أي منطق تسعير/تموضع.
  - تبني محوّلًا ملموسًا يحقّق عقد ``ProtectiveStopClient`` (من
    ``ocobot.domain.guardian_exec``) فوق عميل REST الموجود
    (``ocobot.core.rest_client.SignedRestClient``) دون أي تعديل لذلك العميل.
  - تعيد استخدام منطق كشف البيع الحمائي القائم من
    ``ocobot.domain.open_orders_reader`` (أنواع STOP_LOSS / STOP_LOSS_LIMIT
    وأرجُل OCO) بدل إعادة كتابته.

قيود صارمة (منع البيع المزدوج + لا إلغاء):
  - **لا دالة إلغاء إطلاقًا**: المحوّل لا يُعرّف أي cancel/delete؛ عميل REST يملك
    ``cancel_order`` لكننا لا نكشفه ولا نستدعيه من هنا بتاتًا.
  - ``place_stop_loss_limit`` يضع أمر ``STOP_LOSS_LIMIT`` **واحدًا** عبر
    ``signed_request("POST", "/api/v3/order", ...)`` الموجود — ولا شيء آخر.

العميل الحقيقي يُحقن (dependency injection) فيبقى المحوّل قابلًا للاختبار بمحاكاة
عميل بلا أي شبكة فعلية.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Optional

from ocobot.domain.models import fmt
from ocobot.domain.open_orders_reader import _BELOW_TYPES

_ZERO = Decimal("0")

# أنواع البيع الحمائية القائمة التي تمنع التدخّل (منع البيع المزدوج):
#   - أرجُل OCO (orderListId > 0): أي رِجل بيع في OCO = حماية قائمة.
#   - أوامر مستقلة من نوع STOP (STOP_LOSS / STOP_LOSS_LIMIT): وقف حمائي قائم.
# نعيد استخدام ``_BELOW_TYPES`` من ``open_orders_reader`` حتى يبقى الكشف متطابقًا.
_PROTECTIVE_STANDALONE_TYPES = set(_BELOW_TYPES)


def _dec(value) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value or 0))


class GuardianBroker:
    """محوّل ملموس يحقّق عقد ``ProtectiveStopClient`` فوق عميل REST موجود.

    التبعيات المحقونة:
      - ``rest_client``: ``SignedRestClient`` (أو ما يماثله) يوفّر
        ``get_open_orders(symbol)`` و ``get_account()`` و
        ``signed_request(method, path, params)``.

    لا يحتفظ المحوّل بأي حالة قابلة للكتابة ولا يُلغي شيئًا؛ يقرأ فقط ويضع
    وقفًا حمائيًّا واحدًا عند الطلب.
    """

    PATH_ORDER = "/api/v3/order"

    def __init__(self, rest_client):
        self._client = rest_client

    # ---- قراءة: أوامر البيع الحمائية القائمة -------------------------------
    def get_open_sell_orders(self, symbol: str) -> List[Any]:
        """يعيد أوامر/أرجُل البيع الحمائية القائمة للعملة فقط (قراءة بحتة).

        منطق الكشف (مُعاد استخدامه من ``open_orders_reader``):
          - ``orderListId`` > 0 ⇒ رِجل OCO ⇒ أي بيع في OCO = حماية قائمة.
          - أمر مستقل من نوع ضمن ``STOP_LOSS``/``STOP_LOSS_LIMIT`` = وقف حمائي.
        لا تُعاد أوامر الشراء ولا LIMIT بيع عادية غير حمائية (TP وحده ليس حماية
        سفلية؛ لكننا نُبقي رِجل OCO لأنها جزء من حماية قائمة فعلًا).
        """
        raw = self._client.get_open_orders(symbol) or []
        protective: List[Dict[str, Any]] = []
        for o in raw:
            if str(o.get("side", "")).upper() != "SELL":
                continue
            if str(o.get("symbol", "")).upper() != str(symbol).upper():
                continue
            olid = _as_int(o.get("orderListId"), default=-1)
            otype = str(o.get("type", "")).upper()
            is_oco_leg = olid != -1
            is_standalone_stop = otype in _PROTECTIVE_STANDALONE_TYPES
            if is_oco_leg or is_standalone_stop:
                protective.append(o)
        return protective

    # ---- قراءة: الرصيد الأساسي الحرّ ---------------------------------------
    def get_free_asset_qty(self, asset: str) -> Decimal:
        """يقرأ الرصيد الأساسي الحرّ (غير المقفول) للأصل من /api/v3/account.

        استجابة الحساب: ``{"balances": [{"asset", "free", "locked"}, ...]}``.
        إن غاب الأصل أو تعذّرت القراءة ⇒ ``Decimal("0")`` (آمن: لا كمية للحماية).
        """
        if not asset:
            return _ZERO
        account = self._client.get_account() or {}
        balances = account.get("balances") or []
        target = str(asset).upper()
        for bal in balances:
            if str(bal.get("asset", "")).upper() == target:
                return _dec(bal.get("free"))
        return _ZERO

    # ---- كتابة واحدة فقط: STOP_LOSS_LIMIT ----------------------------------
    def place_stop_loss_limit(
        self,
        symbol: str,
        quantity: Decimal,
        stop_price: Decimal,
        limit_price: Decimal,
        client_order_id: str,
    ) -> Dict[str, Any]:
        """يضع أمر ``STOP_LOSS_LIMIT`` واحدًا عبر عميل REST الموجود.

        يستعمل ``signed_request("POST", "/api/v3/order", ...)`` القائم — لا دالة
        إنشاء جديدة ولا منطق تسعير هنا (الأسعار/الكمية مُحسوبة مسبقًا في
        ``plan_protective_stop``). timeInForce=GTC كما في بقية الأوامر المحدَّدة.
        """
        params = [
            ("symbol", symbol),
            ("side", "SELL"),
            ("type", "STOP_LOSS_LIMIT"),
            ("timeInForce", "GTC"),
            ("quantity", fmt(_dec(quantity))),
            ("price", fmt(_dec(limit_price))),
            ("stopPrice", fmt(_dec(stop_price))),
            ("newClientOrderId", client_order_id),
        ]
        return self._client.signed_request("POST", self.PATH_ORDER, params)


def _as_int(value, default: int = -1) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def base_asset_of(symbol: str, exchange_info=None) -> Optional[str]:
    """يستنتج الأصل الأساسي (base asset) لرمز العملة.

    يُفضّل القراءة الدقيقة من ``exchange_info`` إن توفّر (كائن يملك
    ``get_symbol(symbol)`` أو عميلًا يُرجع ``baseAsset`` من exchangeInfo).
    وإلّا يسقط إلى تقشير لاحقة عملة اقتباس شائعة (USDT/BUSD/USDC/BTC/ETH/BNB)
    كتقدير آمن. يُعيد ``None`` إن تعذّر الاستنتاج (المُشرِف يعاملها كـ NOOP آمن).
    """
    if not symbol:
        return None
    # محاولة دقيقة عبر exchange_info إن أتاح baseAsset
    if exchange_info is not None:
        getter = getattr(exchange_info, "get_symbol", None)
        if callable(getter):
            try:
                obj = getter(symbol) or {}
                base = obj.get("baseAsset") if isinstance(obj, dict) else None
                if base:
                    return str(base)
            except Exception:
                pass  # السقوط للتقدير أدناه؛ لا نكسر المُشرِف
    sym = str(symbol).upper()
    for quote in ("USDT", "FDUSD", "BUSD", "USDC", "TUSD", "BTC", "ETH", "BNB"):
        if sym.endswith(quote) and len(sym) > len(quote):
            return sym[: -len(quote)]
    return None
