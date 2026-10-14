"""منفّذ خروج معزول بالسعر (Market Exit Executor) — G1.32a.

وحدة **إضافية بحتة** معزولة عن المسار الحار (نفس انضباط ``guardian_exec.py``):
  - لا تمسّ ولا تستورد hot_path (``on_price_tick`` / ``SafeExecutor`` /
    ``reposition.py`` / ``create_oco`` / ``MonitoringEngine`` internals).
  - تعتمد على عميل **مُحقَّن** عبر ``typing.Protocol`` (DI) وعلى ``kill_switch``
    مُحقَّن كذلك؛ قابلة للاختبار بالكامل بمحاكاة بلا أيّ شبكة فعلية.
  - تعيد استخدام مساعدات التسعير الموجودة (``round_to_tick`` / ``floor_to_step``)
    لتطابق الفلاتر (tick/step) تمامًا (D7/D8) — لا hardcode للأسعار.

التسعير المعتمد (قرار G1.31/G1.32):
  - الخروج السفلي (``exit_side="lower"``): ``STOP_LOSS_LIMIT`` **قابل للتنفيذ**
    (marketable) بفجوة كافية + **أرضية سعرية** ضد الفلاش-كراش.
  - الخروج العلوي (``exit_side="upper"``): ``LIMIT`` **قابل للتنفيذ** (سعر معروف).
  - ``MARKET`` العاري ليس الافتراضي؛ خيار متقدّم صريح فقط (``allow_market=True``).

منع البيع المزدوج بنيويًّا يُفرَض في تسلسل ``execute_market_exit`` (chunk_2):
  reconcile قبل الوضع + وضع واحد فقط + ``eff_qty = floor_to_step(min(target, free))``.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Protocol, Tuple, runtime_checkable

from ocobot.domain.pricing import DEFAULT_GAP_TICKS, floor_to_step, round_to_tick

_ZERO = Decimal("0")
_HUNDRED = Decimal("100")

# نِسب سلوكية محافِظة افتراضية (مئوية) — لا hardcode للأسعار، نِسب فقط.
DEFAULT_EMERGENCY_SL_PCT = Decimal("1")   # زناد سفلي ~1% دون المرجع ⇒ marketable
DEFAULT_PRICE_FLOOR_PCT = Decimal("8")    # أرضية ضد الفلاش-كراش (لا نبيع أدنى منها)
DEFAULT_SLIP_PCT = Decimal("0.1")         # LIMIT علوي أدنى بقليل من المرجع ⇒ marketable

EXIT_LOWER = "lower"
EXIT_UPPER = "upper"


def _dec(value) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


@runtime_checkable
class MarketExitClient(Protocol):
    """العقد الأدنى لعميل الوساطة الذي يحتاجه منفّذ الخروج (DI عبر Protocol)."""

    def get_open_sell_orders(self, symbol: str) -> List[Any]:
        """أوامر البيع القائمة (رِجل OCO أو بيع مستقل) للعملة — للـreconcile."""
        ...

    def get_free_asset_qty(self, asset: str) -> Decimal:
        """الرصيد الأساسي الحرّ (غير المقفول) للأصل."""
        ...

    def cancel_oco(self, symbol: str, order_list_id: int) -> Dict[str, Any]:
        """يُلغي OCO قائمًا (DELETE /api/v3/orderList) لتحرير الرصيد المقفول."""
        ...

    def place_stop_loss_limit(
        self,
        symbol: str,
        quantity: Decimal,
        stop_price: Decimal,
        limit_price: Decimal,
        client_order_id: str,
    ) -> Dict[str, Any]:
        """يضع أمر ``STOP_LOSS_LIMIT`` واحدًا (الخروج السفلي marketable)."""
        ...

    def place_limit_sell(
        self,
        symbol: str,
        quantity: Decimal,
        price: Decimal,
        client_order_id: str,
    ) -> Dict[str, Any]:
        """يضع أمر ``LIMIT`` SELL واحدًا (الخروج العلوي marketable)."""
        ...

    def place_market_sell(
        self,
        symbol: str,
        quantity: Decimal,
        client_order_id: str,
    ) -> Dict[str, Any]:
        """يضع أمر ``MARKET`` SELL عاريًا — خيار متقدّم صريح فقط."""
        ...


def plan_market_exit(
    *,
    exit_side: str,
    reference_price,
    qty,
    filters,
    emergency_sl_pct=None,
    price_floor_pct=None,
    slip_pct=None,
    gap_ticks=None,
    stop_limit_offset_pct=None,
    allow_market: bool = False,
) -> Dict[str, Any]:
    """دالة **خالصة**: تبني معاملات أمر الخروج وتتحقّق من الفلاتر (LOT_SIZE/minNotional).

    لا شبكة ولا أثر جانبي. تعيد قاموسًا فيه ``valid``/``reason`` + معاملات الأمر:
      - سفلي ⇒ ``type=STOP_LOSS_LIMIT`` بـ ``stop_price``/``limit_price`` + ``price_floor``.
      - علوي ⇒ ``type=LIMIT`` بـ ``price`` (أدنى بقليل من المرجع ⇒ marketable).
      - ``allow_market`` ⇒ ``type=MARKET`` بلا سعر (متقدّم صريح).
    """
    ref = _dec(reference_price)
    tick = _dec(getattr(filters, "tick_size", 0) or 0)
    step = getattr(filters, "step_size", None)
    min_qty = getattr(filters, "min_qty", None)
    min_notional = getattr(filters, "min_notional", None)
    symbol = getattr(filters, "symbol", None)
    if gap_ticks is None:
        gap_ticks = getattr(filters, "gap_ticks", None)
    if gap_ticks is None:
        gap_ticks = DEFAULT_GAP_TICKS
    sl_pct = _dec(emergency_sl_pct if emergency_sl_pct is not None else DEFAULT_EMERGENCY_SL_PCT)
    floor_pct = _dec(price_floor_pct if price_floor_pct is not None else DEFAULT_PRICE_FLOOR_PCT)
    sp = _dec(slip_pct if slip_pct is not None else DEFAULT_SLIP_PCT)

    quantity = floor_to_step(_dec(qty), step)

    result: Dict[str, Any] = {
        "symbol": symbol,
        "side": "SELL",
        "exit_side": exit_side,
        "quantity": quantity,
        "reference_price": ref,
        "type": None,
        "price": None,
        "stop_price": None,
        "limit_price": None,
        "price_floor": None,
        "notional": None,
        "valid": False,
        "reason": None,
    }

    if allow_market:
        result["type"] = "MARKET"
        price_for_notional = ref
    elif exit_side == EXIT_LOWER:
        result["type"] = "STOP_LOSS_LIMIT"
        stop_trigger = round_to_tick(ref * (Decimal("1") - sl_pct / _HUNDRED), tick)
        gap = _dec(gap_ticks) * tick
        # G1.49: إزاحة STOP_LOSS_LIMIT نسبية اختيارية (تحت الزناد) لجعله marketable. None ⇒ سلوك gap_ticks القديم.
        if stop_limit_offset_pct is not None:
            _off = _dec(stop_limit_offset_pct)
            if _off < _ZERO:
                _off = _ZERO
            _offset_gap = stop_trigger * _off / _HUNDRED
            if _offset_gap > gap:
                gap = _offset_gap
        stop_limit = round_to_tick(stop_trigger - gap, tick, rounding=ROUND_DOWN)
        if tick and stop_limit >= stop_trigger:
            stop_limit = stop_trigger - tick
        # أرضية ضد الفلاش-كراش: لا نضع limit أدنى من الأرضية.
        price_floor = round_to_tick(ref * (Decimal("1") - floor_pct / _HUNDRED), tick)
        if stop_limit < price_floor:
            stop_limit = price_floor
            if tick and stop_limit >= stop_trigger:
                stop_trigger = stop_limit + tick
        result["stop_price"] = stop_trigger
        result["limit_price"] = stop_limit
        result["price_floor"] = price_floor
        price_for_notional = stop_limit
    elif exit_side == EXIT_UPPER:
        result["type"] = "LIMIT"
        limit_price = round_to_tick(ref * (Decimal("1") - sp / _HUNDRED), tick)
        result["price"] = limit_price
        price_for_notional = limit_price
    else:
        result["reason"] = "unknown_exit_side"
        return result

    # تحقّق الفلاتر (الترتيب: كمية صفرية ⇐ LOT_SIZE ⇐ minNotional).
    if quantity <= _ZERO:
        result["reason"] = "zero_qty_after_floor"
        return result
    if min_qty is not None and _dec(min_qty) > _ZERO and quantity < _dec(min_qty):
        result["reason"] = "below_lot_size_min_qty"
        return result
    notional = quantity * _dec(price_for_notional)
    result["notional"] = notional
    if min_notional is not None and _dec(min_notional) > _ZERO and notional < _dec(min_notional):
        result["reason"] = "below_min_notional"
        return result

    result["valid"] = True
    return result


def _result(action: str, symbol: str, exit_side: str, **extra) -> Dict[str, Any]:
    base: Dict[str, Any] = {"action": action, "symbol": symbol, "exit_side": exit_side}
    base.update(extra)
    return base


# ======================================================================
# G1.53 — telemetry تنفيذ الخروج (exit_execution) عبر audit_sink محقون (opt-in).
# إضافة بحتة: الكتابة اختيارية (``audit_sink`` default None ⇒ لا انحدار ولا تغيير
# سلوك)، لا تمسّ hot_path ولا تغيّر أي قرار تنفيذ. القيم كلّها محسوبة أصلًا داخل
# المنفّذ (كانت تُهمَل). القارئ: ``ocobot.domain.profitability.extract_exit_executions``.
# ======================================================================
_EXIT_EXECUTION_EVENT = "exit_execution"


def _to_dec_safe(value) -> Optional[Decimal]:
    """تحويل Decimal متسامح (None/'' ⇒ None؛ التالف ⇒ None) — لا يرمي."""
    if value is None or value == "":
        return None
    try:
        return value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def sum_commission(resp) -> Tuple[Decimal, Optional[str]]:
    """G1.53/chunk_3: يجمع عمولة التنفيذ من ردّ وسيط (best-effort، Decimal فقط).

    يدعم شكلَي ردّ Binance الشائعين دون افتراض واحد:
      - executionReport: الحقل ``n`` = العمولة، ``N`` = أصل العمولة.
      - order response: ``fills`` = قائمة ``{commission, commissionAsset}``.
    يُعيد ``(total, asset)``؛ وعند غياب أي عمولة ⇒ ``(Decimal('0'), None)`` بلا رفع
    استثناء. دالة **خالصة** لا تمسّ أي قرار تنفيذ (قراءة فقط من الردّ).
    """
    if not isinstance(resp, dict):
        return _ZERO, None
    total = _ZERO
    asset: Optional[str] = None
    c = _to_dec_safe(resp.get("n"))
    if c is not None:
        total += c
        asset = resp.get("N") or asset
    fills = resp.get("fills")
    if isinstance(fills, list):
        for f in fills:
            if not isinstance(f, dict):
                continue
            fc = _to_dec_safe(f.get("commission"))
            if fc is not None:
                total += fc
                asset = f.get("commissionAsset") or asset
    return total, asset


def build_exit_execution_record(
    *, source, exit_side, order_type, tif, requested_price, filled_price,
    live_bid, slippage_pct, band_pct, attempts_used, reached_floor,
    floor_price, qty, trade_uid, dry_run, commission=None, commission_asset=None,
) -> Dict[str, Any]:
    """يبني قاموس تفاصيل سجلّ ``exit_execution`` (دالة **خالصة** بلا أثر جانبي).

    تبقى قيم ``Decimal`` كما هي؛ يُسلسِلها ``AuditLog`` كنصوص (``default=str``)
    ويعيدها القارئ إلى ``Decimal`` — فلا تحويل إلى ``float`` إطلاقًا. حقلا
    ``commission``/``commission_asset`` (G1.53/chunk_3) يُضافان **فقط** عند
    توفّرهما (best-effort) ليبقى السجلّ مطابقًا لسكيمة chunk_2 عند غياب العمولة.
    """
    record: Dict[str, Any] = {
        "source": source or "",
        "exit_side": exit_side,
        "order_type": order_type,
        "tif": tif,
        "requested_price": requested_price,
        "filled_price": filled_price,
        "live_bid": live_bid,
        "slippage_pct": slippage_pct,
        "band_pct": band_pct,
        "attempts_used": attempts_used,
        "reached_floor": bool(reached_floor),
        "floor_price": floor_price,
        "qty": qty,
        "trade_uid": trade_uid or "",
        "dry_run": bool(dry_run),
    }
    if commission is not None:
        record["commission"] = commission
    if commission_asset is not None:
        record["commission_asset"] = commission_asset
    return record


def _emit_exit_execution(audit_sink, details: Dict[str, Any]) -> None:
    """يُرسِل سجلّ telemetry عبر ``audit_sink`` إن وُجد — لا يُفشِل الخروج أبدًا.

    ``audit_sink`` قابل للاستدعاء بتوقيع ``(event, details)`` (مطابق لـ
    ``AuditLog.record``). ``None`` ⇒ لا شيء (opt-in). أي استثناء يُبتَلع (دفاعي)
    حتى لا تؤثّر الـtelemetry على مسار التنفيذ.
    """
    if audit_sink is None:
        return
    try:
        audit_sink(_EXIT_EXECUTION_EVENT, details)
    except Exception:  # pragma: no cover - دفاعي: الـtelemetry لا تُفشِل الخروج
        pass


def execute_market_exit(
    *,
    client,
    symbol: str,
    base_asset: str,
    exit_side: str,
    reference_price,
    target_qty,
    filters,
    client_order_id: str,
    order_list_id=None,
    kill_switch=None,
    notifier=None,
    emergency_sl_pct=None,
    price_floor_pct=None,
    slip_pct=None,
    gap_ticks=None,
    stop_limit_offset_pct=None,
    allow_market: bool = False,
    audit_sink=None,
    source: str = "",
    trade_uid: str = "",
    dry_run: bool = True,
) -> Dict[str, Any]:
    """ينفّذ تسلسل الخروج الآمن بالترتيب الصارم (وضع واحد على الأكثر).

    التشغيل الجافّ (``dry_run=True``) **بلا أيّ أثر جانبي**: لا ``kill_switch`` ولا
    إلغاء ولا وضع — يعيد ``action="DRY_RUN"`` بالخطّة المبنيّة على ``target_qty``.

    التشغيل الفعلي، بالترتيب:
      1. ``kill_switch()`` — يوقف المراقبة أولًا (idempotent؛ لا يُفشِل الخروج إن رمى).
      2. إلغاء OCO القائم عبر ``client.cancel_oco`` لتحرير الرصيد (إن أُعطي
         ``order_list_id``). لا يمسّ ``reposition``.
      3. **RECONCILE** (منع البيع المزدوج): يُعاد قراءة أوامر البيع؛ إن بقي أيّ بيع
         حمائي قائم ⇒ ``ABORT_PROTECTED`` ولا وضع (لا بيع ثانٍ أبدًا).
      4. ``free = get_free_asset_qty``؛ ``eff_qty = min(target, free)``؛ إن ``<=0`` ⇒
         ``ABORT_NO_FREE_QTY``.
      5. ``plan_market_exit`` على ``eff_qty``؛ إن غير صالح (غبار/minNotional) ⇒
         ``ABORT_INVALID_FILTERS``.
      6. وضع **واحد فقط** حسب النوع (STOP_LOSS_LIMIT سفلي / LIMIT علوي / MARKET متقدّم)
         + تنبيه اختياري ⇒ ``PLACED``.
    """
    # ---- تشغيل جافّ: معاينة خالصة بلا أثر جانبي ----
    if dry_run:
        plan = plan_market_exit(
            exit_side=exit_side, reference_price=reference_price, qty=target_qty,
            filters=filters, emergency_sl_pct=emergency_sl_pct,
            price_floor_pct=price_floor_pct, slip_pct=slip_pct,
            gap_ticks=gap_ticks, stop_limit_offset_pct=stop_limit_offset_pct,
            allow_market=allow_market,
        )
        plan["symbol"] = plan.get("symbol") or symbol
        if audit_sink is not None:
            _emit_exit_execution(audit_sink, build_exit_execution_record(
                source=source, exit_side=exit_side, order_type=plan.get("type"), tif=None,
                requested_price=(plan.get("limit_price") or plan.get("price")),
                filled_price=None, live_bid=None, slippage_pct=None, band_pct=None,
                attempts_used=0, reached_floor=False, floor_price=plan.get("price_floor"),
                qty=plan.get("quantity"), trade_uid=trade_uid, dry_run=True))
        return _result("DRY_RUN", symbol, exit_side, placed=False, plan=plan,
                       client_order_id=client_order_id, steps=[("dry_run_preview", True)])

    steps: List[Any] = []

    # 1) إيقاف المراقبة أولًا (لا يُفشِل الخروج إن رمى).
    monitoring_stopped = False
    if kill_switch is not None:
        try:
            kill_switch()
            monitoring_stopped = True
        except Exception as exc:  # pragma: no cover - دفاعي
            steps.append(("kill_switch_error", repr(exc)))
    steps.append(("monitoring_stopped", monitoring_stopped))

    # 2) إلغاء OCO القائم لتحرير الرصيد المقفول.
    if order_list_id is not None:
        client.cancel_oco(symbol, order_list_id)
        steps.append(("oco_cancelled", order_list_id))

    # 3) RECONCILE — منع البيع المزدوج بعد الإلغاء.
    resting = client.get_open_sell_orders(symbol)
    if resting:
        return _result("ABORT_PROTECTED", symbol, exit_side, placed=False,
                       reason="resting protective sell present after cancel — double-sell abort",
                       resting_orders=len(resting), steps=steps)

    # 4) الرصيد الحرّ ⇒ eff_qty = min(target, free).
    free = _dec(client.get_free_asset_qty(base_asset))
    eff_qty = min(_dec(target_qty), free)
    if eff_qty <= _ZERO:
        return _result("ABORT_NO_FREE_QTY", symbol, exit_side, placed=False,
                       reason="no free base balance to exit", free=free, steps=steps)

    # 5) الخطّة على الكمية الفعّالة.
    plan = plan_market_exit(
        exit_side=exit_side, reference_price=reference_price, qty=eff_qty,
        filters=filters, emergency_sl_pct=emergency_sl_pct,
        price_floor_pct=price_floor_pct, slip_pct=slip_pct,
        gap_ticks=gap_ticks, stop_limit_offset_pct=stop_limit_offset_pct,
        allow_market=allow_market,
    )
    plan["symbol"] = plan.get("symbol") or symbol
    if not plan["valid"]:
        return _result("ABORT_INVALID_FILTERS", symbol, exit_side, placed=False,
                       reason=plan["reason"], plan=plan, free=free, eff_qty=eff_qty, steps=steps)

    # 6) وضع واحد فقط حسب النوع.
    otype = plan["type"]
    if otype == "STOP_LOSS_LIMIT":
        response = client.place_stop_loss_limit(
            symbol=symbol, quantity=plan["quantity"], stop_price=plan["stop_price"],
            limit_price=plan["limit_price"], client_order_id=client_order_id)
    elif otype == "LIMIT":
        response = client.place_limit_sell(
            symbol=symbol, quantity=plan["quantity"], price=plan["price"],
            client_order_id=client_order_id)
    elif otype == "MARKET":
        response = client.place_market_sell(
            symbol=symbol, quantity=plan["quantity"], client_order_id=client_order_id)
    else:  # pragma: no cover - دفاعي
        return _result("ABORT_INVALID_FILTERS", symbol, exit_side, placed=False,
                       reason="unknown_order_type", plan=plan, steps=steps)

    result = _result("PLACED", symbol, exit_side, placed=True, plan=plan, free=free,
                     eff_qty=eff_qty, client_order_id=client_order_id, response=response,
                     steps=steps)

    if audit_sink is not None:
        _place_commission, _place_asset = sum_commission(response)
        _emit_exit_execution(audit_sink, build_exit_execution_record(
            source=source, exit_side=exit_side, order_type=plan.get("type"), tif=None,
            requested_price=(plan.get("limit_price") or plan.get("price")),
            filled_price=None, live_bid=None, slippage_pct=None, band_pct=None,
            attempts_used=1, reached_floor=False, floor_price=plan.get("price_floor"),
            qty=plan.get("quantity"), trade_uid=trade_uid, dry_run=False,
            commission=(_place_commission if _place_commission > _ZERO else None),
            commission_asset=_place_asset))

    # تنبيه اختياري — لا يُفشِل الخروج إن رمى.
    if notifier is not None:
        try:
            notifier(result)
        except Exception as exc:  # pragma: no cover - دفاعي
            result["notify_error"] = repr(exc)
    return result


# ======================================================================
# G1.49 — سياسة تنفيذ الخروج الموحّدة (Unified Exit-Execution Policy)
# إضافة بحتة: دوال خالصة قابلة للاختبار، بلا شبكة ولا hot_path.
# الهدف المعتمد: «عدم التعليق + الخروج بأقرب نقطة سعرية في الطوارئ لا بنطّة بعيدة».
# الآلية: ترسية على أفضل BID حيّ + band عبور محكوم + LIMIT IOC + chase نازل
# لحد أرضية صارمة + ملاذ أخير (ب) MARKET محمي بالأرضية. التنفيذ الفعلي (الحلقة
# الحيّة + إعادة قراءة الـBID) يتمّ في طبقة الربط (chunk_4) فوق هذه الخطط الخالصة.
# ======================================================================

TIF_IOC = "IOC"  # Immediate-Or-Cancel: ينفّذ فورًا أو يُلغى (لا أمر راقد معلّق)

# نِسب افتراضية (مئوية) لسياسة التنفيذ الموحّدة (قابلة للضبط من الواجهة لاحقًا).
DEFAULT_BAND_PCT = Decimal("0.2")          # عبور محكوم تحت أفضل BID (marketable)
DEFAULT_CHASE_STEP_PCT = Decimal("0.2")    # مقدار النزول في كل محاولة chase
DEFAULT_CHASE_MAX_ATTEMPTS = 6             # عدد محاولات IOC النازلة قبل الملاذ الأخير


def marketable_sell_price(reference_bid, band_pct, tick, rounding=ROUND_DOWN) -> Decimal:
    """سعر ``LIMIT`` SELL قابل للتنفيذ فورًا = أفضل BID حيّ ناقص ``band`` محكوم.

    التسعير عند/تحت أفضل BID يعبر السبريد فينفّذ فورًا للبيع؛ وصِغَر الـband يضمن
    القرب من السوق (لا بنطّة بعيدة). مُقرَّب لمضاعف tick. دالة **خالصة**.
    """
    ref = _dec(reference_bid)
    band = _dec(band_pct)
    if band < _ZERO:
        band = _ZERO
    return round_to_tick(ref * (Decimal("1") - band / _HUNDRED), tick, rounding=rounding)


def flash_crash_floor(reference_bid, floor_pct, tick, rounding=ROUND_DOWN) -> Decimal:
    """الأرضية الصارمة: أدنى سعر بيع مقبول = ``BID × (1 − floor_pct/100)`` (مضاعف tick).

    لا يُنفَّذ أي خروج تحت هذه الأرضية مهما حصل (خط الحماية الكارثي). دالة **خالصة**.
    """
    ref = _dec(reference_bid)
    fp = _dec(floor_pct)
    if fp < _ZERO:
        fp = _ZERO
    return round_to_tick(ref * (Decimal("1") - fp / _HUNDRED), tick, rounding=rounding)


def plan_chase_ladder(
    reference_bid,
    tick,
    *,
    band_pct=None,
    chase_step_pct=None,
    max_attempts=None,
    floor_pct=None,
) -> Dict[str, Any]:
    """يبني سُلّم أسعار ``IOC`` نازلة من قرب الـBID لحد الأرضية (دالة **خالصة**).

    - كل عنصر = ``BID × (1 − (band + i·step)/100)`` مُقرَّب لمضاعف tick أدنى.
    - لا ينزل أيّ عنصر تحت الأرضية؛ وآخر عنصر = الأرضية (لا بيع أرخص منها).
    - تناقص صارم (كل عنصر أدنى من سابقه بـtick على الأقل عند توفّر tick).

    يعيد ``{"ladder": [Decimal, ...], "floor": Decimal}``. لا شبكة ولا أثر جانبي.
    """
    ref = _dec(reference_bid)
    t = _dec(tick)
    band = _dec(band_pct if band_pct is not None else DEFAULT_BAND_PCT)
    step = _dec(chase_step_pct if chase_step_pct is not None else DEFAULT_CHASE_STEP_PCT)
    attempts = int(max_attempts if max_attempts is not None else DEFAULT_CHASE_MAX_ATTEMPTS)
    fp = _dec(floor_pct if floor_pct is not None else DEFAULT_PRICE_FLOOR_PCT)
    if attempts < 1:
        attempts = 1

    floor = flash_crash_floor(ref, fp, t)
    ladder: List[Decimal] = []
    for i in range(attempts):
        px = round_to_tick(
            ref * (Decimal("1") - (band + Decimal(i) * step) / _HUNDRED),
            t,
            rounding=ROUND_DOWN,
        )
        if px < floor:
            px = floor
        if ladder:
            prev = ladder[-1]
            if px >= prev:  # اضمن تناقصًا صارمًا
                px = (prev - t) if (t and (prev - t) >= floor) else floor
        ladder.append(px)
        if px <= floor:
            break
    return {"ladder": ladder, "floor": floor}


def compute_slippage_pct(reference_bid, filled_price) -> Decimal:
    """انزلاق البيع المئوي = ``(reference − filled)/reference × 100`` (موجب = أسوأ).

    يُستعمل في telemetry/الشفافية (السعر المطلوب مقابل المنفَّذ). دالة **خالصة**.
    """
    ref = _dec(reference_bid)
    fill = _dec(filled_price)
    if ref <= _ZERO:
        return _ZERO
    return (ref - fill) / ref * _HUNDRED


@dataclass
class ExitExecutionPolicy:
    """إعداد سياسة التنفيذ الموحّدة (قيم قابلة للضبط من الواجهة في chunk_5).

    ``last_resort_market`` = الخيار (ب) المعتمد: عند بلوغ الأرضية بلا تنفيذ، حوّل
    إلى ``MARKET`` محمي بالأرضية لضمان عدم التعليق (الـchase يملأ قرب السوق قبلها عادةً).
    """

    band_pct: Decimal = DEFAULT_BAND_PCT
    chase_step_pct: Decimal = DEFAULT_CHASE_STEP_PCT
    chase_max_attempts: int = DEFAULT_CHASE_MAX_ATTEMPTS
    floor_pct: Decimal = DEFAULT_PRICE_FLOOR_PCT
    last_resort_market: bool = True

    def ladder(self, reference_bid, tick) -> Dict[str, Any]:
        """سُلّم الـchase وفق هذه السياسة (يستدعي ``plan_chase_ladder``)."""
        return plan_chase_ladder(
            reference_bid,
            tick,
            band_pct=self.band_pct,
            chase_step_pct=self.chase_step_pct,
            max_attempts=self.chase_max_attempts,
            floor_pct=self.floor_pct,
        )


def execute_exit_chase(
    *,
    client,
    symbol: str,
    base_asset: str,
    bid_getter,
    target_qty,
    filters,
    client_order_id: str,
    exit_side: str = EXIT_UPPER,
    policy: "ExitExecutionPolicy" = None,
    order_list_id=None,
    kill_switch=None,
    notifier=None,
    sleeper=None,
    chase_interval_s=None,
    audit_sink=None,
    source: str = "",
    trade_uid: str = "",
    dry_run: bool = True,
) -> Dict[str, Any]:
    """طبقة الربط الحيّة لسياسة الخروج الموحّدة (G1.49) فوق الخطط الخالصة.

    الهدف المعتمد: «لا تعليق + أقرب نقطة سعرية في الطوارئ». الآلية:
      1) أمان بالترتيب: ``kill_switch`` (idempotent) ⇒ إلغاء OCO (تحرير الرصيد) ⇒
         **RECONCILE** (أي بيع حمائي قائم ⇒ ``ABORT_PROTECTED`` بلا وضع — لا بيع
         مزدوج) ⇒ ``remaining = min(target, free)`` (⇐ ``ABORT_NO_FREE_QTY`` إن صفر).
      2) **chase نازل**: في كل محاولة يُعاد قراءة أفضل BID حيّ (``bid_getter``)
         ويُسعَّر ``LIMIT IOC`` قابل للتنفيذ = ``marketable_sell_price(bid, band+i·step)``
         لا أدنى من **الأرضية** المثبّتة على BID البداية (``flash_crash_floor``)؛ IOC
         ⇒ ينفّذ فورًا أو يُلغى (لا أمر راقد ⇒ لا تعليق). يُطرح ``executedQty`` من المتبقّي.
      3) **ملاذ (ب)**: إن بقي متبقٍّ بعد بلوغ الأرضية/استنفاد المحاولات و
         ``policy.last_resort_market`` ⇒ ``MARKET`` SELL للمتبقّي (لا يُلجأ إليه إلا بعد
         استنزاف السُّلّم المحكوم بالأرضية).

    كل التبعيات محقونة (``client``/``bid_getter``/``kill_switch``/``notifier``/``sleeper``)
    ⇒ قابلة للاختبار بالكامل بلا شبكة. ``dry_run`` بلا أيّ أثر جانبي (معاينة السُّلّم فقط).
    لا تمسّ hot_path. يتطلّب ``client.place_limit_sell_ioc`` + ``place_market_sell``.
    Testnet فقط (لا Live قبل G1).
    """
    pol = policy if policy is not None else ExitExecutionPolicy()
    tick = _dec(getattr(filters, "tick_size", 0) or 0)
    step = getattr(filters, "step_size", None)
    min_qty = _dec(getattr(filters, "min_qty", 0) or 0)
    min_notional = _dec(getattr(filters, "min_notional", 0) or 0)

    def _ref_bid() -> Decimal:
        try:
            return _dec(bid_getter())
        except Exception:  # pragma: no cover - دفاعي
            return _ZERO

    init_bid = _ref_bid()
    floor = flash_crash_floor(init_bid, pol.floor_pct, tick) if init_bid > _ZERO else _ZERO

    # ---- تشغيل جافّ: معاينة خالصة بلا أثر جانبي ----
    if dry_run:
        preview = pol.ladder(init_bid, tick) if init_bid > _ZERO else {"ladder": [], "floor": _ZERO}
        if audit_sink is not None:
            _emit_exit_execution(audit_sink, build_exit_execution_record(
                source=source, exit_side=exit_side, order_type="LIMIT_IOC", tif=TIF_IOC,
                requested_price=None, filled_price=None, live_bid=init_bid, slippage_pct=None,
                band_pct=pol.band_pct, attempts_used=0, reached_floor=False,
                floor_price=preview["floor"], qty=_dec(target_qty), trade_uid=trade_uid, dry_run=True))
        return _result("DRY_RUN", symbol, exit_side, placed=False,
                       reference_bid=init_bid, floor=preview["floor"],
                       ladder=preview["ladder"], client_order_id=client_order_id,
                       steps=[("dry_run_preview", True)])

    steps: List[Any] = []

    # 1) إيقاف المراقبة أولًا (لا يُفشِل الخروج إن رمى).
    if kill_switch is not None:
        try:
            kill_switch()
            steps.append(("monitoring_stopped", True))
        except Exception as exc:  # pragma: no cover - دفاعي
            steps.append(("kill_switch_error", repr(exc)))

    # 2) إلغاء OCO القائم لتحرير الرصيد المقفول.
    if order_list_id is not None:
        client.cancel_oco(symbol, order_list_id)
        steps.append(("oco_cancelled", order_list_id))

    # 3) RECONCILE — منع البيع المزدوج بعد الإلغاء.
    resting = client.get_open_sell_orders(symbol)
    if resting:
        return _result("ABORT_PROTECTED", symbol, exit_side, placed=False,
                       reason="resting protective sell present after cancel — double-sell abort",
                       resting_orders=len(resting), steps=steps)

    # 4) الرصيد الحرّ ⇒ remaining = min(target, free).
    free = _dec(client.get_free_asset_qty(base_asset))
    remaining = min(_dec(target_qty), free)
    if remaining <= _ZERO:
        return _result("ABORT_NO_FREE_QTY", symbol, exit_side, placed=False,
                       reason="no free base balance to exit", free=free, steps=steps)

    attempts: List[Dict[str, Any]] = []
    filled_total = _ZERO
    reached_floor = False
    last_price = None
    commission_total = _ZERO          # G1.53/chunk_3: عمولة مُجمَّعة (best-effort)
    commission_asset: Optional[str] = None

    for i in range(max(1, int(pol.chase_max_attempts))):
        bid = _ref_bid()
        if bid <= _ZERO:
            steps.append(("no_bid", i))
            break
        price = marketable_sell_price(bid, pol.band_pct + Decimal(i) * pol.chase_step_pct, tick)
        if floor > _ZERO and price < floor:
            price = floor
            reached_floor = True
        last_price = price
        qty = floor_to_step(remaining, step)
        if (qty <= _ZERO or (min_qty > _ZERO and qty < min_qty)
                or (min_notional > _ZERO and qty * price < min_notional)):
            steps.append(("dust_stop", {"remaining": str(remaining), "qty": str(qty)}))
            break
        resp = client.place_limit_sell_ioc(
            symbol=symbol, quantity=qty, price=price,
            client_order_id="%s-ioc-%d" % (client_order_id, i)) or {}
        _cc, _ca = sum_commission(resp)
        commission_total += _cc
        if _ca:
            commission_asset = _ca
        executed = _dec(resp.get("executedQty", 0))
        if executed < _ZERO:
            executed = _ZERO
        if executed > qty:
            executed = qty
        filled_total += executed
        remaining -= executed
        attempts.append({"i": i, "price": price, "qty": qty,
                         "executed": executed, "status": resp.get("status")})
        if remaining <= _ZERO:
            break
        if reached_floor:
            break
        if sleeper is not None and chase_interval_s is not None:
            try:
                sleeper(chase_interval_s)
            except Exception:  # pragma: no cover - دفاعي
                pass

    remaining_step = floor_to_step(remaining, step) if remaining > _ZERO else _ZERO
    market_resp = None
    if (remaining_step > _ZERO and pol.last_resort_market
            and (min_qty <= _ZERO or remaining_step >= min_qty)):
        market_resp = client.place_market_sell(
            symbol=symbol, quantity=remaining_step,
            client_order_id="%s-mkt" % client_order_id)
        _cc, _ca = sum_commission(market_resp)
        commission_total += _cc
        if _ca:
            commission_asset = _ca
        steps.append(("last_resort_market", str(remaining_step)))
        filled_total += remaining_step
        remaining -= remaining_step

    if filled_total <= _ZERO:
        action, placed = "ABORT_NOT_FILLED", False
    elif remaining > _ZERO:
        action, placed = "PARTIAL", True
    elif market_resp is not None:
        action, placed = "MARKET_FALLBACK", True
    else:
        action, placed = "FILLED", True

    slippage = compute_slippage_pct(init_bid, last_price) if (last_price and init_bid > _ZERO) else _ZERO
    result = _result(
        action, symbol, exit_side, placed=placed, filled_qty=filled_total,
        remaining_qty=(remaining if remaining > _ZERO else _ZERO), attempts=attempts,
        floor=floor, reference_bid=init_bid, last_price=last_price,
        slippage_pct=slippage, market_fallback=(market_resp is not None),
        free=free, client_order_id=client_order_id, steps=steps)
    if audit_sink is not None:
        _emit_exit_execution(audit_sink, build_exit_execution_record(
            source=source, exit_side=exit_side,
            order_type=("MARKET" if market_resp is not None else "LIMIT_IOC"),
            tif=(None if market_resp is not None else TIF_IOC),
            requested_price=last_price, filled_price=None, live_bid=init_bid,
            slippage_pct=slippage, band_pct=pol.band_pct, attempts_used=len(attempts),
            reached_floor=reached_floor, floor_price=floor, qty=filled_total,
            trade_uid=trade_uid, dry_run=False,
            commission=(commission_total if commission_total > _ZERO else None),
            commission_asset=commission_asset))
    if notifier is not None:
        try:
            notifier(result)
        except Exception as exc:  # pragma: no cover - دفاعي
            result["notify_error"] = repr(exc)
    return result
