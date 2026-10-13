"""G1.13: تحويل أي أمر بيع (LIMIT/STOP/TRAILING/OCO) إلى OCO جديد (TP+SL) محسوب
من السعر الحي (D-G1.13-refprice)، ثم تسليم orderListId الجديد للمراقبة.
يُعيد استخدام آلة reposition المختومة (بوّابة D16، partial-fill D17، ترتيب SELL D4،
فلاتر tick/step/notional) وأنواع ExecutionResult كما هي — فتعمل معه SafeExecutionScreen
دون تغيير. الفرق الوحيد: المصدر أي أمر، والإلغاء يختار النقطة الصحيحة."""
from __future__ import annotations
from decimal import Decimal
from uuid import uuid4

from ocobot.domain.models import OpenSellOrder, fmt
from ocobot.domain.pricing import compute_levels, floor_to_step, DEFAULT_GAP_TICKS
from ocobot.domain.reposition import (
    ExecutionState, ExecutionResult, ExecutionStep, RepositionDraft, validate_pre_cancel,
)

PATH_CREATE_OCO = "/api/v3/orderList/oco"
PATH_ORDERLIST = "/api/v3/orderList"   # DELETE (cancel OCO) + GET (recheck)


def _default_id_factory(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:20]}"


class ConvertExecutor:
    def __init__(self, client, exchange_info, id_factory=None,
                 gap_ticks: int = DEFAULT_GAP_TICKS, audit=None):
        self._client = client
        self._exchange_info = exchange_info
        self._id_factory = id_factory or _default_id_factory
        self._gap_ticks = gap_ticks
        self._audit = audit

    def build_draft(self, source: OpenSellOrder, tp_pct, sl_pct, reference_price):
        filters = self._exchange_info.get_filters(source.symbol)
        remaining = Decimal(str(source.origQty)) - Decimal(str(source.executedQty))
        qty = floor_to_step(remaining, filters.step_size)
        tp, trg, lim = compute_levels(
            Decimal(str(reference_price)), Decimal(str(tp_pct)), Decimal(str(sl_pct)),
            filters.tick_size, gap_ticks=self._gap_ticks,
        )
        return RepositionDraft(
            symbol=source.symbol, quantity=qty, tp_price=tp, stop_trigger=trg,
            stop_limit=lim, reference_price=Decimal(str(reference_price)),
            tp_pct=Decimal(str(tp_pct)), sl_pct=Decimal(str(sl_pct)),
            filters=filters, gap_ticks=self._gap_ticks, side="SELL",
        )

    def _cancel_source(self, source: OpenSellOrder):
        if source.is_oco and source.oco_group_id is not None:
            return self._client.signed_request(
                "DELETE", PATH_ORDERLIST,
                [("symbol", source.symbol), ("orderListId", int(source.oco_group_id))],
            )
        return self._client.cancel_order(source.symbol, orderId=int(source.orderId))

    def convert(self, source: OpenSellOrder, tp_pct, sl_pct, reference_price,
                dry_run: bool = False) -> ExecutionResult:
        steps = []
        def step(key, label, status="pending", detail="", naked=False):
            s = ExecutionStep(key=key, label=label, status=status,
                              detail=detail, naked_window=naked)
            steps.append(s); return s

        step("verify", "التحقّق من الأمر المصدر", "done", f"{source.badge} · {source.symbol}")
        draft = self.build_draft(source, tp_pct, sl_pct, reference_price)
        step("price", "حساب TP/SL من السعر الحي", "done",
             f"TP={fmt(draft.tp_price)} TRG={fmt(draft.stop_trigger)} LIM={fmt(draft.stop_limit)}")
        step("recalc", "إعادة الحساب", "done")

        gate = validate_pre_cancel(draft, draft.reference_price, draft.filters,
                                   available_qty=draft.quantity)
        step("gate", "بوّابة التحقّق قبل الإلغاء", "done" if gate.ok else "failed")
        if not gate.ok:
            reason = "PARTIAL_FILL_ABORT" if gate.partial_fill_abort else "GATE_FAILED"
            return ExecutionResult(state=ExecutionState.ABORTED, steps=steps, draft=draft,
                                   reason=reason, gate=gate, messages=list(gate.failures))
        if dry_run:
            return ExecutionResult(state=ExecutionState.GATE_PASSED, steps=steps,
                                   draft=draft, gate=gate)

        cancelled_id = source.oco_group_id if source.is_oco else source.orderId
        cstep = step("cancel", "إلغاء الأمر المصدر", naked=True,
                     detail=f"{'OCO' if source.is_oco else 'order'} {cancelled_id}")
        try:
            self._cancel_source(source)
            cstep.status = "done"
        except Exception as exc:  # لم يُنشأ شيء بعد ⇒ آمن
            cstep.status = "failed"; cstep.detail = str(exc)
            return ExecutionResult(state=ExecutionState.ABORTED, steps=steps, draft=draft,
                                   reason="CANCEL_FAILED", gate=gate, messages=[str(exc)])

        list_id = self._id_factory("ocl")
        create_params = [
            ("symbol", draft.symbol), ("side", "SELL"), ("quantity", fmt(draft.quantity)),
            ("aboveType", "LIMIT_MAKER"), ("abovePrice", fmt(draft.tp_price)),
            ("belowType", "STOP_LOSS_LIMIT"), ("belowStopPrice", fmt(draft.stop_trigger)),
            ("belowPrice", fmt(draft.stop_limit)), ("belowTimeInForce", "GTC"),
            ("aboveClientOrderId", self._id_factory("oca")),
            ("belowClientOrderId", self._id_factory("ocb")),
            ("listClientOrderId", list_id),
        ]
        crstep = step("create", "إنشاء OCO الجديد", naked=True)
        result = ExecutionResult(
            state=ExecutionState.REPOSITIONING, steps=steps, draft=draft, gate=gate,
            cancelled_order_list_id=(int(cancelled_id) if source.is_oco and cancelled_id is not None else None),
        )
        try:
            resp = self._client.signed_request("POST", PATH_CREATE_OCO, create_params)
            crstep.status = "done"
            result.new_order_list_id = resp.get("orderListId")
        except Exception as exc:
            # D9 لا إعادة إنشاء أعمى + D10 إعادة فحص واحدة فقط
            new_id = None
            try:
                rc = self._client.signed_request("GET", PATH_ORDERLIST,
                                                 [("listClientOrderId", list_id)])
                if isinstance(rc, dict):
                    new_id = rc.get("orderListId")
            except Exception:
                new_id = None
            if new_id and int(new_id) > 0:
                crstep.status = "done"; result.new_order_list_id = new_id
                step("confirm", "تأكيد", "done", f"OCO {new_id}")
                result.state = ExecutionState.SUCCESS
                return result
            crstep.status = "failed"; crstep.detail = str(exc)
            result.state = ExecutionState.FAILED_NEEDS_ATTENTION
            result.reason = "CREATE_FAILED_AFTER_CANCEL"
            result.messages.append(str(exc))
            return result

        step("confirm", "تأكيد", "done", f"OCO {result.new_order_list_id}")
        result.state = ExecutionState.SUCCESS
        return result
