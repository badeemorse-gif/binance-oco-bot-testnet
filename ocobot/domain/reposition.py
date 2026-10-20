"""Reposition draft + Safe Execution (M2 / T3).

يبني مسودّة إعادة تموضع (Manual Edit Draft، قراءة فقط — P2) ثم ينفّذها بأمان:
cancel ثم create لأمر OCO واحد محدَّد فقط (P3)، مع:
  - Pre-Cancel Validation Gate (D16): يتحقق من البديل كاملًا قبل أي إلغاء.
  - Partial-Fill early-abort (D17): إن كانت المتبقية تحت minNotional/minQty ⇒ Abort قبل الإلغاء.
  - Idempotency (D10): listClientOrderId فريد + recheck-before-retry عند ضياع الردّ.
  - No Blind Retry (D9): Cancel OK + Create FAILED ⇒ FAILED_NEEDS_ATTENTION يدوي.
  - Naked Window (D19): لا cancelReplace ذرّي؛ الواجهة تُبرز النافذة العارية.

reference_price مُدخَل صريح (D14 — لا سعر حيّ مُختلَق حتى Market WS في T4).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING, Callable, List, Optional
from uuid import uuid4

from ocobot.core.errors import BinanceApiError, TransportError

if TYPE_CHECKING:  # hint only — audit sink is duck-typed at runtime
    from ..core.audit_log import AuditLog
from ocobot.domain.models import fmt
from ocobot.domain.dynamic_exit import next_stop
from ocobot.domain.pricing import (
    DEFAULT_GAP_TICKS,
    compute_levels,
    floor_to_step,
    is_multiple_of,
)

PATH_CREATE_OCO = "/api/v3/orderList/oco"
PATH_CANCEL = "/api/v3/orderList"
PATH_RECHECK = "/api/v3/orderList"

# رسائل بشرية (عربية)
MSG_FAILED_NEEDS_ATTENTION = (
    "تم إلغاء الأمر المحدد، لكن إنشاء البديل فشل — لا توجد إعادة محاولة تلقائية. "
    "تدخّل يدوي مطلوب."
)
MSG_PARTIAL_FILL_ABORT = (
    "الكمية المتبقية بعد التنفيذ الجزئي أقل من الحد الأدنى — أُلغي الإجراء قبل أي "
    "إلغاء لتفادي مركز عارٍ (no naked position). (D17)"
)


class ExecutionState(str, Enum):
    IDLE = "IDLE"
    COMPUTING = "COMPUTING"
    GATE_PASSED = "GATE_PASSED"
    REPOSITIONING = "REPOSITIONING"
    SUCCESS = "SUCCESS"
    ABORTED = "ABORTED"
    FAILED_NEEDS_ATTENTION = "FAILED_NEEDS_ATTENTION"


@dataclass
class RepositionDraft:
    symbol: str
    quantity: Optional[Decimal]
    tp_price: Optional[Decimal]
    stop_trigger: Optional[Decimal]
    stop_limit: Optional[Decimal]
    reference_price: Optional[Decimal]
    tp_pct: Optional[Decimal]
    sl_pct: Optional[Decimal]
    filters: object = None
    old_tp: Optional[Decimal] = None
    old_stop_trigger: Optional[Decimal] = None
    old_stop_limit: Optional[Decimal] = None
    gap_ticks: int = DEFAULT_GAP_TICKS
    side: str = "SELL"

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "side": self.side,
            "quantity": fmt(self.quantity),
            "tpPrice": fmt(self.tp_price),
            "stopTrigger": fmt(self.stop_trigger),
            "stopLimit": fmt(self.stop_limit),
            "referencePrice": fmt(self.reference_price),
            "tpPct": fmt(self.tp_pct),
            "slPct": fmt(self.sl_pct),
            "oldTp": fmt(self.old_tp),
            "oldStopTrigger": fmt(self.old_stop_trigger),
            "oldStopLimit": fmt(self.old_stop_limit),
            "gapTicks": self.gap_ticks,
            "filters": self.filters.to_dict() if self.filters else None,
        }


@dataclass
class GateResult:
    ok: bool
    failures: List[str] = field(default_factory=list)
    partial_fill_abort: bool = False


@dataclass
class ExecutionStep:
    key: str
    label: str
    status: str            # pending / done / failed / skipped / naked
    detail: str = ""
    naked_window: bool = False


@dataclass
class ExecutionResult:
    state: ExecutionState
    steps: List[ExecutionStep]
    draft: Optional[RepositionDraft] = None
    cancelled_order_list_id: Optional[int] = None
    new_order_list_id: Optional[int] = None
    reason: str = ""
    messages: List[str] = field(default_factory=list)
    gate: Optional[GateResult] = None


def validate_pre_cancel(draft: RepositionDraft, last_price, filters,
                        available_qty=None) -> GateResult:
    """بوابة ما قبل الإلغاء (D16): تحقّق من البديل كاملًا قبل أي كتابة.

    الترتيب: (1) Partial-Fill (D17) → (2) Strict order (D4) → (3) tick multiples →
    (4) qty step & minQty → (5) minNotional لكل رِجل مُسعّرة → (6) balance (اختياري).
    تُجمَع كل الإخفاقات (لا توقف عند أول خطأ) لعرضها للمستخدم.
    """
    failures: List[str] = []
    partial_fill_abort = False

    last = Decimal(str(last_price)) if last_price is not None else None
    tp = draft.tp_price
    trg = draft.stop_trigger
    lim = draft.stop_limit
    qty = draft.quantity

    tick = getattr(filters, "tick_size", None)
    step = getattr(filters, "step_size", None)
    min_qty = getattr(filters, "min_qty", None)
    min_notional = getattr(filters, "min_notional", None)

    # (1) Partial-Fill edge (D17): المتبقية تحت الحد الأدنى ⇒ Abort مبكّر مميّز
    priced_below = lim if lim is not None else trg
    if qty is not None:
        if min_qty is not None and qty < min_qty:
            partial_fill_abort = True
        if (min_notional is not None and priced_below is not None
                and qty * priced_below < min_notional):
            partial_fill_abort = True
    if partial_fill_abort:
        failures.append(MSG_PARTIAL_FILL_ABORT)
        # مع ذلك نُكمل بقية الفحوص لتجميع صورة كاملة للمستخدم

    # (2) الترتيب الصارم (D4): Stop Limit < Stop Trigger < Last < TP
    if None in (lim, trg, last, tp):
        failures.append("ترتيب صارم غير قابل للتحقق: قيمة سعرية مفقودة.")
    else:
        if not (lim < trg < last < tp):
            failures.append(
                f"انتهاك الترتيب الصارم (D4): يجب Stop Limit({fmt(lim)}) < "
                f"Trigger({fmt(trg)}) < Last({fmt(last)}) < TP({fmt(tp)})."
            )

    # (3) كل الأسعار مضاعفات tickSize (D8)
    if tick:
        for name, val in (("TP", tp), ("Stop Trigger", trg), ("Stop Limit", lim)):
            if val is not None and not is_multiple_of(val, tick):
                failures.append(f"{name}({fmt(val)}) ليس مضاعفًا لِ tickSize({fmt(tick)}).")

    # (4) الكمية مضاعف stepSize و ≥ minQty (D8)
    if qty is not None:
        if step and not is_multiple_of(qty, step):
            failures.append(f"الكمية({fmt(qty)}) ليست مضاعفًا لِ stepSize({fmt(step)}).")
        if min_qty is not None and qty < min_qty:
            failures.append(f"الكمية({fmt(qty)}) أقل من minQty({fmt(min_qty)}).")

    # (5) minNotional لكل رِجل مُسعّرة (tp للأعلى، stop_limit للأسفل) (D8)
    if qty is not None and min_notional is not None:
        if tp is not None and qty * tp < min_notional:
            failures.append(
                f"قيمة رِجل TP ({fmt(qty * tp)}) أقل من minNotional({fmt(min_notional)})."
            )
        if priced_below is not None and qty * priced_below < min_notional:
            failures.append(
                f"قيمة الرِّجل السفلية ({fmt(qty * priced_below)}) أقل من "
                f"minNotional({fmt(min_notional)})."
            )

    # (6) فحص الرصيد الاختياري (D16): الكمية لا تتجاوز المتاح
    if available_qty is not None and qty is not None:
        avail = Decimal(str(available_qty))
        if qty > avail:
            failures.append(f"الكمية({fmt(qty)}) تتجاوز المتاح({fmt(avail)}).")

    return GateResult(ok=not failures, failures=failures,
                      partial_fill_abort=partial_fill_abort)


def _default_id_factory(prefix: str) -> str:
    # <=36 حرفًا (Binance-safe): بادئة قصيرة + 20 hex
    return f"{prefix}-{uuid4().hex[:20]}"


class SafeExecutor:
    def __init__(self, client, reader, exchange_info, id_factory=None,
                 gap_ticks=DEFAULT_GAP_TICKS, audit: Optional["AuditLog"] = None):
        self._client = client
        self._reader = reader
        self._exchange_info = exchange_info
        self._id_factory = id_factory or _default_id_factory
        self._gap_ticks = gap_ticks
        self._audit = audit

    def _record(self, event, details):
        # التدقيق اختياري ولا يجب أن يكسر التنفيذ أبدًا (backward-compatible).
        if self._audit is not None:
            try:
                self._audit.record(event, details)
            except Exception:
                pass   # auditing must never break execution

    # ---- draft (read-only, P2) ----
    def build_draft(self, order_list_id: int, tp_pct, sl_pct, reference_price, *,
                    dynamic_exit=None, peak_price=None, prev_stop=None, live_atr_pct_value=None):
        oco = self._reader.get_oco(order_list_id)          # P1: إعادة تحقق الهوية
        filters = self._exchange_info.get_filters(oco.symbol)  # D8

        tp_pct = Decimal(str(tp_pct))
        sl_pct = Decimal(str(sl_pct))
        reference_price = Decimal(str(reference_price))

        # G1.65 adaptive exit (behind flag; default None => identical behavior)
        eff_sl_pct = sl_pct
        if (dynamic_exit is not None and dynamic_exit.enabled
                and peak_price is not None and prev_stop is not None
                and live_atr_pct_value is not None and reference_price > 0):
            _ns = next_stop(
                float(reference_price), float(peak_price), float(prev_stop),
                float(live_atr_pct_value), p=dynamic_exit.params(),
            )
            eff_sl_pct = (Decimal("1") - Decimal(str(_ns)) / reference_price) * Decimal("100")

        remaining = oco.remaining_qty
        qty = floor_to_step(remaining, filters.step_size) if remaining is not None else None  # D7

        tp, trg, lim = compute_levels(
            reference_price, tp_pct, eff_sl_pct, filters.tick_size, gap_ticks=self._gap_ticks
        )

        draft = RepositionDraft(
            symbol=oco.symbol,
            quantity=qty,
            tp_price=tp,
            stop_trigger=trg,
            stop_limit=lim,
            reference_price=reference_price,
            tp_pct=tp_pct,
            sl_pct=eff_sl_pct,
            filters=filters,
            old_tp=oco.tp_price,
            old_stop_trigger=oco.stop_trigger,
            old_stop_limit=oco.stop_limit,
            gap_ticks=self._gap_ticks,
        )
        return oco, draft

    # ---- draft from Live bridge (read-only, P2) — G1.59 ----
    def build_draft_from_bridge(self, order_list_id: int, bridge, reference_price):
        """يبني مسودّة «الدورة التالية» من نِسب الوصلة الحيّة (Live/أساس) — قراءة فقط (P2).

        لا يُلغي ولا يُنشئ أي أمر (ليست T16)، ولا يمسّ الأمر المفتوح لحظيًا: مجرّد
        توجيه نِسب «الدورة التالية فقط» من RepositionRecommendationBridge إلى
        build_draft القائمة بلا أي تغيير في سلوكها أو رسائلها.
        """
        pcts = bridge.pcts_for_next_cycle()
        return self.build_draft(order_list_id, pcts.tp_pct, pcts.sl_pct, reference_price)

    # ---- execute (may write, only after Activate) ----
    def execute(self, order_list_id: int, tp_pct, sl_pct, reference_price,
                dry_run=False, *,
                dynamic_exit=None, peak_price=None, prev_stop=None, live_atr_pct_value=None) -> ExecutionResult:
        steps = [
            ExecutionStep("verify", "① إعادة التحقق من هوية الأمر (P1)", "pending"),
            ExecutionStep("price", "② السعر المرجعي + الكمية المتبقية (D6/D7)", "pending"),
            ExecutionStep("recalc", "③ إعادة حساب الأسعار الثلاثة (D4/D5)", "pending"),
            ExecutionStep("gate", "④ بوابة ما قبل الإلغاء (D16)", "pending"),
            ExecutionStep("cancel", "⑤ إلغاء الأمر المحدد (P3)", "pending", naked_window=True),
            ExecutionStep("create", "⑥ إنشاء الأمر البديل", "pending", naked_window=True),
            ExecutionStep("confirm", "⑦ التأكيد النهائي", "pending"),
        ]
        by_key = {s.key: s for s in steps}
        result = ExecutionResult(state=ExecutionState.COMPUTING, steps=steps)

        # ① + ② + ③ : بناء المسودّة
        try:
            oco, draft = self.build_draft(order_list_id, tp_pct, sl_pct, reference_price,
                                          dynamic_exit=dynamic_exit, peak_price=peak_price,
                                          prev_stop=prev_stop, live_atr_pct_value=live_atr_pct_value)
        except (BinanceApiError, TransportError) as exc:
            by_key["verify"].status = "failed"
            by_key["verify"].detail = str(exc)
            result.state = ExecutionState.ABORTED
            result.reason = f"تعذّر بناء المسودّة: {exc}"
            result.messages.append(result.reason)
            for k in ("price", "recalc", "gate", "cancel", "create", "confirm"):
                by_key[k].status = "skipped"
            self._record("abort", {
                "order_list_id": order_list_id,
                "stage": "build",
                "reason": result.reason,
            })
            return result

        result.draft = draft
        reference_price = draft.reference_price
        self._record("draft_built", {
            "order_list_id": oco.order_list_id,
            "symbol": draft.symbol,
            "tp_pct": draft.tp_pct,
            "sl_pct": draft.sl_pct,
            "tp_price": draft.tp_price,
            "stop_trigger": draft.stop_trigger,
            "stop_limit": draft.stop_limit,
            "reference_price": draft.reference_price,
            "quantity": draft.quantity,
            "dry_run": dry_run,
        })
        by_key["verify"].status = "done"
        by_key["verify"].detail = f"orderListId={oco.order_list_id} symbol={oco.symbol}"
        by_key["price"].status = "done"
        by_key["price"].detail = (
            f"Reference={fmt(reference_price)} | Remaining qty={fmt(draft.quantity)}"
        )
        by_key["recalc"].status = "done"
        by_key["recalc"].detail = (
            f"TP={fmt(draft.tp_price)} Trigger={fmt(draft.stop_trigger)} "
            f"Limit={fmt(draft.stop_limit)}"
        )

        # ④ Pre-Cancel Gate (D16) — السعر المرجعي هو "Last" هنا (D14: مُدخَل صريح)
        gate = validate_pre_cancel(draft, reference_price, draft.filters)
        result.gate = gate
        if not gate.ok:
            by_key["gate"].status = "failed"
            by_key["gate"].detail = " | ".join(gate.failures)
            for k in ("cancel", "create", "confirm"):
                by_key[k].status = "skipped"
            result.state = ExecutionState.ABORTED
            if gate.partial_fill_abort:
                result.reason = MSG_PARTIAL_FILL_ABORT
                result.messages.append(MSG_PARTIAL_FILL_ABORT)
            else:
                result.reason = "فشلت بوابة ما قبل الإلغاء — الأمر الأصلي سليم (D16)."
            result.messages.extend(gate.failures)
            self._record("abort", {
                "order_list_id": oco.order_list_id,
                "symbol": draft.symbol,
                "stage": "gate",
                "partial_fill": gate.partial_fill_abort,
                "failures": gate.failures,
                "reason": result.reason,
            })
            return result

        by_key["gate"].status = "done"
        by_key["gate"].detail = "اجتازت كل الفحوص."

        # dry_run: توقّف عند GATE_PASSED — لا كتابة إطلاقًا (P2)
        if dry_run:
            for k in ("cancel", "create", "confirm"):
                by_key[k].status = "skipped"
            result.state = ExecutionState.GATE_PASSED
            result.messages.append("Draft فقط (Read-only): لا تغيير قبل Activate (P2).")
            self._record("dry_run_gate_passed", {
                "order_list_id": oco.order_list_id,
                "symbol": draft.symbol,
            })
            return result

        # مُعرِّفات فريدة لكل execute() (D10 — Idempotency)
        list_id = self._id_factory("ocl")
        above_id = self._id_factory("oca")
        below_id = self._id_factory("ocb")

        result.state = ExecutionState.REPOSITIONING

        # ⑤ إلغاء الأمر المحدد فقط (P3) — بداية النافذة العارية (D19)
        self._record("before_cancel", {
            "order_list_id": oco.order_list_id,
            "symbol": draft.symbol,
        })
        try:
            self._client.signed_request(
                "DELETE", PATH_CANCEL,
                [("symbol", draft.symbol), ("orderListId", int(oco.order_list_id))],
            )
            by_key["cancel"].status = "done"
            by_key["cancel"].detail = f"أُلغي orderListId={oco.order_list_id}"
            result.cancelled_order_list_id = int(oco.order_list_id)
            self._record("cancel_ok", {
                "cancelled_order_list_id": result.cancelled_order_list_id,
                "symbol": draft.symbol,
            })
        except (BinanceApiError, TransportError) as exc:
            # فشل الإلغاء / الأمر مفقود ⇒ ABORTED بلا إنشاء (D9)
            by_key["cancel"].status = "failed"
            by_key["cancel"].detail = str(exc)
            by_key["create"].status = "skipped"
            by_key["confirm"].status = "skipped"
            result.state = ExecutionState.ABORTED
            result.reason = f"فشل الإلغاء — لم يُنشأ بديل، الأمر الأصلي سليم/غير مؤكَّد: {exc}"
            result.messages.append(result.reason)
            self._record("abort", {
                "order_list_id": oco.order_list_id,
                "symbol": draft.symbol,
                "stage": "cancel",
                "reason": result.reason,
            })
            return result

        # ⑥ إنشاء البديل — لا يزال داخل النافذة العارية (D19)
        create_params = [
            ("symbol", draft.symbol),
            ("side", "SELL"),
            ("quantity", fmt(draft.quantity)),
            ("aboveType", "LIMIT_MAKER"),
            ("abovePrice", fmt(draft.tp_price)),
            ("belowType", "STOP_LOSS_LIMIT"),
            ("belowStopPrice", fmt(draft.stop_trigger)),
            ("belowPrice", fmt(draft.stop_limit)),
            ("belowTimeInForce", "GTC"),
            ("aboveClientOrderId", above_id),
            ("belowClientOrderId", below_id),
            ("listClientOrderId", list_id),
        ]
        try:
            resp = self._client.signed_request("POST", PATH_CREATE_OCO, create_params)
        except TransportError:
            # D10: ردّ ضائع بعد إصدار الإنشاء ⇒ recheck واحد (check-before-retry)
            by_key["create"].status = "pending"
            by_key["create"].detail = "ردّ ضائع — فحص واحد قبل أي إعادة (D10)."
            return self._recheck_after_lost_create(result, by_key, list_id)
        except BinanceApiError as exc:
            # D9: Cancel OK + Create FAILED ⇒ FAILED_NEEDS_ATTENTION (يدوي)
            by_key["create"].status = "failed"
            by_key["create"].detail = str(exc)
            by_key["confirm"].status = "skipped"
            result.state = ExecutionState.FAILED_NEEDS_ATTENTION
            result.reason = MSG_FAILED_NEEDS_ATTENTION
            result.messages.append(MSG_FAILED_NEEDS_ATTENTION)
            self._record("failed_needs_attention", {
                "cancelled_order_list_id": result.cancelled_order_list_id,
                "symbol": draft.symbol,
                "reason": result.reason,
            })
            return result

        new_id = resp.get("orderListId")
        by_key["create"].status = "done"
        by_key["create"].detail = f"أُنشئ OCO الجديد listClientOrderId={list_id}"
        result.new_order_list_id = new_id

        # ⑦ تأكيد + rollover
        by_key["confirm"].status = "done"
        by_key["confirm"].detail = f"OCO الجديد: {new_id}"
        result.state = ExecutionState.SUCCESS
        result.messages.append(
            f"نجحت إعادة التموضع: أُلغي {result.cancelled_order_list_id} وأُنشئ {new_id}."
        )
        self._record("after_create", {
            "new_order_list_id": new_id,
            "cancelled_order_list_id": result.cancelled_order_list_id,
            "symbol": draft.symbol,
            "list_client_order_id": list_id,
            "above_client_order_id": above_id,
            "below_client_order_id": below_id,
        })
        self._record("reposition_success", {
            "cancelled_order_list_id": result.cancelled_order_list_id,
            "new_order_list_id": new_id,
            "symbol": draft.symbol,
            "tp_price": draft.tp_price,
            "stop_trigger": draft.stop_trigger,
            "stop_limit": draft.stop_limit,
        })
        return result

    def _recheck_after_lost_create(self, result, by_key, list_id) -> ExecutionResult:
        """D10: فحص واحد GET /orderList بالـ listClientOrderId — لا كتابة ثانية أبدًا."""
        try:
            resp = self._client.signed_request(
                "GET", PATH_RECHECK, [("listClientOrderId", list_id)]
            )
        except (BinanceApiError, TransportError) as exc:
            by_key["create"].status = "failed"
            by_key["confirm"].status = "skipped"
            result.state = ExecutionState.FAILED_NEEDS_ATTENTION
            result.reason = MSG_FAILED_NEEDS_ATTENTION
            result.messages.append(f"تعذّر الفحص بعد ضياع الردّ: {exc}")
            result.messages.append(MSG_FAILED_NEEDS_ATTENTION)
            self._record("failed_needs_attention", {
                "symbol": result.draft.symbol if result.draft else None,
                "reason": result.reason,
                "recheck": True,
            })
            return result

        new_id = resp.get("orderListId")
        if isinstance(new_id, int) and new_id > 0:
            # الأمر موجود فعلًا ⇒ نجاح رغم ضياع الردّ
            by_key["create"].status = "done"
            by_key["create"].detail = f"مؤكَّد عبر الفحص: orderListId={new_id}"
            by_key["confirm"].status = "done"
            by_key["confirm"].detail = f"OCO الجديد: {new_id}"
            result.new_order_list_id = new_id
            result.state = ExecutionState.SUCCESS
            result.messages.append(
                f"تأكّد إنشاء البديل بعد ضياع الردّ (idempotency): {new_id}."
            )
            self._record("after_create", {
                "recheck": True,
                "new_order_list_id": new_id,
                "cancelled_order_list_id": result.cancelled_order_list_id,
                "symbol": (result.draft.symbol if result.draft else None),
            })
            return result

        # غير موجود ⇒ تدخّل يدوي (بلا إعادة كتابة، D9/D10)
        by_key["create"].status = "failed"
        by_key["confirm"].status = "skipped"
        result.state = ExecutionState.FAILED_NEEDS_ATTENTION
        result.reason = MSG_FAILED_NEEDS_ATTENTION
        result.messages.append("الفحص أظهر عدم وجود الأمر — لا إعادة محاولة (D10).")
        result.messages.append(MSG_FAILED_NEEDS_ATTENTION)
        self._record("failed_needs_attention", {
            "symbol": result.draft.symbol if result.draft else None,
            "reason": result.reason,
            "recheck": True,
        })
        return result


# ====================================================================
# G1.59 — جسر تطبيق Live لمتتبّع مُرشِّح النِّسب على «دورة التموضع التالية فقط».
# وحدة domain خالصة (بلا Qt/شبكة). لا تمسّ الأمر المفتوح لحظيًا ولا hot_path،
# ولا تنفّذ أي أمر Live فعلي (ليست T16). الأثر مؤجَّل حصراً إلى الدورة التالية.
# ====================================================================

def _opt_dec(value):
    """تحويل آمن إلى Decimal (أو None لو None) — لا يرفع استثناءً على None."""
    if value is None:
        return None
    return value if isinstance(value, Decimal) else Decimal(str(value))


@dataclass
class NextCyclePcts:
    """النِّسب التي ستُغذّي حساب دورة التموضع التالية فقط (لا الأمر القائم)."""
    tp_pct: Optional[Decimal]
    sl_pct: Optional[Decimal]
    trigger_pct: Optional[Decimal]
    source: str              # "base" | "live_rec"
    reason: str = ""         # آخر سبب من المتتبّع: first|applied|observe|off|cooldown|hysteresis|session_cap


class RepositionRecommendationBridge:
    """يربط RecommendationTracker بنِسب «دورة التموضع التالية فقط» (G1.59).

    يحتفظ بنِسب أساس (base) وبآخر نِسب اعتُمدت في MODE_LIVE، ويقرّر — عبر
    ``tracker.offer`` — أيّها يُغذّي بناء المسودّة التالية. الأثر مؤجَّل حصراً
    إلى الدورة التالية؛ لا مسّ للأمر المفتوح لحظيًا ولا لأي hot_path، ولا تنفيذ
    T16. حارس صريح ``enabled``: ما لم يكن True ويكن المتتبّع في MODE_LIVE وقد
    اعتُمد القرار (``decision.applied``)، تبقى الوصلة خاملة الأثر على التموضع.
    """

    def __init__(self, tracker, *, base_tp_pct=None, base_sl_pct=None,
                 base_trigger_pct=None, enabled: bool = True,
                 audit: Optional[Callable[[dict], None]] = None):
        self._tracker = tracker
        self._base = (_opt_dec(base_tp_pct), _opt_dec(base_sl_pct),
                      _opt_dec(base_trigger_pct))
        self._live = None            # (tp, sl, trigger) آخر اعتماد Live
        self._enabled = bool(enabled)
        self._audit_cb = audit
        self.audit_log: List[dict] = []
        self.last_decision = None
        self.last_reason = ""

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, value: bool) -> None:
        self._enabled = bool(value)

    @property
    def mode(self):
        return getattr(self._tracker, "mode", None)

    def set_base(self, tp_pct=None, sl_pct=None, trigger_pct=None) -> None:
        self._base = (_opt_dec(tp_pct), _opt_dec(sl_pct), _opt_dec(trigger_pct))

    def reset_live(self) -> None:
        self._live = None

    def offer(self, rec, now=None):
        """يمرّر الاقتراح للمتتبّع؛ ويعتمد نِسبه للدورة التالية فقط إن طُبِّق Live والحارس مفعّل."""
        decision = self._tracker.offer(rec, now)
        self.last_decision = decision
        self.last_reason = decision.reason
        applied_to_next_cycle = False
        if self._enabled and decision.applied and rec is not None:
            self._live = (_opt_dec(rec.tp_pct), _opt_dec(rec.sl_pct),
                          _opt_dec(rec.trigger_pct))
            applied_to_next_cycle = True
        self._emit_audit({
            "event": "reposition_bridge_offer",
            "enabled": self._enabled,
            "mode": decision.mode,
            "reason": decision.reason,
            "tracker_applied": decision.applied,
            "applied_to_next_cycle": applied_to_next_cycle,
            "tpPct": None if rec is None else str(rec.tp_pct),
            "slPct": None if rec is None else str(rec.sl_pct),
            "triggerPct": None if rec is None else str(rec.trigger_pct),
        })
        return decision

    def pcts_for_next_cycle(self) -> NextCyclePcts:
        """النِّسب للدورة التالية: المُعتمدة Live إن وُجدت، وإلا الأساس."""
        if self._live is not None:
            tp, sl, trig = self._live
            return NextCyclePcts(tp, sl, trig, "live_rec", self.last_reason)
        tp, sl, trig = self._base
        return NextCyclePcts(tp, sl, trig, "base", self.last_reason)

    def _emit_audit(self, record: dict) -> None:
        self.audit_log.append(record)
        if callable(self._audit_cb):
            try:
                self._audit_cb(record)
            except Exception:
                pass
