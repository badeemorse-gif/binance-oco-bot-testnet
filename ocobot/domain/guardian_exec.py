"""منفّذ الوقف الحمائي (Protective-Stop Executor) — G1.30 / chunk_2.

هذه الوحدة **إضافية بحتة** ومعزولة عن المسار الحار:
  - لا تمسّ ولا تستورد المسار الحار إطلاقًا (``on_price_tick`` / ``SafeExecutor`` /
    ``reposition.py`` / ``create_oco`` / ``monitoring`` engine internals).
  - لا تستورد عميل الوساطة الحقيقي؛ تعتمد على عميل **مُحقَّن** عبر
    ``typing.Protocol`` (dependency injection)، فتكون قابلة للاختبار بالكامل
    بمحاكاة عميل بلا أيّ شبكة فعلية.
  - تعيد استخدام مساعدات التسعير الموجودة (``round_to_tick`` / ``floor_to_step``)
    حتى تطابق الدقّة والفلاتر (tick/step) ما يستعمله المحرّك تمامًا (D8/D7).

منع البيع المزدوج (double-sell guard) على مستوى المنفّذ، بقيدين بنيويّين:
  1. **RECONCILE**: قبل أيّ وضع، نقرأ أوامر البيع القائمة؛ فإن وُجد أيّ بيع حمائي
     قائم ⇒ ``ABORT_PROTECTED`` ولا نضع شيئًا (لا بيع ثانٍ أبدًا).
  2. **eff_qty = min(qty, free)**: نقصر الكمية على الرصيد الحرّ الفعلي؛ فإن كان
     الرصيد مقفولًا (أمر قائم يقفله) كان ``free`` صفرًا والنتيجة
     ``ABORT_NO_FREE_QTY``.

المنفّذ **لا يُلغي أيّ أمر إطلاقًا** — يقرأ فقط (الأوامر القائمة + الرصيد الحرّ)
ويضع **وقفًا حمائيًّا واحدًا** (``STOP_LOSS_LIMIT``) على الأكثر.

العميل الحقيقي يُهيَّأ (adapter) في chunk_3؛ لا يُستورَد العميل الملموس هنا.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Protocol, runtime_checkable

from ocobot.domain.pricing import DEFAULT_GAP_TICKS, floor_to_step, round_to_tick

_ZERO = Decimal("0")


def _dec(value) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


@runtime_checkable
class ProtectiveStopClient(Protocol):
    """العقد الأدنى لعميل الوساطة الذي يحتاجه المنفّذ (DI عبر Protocol).

    ملاحظة: لا توجد أيّ دالة إلغاء هنا بنيويًّا — المنفّذ لا يُلغي أبدًا.
    """

    def get_open_sell_orders(self, symbol: str) -> List[Any]:
        """أوامر البيع القائمة (رِجل OCO أو أمر بيع مستقل) للعملة."""
        ...

    def get_free_asset_qty(self, asset: str) -> Decimal:
        """الرصيد الأساسي الحرّ (غير المقفول) للأصل."""
        ...

    def place_stop_loss_limit(
        self,
        symbol: str,
        quantity: Decimal,
        stop_price: Decimal,
        limit_price: Decimal,
        client_order_id: str,
    ) -> Dict[str, Any]:
        """يضع أمر ``STOP_LOSS_LIMIT`` واحدًا ويعيد ردّ الوساطة."""
        ...


def plan_protective_stop(reference_price, qty, emergency_sl_pct, filters, stop_limit_offset_pct=None, price_floor_pct=None) -> Dict[str, Any]:
    """دالة **خالصة**: تحسب معاملات الوقف الحمائي من سعر مرجعي + نسبة طارئة.

    - ``stop_trigger = round_to_tick(reference_price * (1 - emergency_sl_pct/100))``
      [ROUND_HALF_UP عبر المساعد الموجود، مضاعف tick نظيف — D8].
    - ``stop_limit = stop_trigger - gap_ticks * tick`` ثم يُقرَّب لمضاعف tick أدنى
      بصرامة، فيبقى دائمًا أدنى من ``stop_trigger`` (D4/D5).
    - ``quantity = floor_to_step(qty)`` [ROUND_DOWN — D7] حتى لا نتجاوز الرصيد.

    يعيد قاموس المعاملات المُخطّطة؛ لا شبكة ولا أثر جانبي.
    """
    p = _dec(reference_price)
    sl_pct = _dec(emergency_sl_pct)
    tick = _dec(getattr(filters, "tick_size", 0) or 0)
    step = getattr(filters, "step_size", None)
    gap_ticks = getattr(filters, "gap_ticks", None)
    if gap_ticks is None:
        gap_ticks = DEFAULT_GAP_TICKS
    hundred = Decimal("100")

    stop_trigger = round_to_tick(p * (Decimal("1") - sl_pct / hundred), tick)

    gap = _dec(gap_ticks) * tick
    # G1.49: إزاحة STOP_LOSS_LIMIT قابلة للضبط (نسبة مئوية تحت الزناد) لجعله marketable
    #        فيُنفَّذ بدل أن يرقد ويعلّق. None ⇒ سلوك gap_ticks القديم تمامًا.
    if stop_limit_offset_pct is not None:
        _off = _dec(stop_limit_offset_pct)
        if _off < _ZERO:
            _off = _ZERO
        _offset_gap = stop_trigger * _off / hundred
        if _offset_gap > gap:
            gap = _offset_gap
    stop_limit = round_to_tick(stop_trigger - gap, tick)
    # اضمن أن Stop Limit أدنى من Trigger بصرامة (D4) إن توفّر tick.
    if tick and stop_limit >= stop_trigger:
        stop_limit = stop_trigger - tick
    # G1.49: أرضية ضد الفلاش-كراش (اختيارية) — لا نضع limit أدنى من الأرضية. None ⇒ لا أرضية إضافية.
    if price_floor_pct is not None:
        _fp = _dec(price_floor_pct)
        if _fp < _ZERO:
            _fp = _ZERO
        _price_floor = round_to_tick(p * (Decimal("1") - _fp / hundred), tick)
        if stop_limit < _price_floor:
            stop_limit = _price_floor
            if tick and stop_limit >= stop_trigger:
                stop_trigger = stop_limit + tick

    quantity = floor_to_step(_dec(qty), step)

    return {
        "symbol": getattr(filters, "symbol", None),
        "side": "SELL",
        "type": "STOP_LOSS_LIMIT",
        "quantity": quantity,
        "stop_price": stop_trigger,
        "stop_trigger": stop_trigger,
        "limit_price": stop_limit,
        "stop_limit": stop_limit,
        "reference_price": p,
        "emergency_sl_pct": sl_pct,
        "gap_ticks": int(_dec(gap_ticks)),
    }


def place_protective_stop(
    client: ProtectiveStopClient,
    symbol: str,
    base_asset: str,
    reference_price,
    qty,
    emergency_sl_pct,
    filters,
    client_order_id: str,
    dry_run: bool = True,
    notifier=None,
    stop_limit_offset_pct=None,
    price_floor_pct=None,
) -> Dict[str, Any]:
    """يضع وقفًا حمائيًّا واحدًا على الأكثر، بالترتيب الصارم التالي.

      1. **RECONCILE** (منع البيع المزدوج على مستوى المنفّذ):
         إن وُجد أيّ بيع حمائي قائم ⇒ ``action="ABORT_PROTECTED"`` ولا نضع شيئًا.
      2. ``free = get_free_asset_qty(base_asset)``؛ ``eff_qty = min(qty, free)``؛
         إن كان ``eff_qty <= 0`` ⇒ ``action="ABORT_NO_FREE_QTY"`` ولا نضع شيئًا.
      3. يبني الخطّة عبر ``plan_protective_stop`` على ``eff_qty``.
      4. إن كان ``dry_run`` ⇒ ``action="DRY_RUN"`` بالخطّة، بلا أيّ استدعاء وضع.
      5. وإلّا ⇒ يستدعي ``place_stop_loss_limit`` **مرّة واحدة فقط** بمعاملات
         الخطّة + ``client_order_id`` المُعطى، ويعيد ``action="PLACED"`` بالردّ.

    لا يستدعي أيّ دالة إلغاء إطلاقًا، ولا يضع أكثر من أمر واحد.

    G1.37 (emit-only): ``notifier`` معامل اختياري؛ إن أُعطي يُستدعى
    ``notifier(result)`` **فقط** على مسار ``PLACED`` قبل الإرجاع، محروسًا داخل
    try/except (فشله يُسجَّل في ``result["notify_error"]`` ولا يُفشِل التنفيذ).
    لا يُستدعى على ``DRY_RUN`` / ``ABORT_*``.
    """
    # 1) RECONCILE — قراءة فقط؛ أيّ بيع حمائي قائم يمنع التدخّل.
    orders = client.get_open_sell_orders(symbol)
    if orders:
        return {
            "action": "ABORT_PROTECTED",
            "symbol": symbol,
            "resting_orders": len(orders),
            "placed": False,
            "reason": "resting protective sell present — reconcile abort",
        }

    # 2) الرصيد الحرّ ⇒ eff_qty = min(qty, free).
    free = _dec(client.get_free_asset_qty(base_asset))
    eff_qty = min(_dec(qty), free)
    if eff_qty <= _ZERO:
        return {
            "action": "ABORT_NO_FREE_QTY",
            "symbol": symbol,
            "free": free,
            "placed": False,
            "reason": "no free base balance to protect",
        }

    # 3) بناء الخطّة على الكمية الفعّالة.
    plan = plan_protective_stop(reference_price, eff_qty, emergency_sl_pct, filters,
                                stop_limit_offset_pct=stop_limit_offset_pct,
                                price_floor_pct=price_floor_pct)
    plan["symbol"] = plan.get("symbol") or symbol

    # 4) تشغيل جافّ — لا وضع إطلاقًا.
    if dry_run:
        return {
            "action": "DRY_RUN",
            "symbol": symbol,
            "free": free,
            "eff_qty": eff_qty,
            "plan": plan,
            "placed": False,
            "client_order_id": client_order_id,
        }

    # 5) وضع واحد فقط.
    response = client.place_stop_loss_limit(
        symbol=symbol,
        quantity=plan["quantity"],
        stop_price=plan["stop_price"],
        limit_price=plan["limit_price"],
        client_order_id=client_order_id,
    )
    result = {
        "action": "PLACED",
        "symbol": symbol,
        "free": free,
        "eff_qty": eff_qty,
        "plan": plan,
        "placed": True,
        "client_order_id": client_order_id,
        "response": response,
    }

    # G1.37: تنبيه إضافي اختياري — فقط على مسار الوضع الفعلي (PLACED). محروس حتى
    #        لا يرمي أبدًا، ولا يؤثّر على نتيجة التنفيذ.
    if notifier is not None:
        try:
            notifier(result)
        except Exception as exc:  # pragma: no cover - دفاعي
            result["notify_error"] = repr(exc)
    return result
