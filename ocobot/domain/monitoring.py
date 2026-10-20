"""Dynamic Monitoring engine (M3 / T4) — in-memory only.

يستهلك ticks الأسعار فقط (لا يعرف شيئًا عن النقل: WS/REST). يفوّض كل تنفيذ
حقيقي (cancel+create) إلى ``SafeExecutor.execute(...)`` القائم — لا يعيد بناء
البوابة/idempotency/naked-window (D9/D10/D16/D17/D19 تبقى في SafeExecutor).

مبادئ محورية:
  - D14: السعر المرجعي = السعر الحيّ الحقيقي المُمرَّر عند Start (المحرّك لا يختلق سعرًا).
  - Trigger Latching: بعد تجاوز مستوى التفعيل يبقى latched=True (لا يُلغى بسحب صغير).
  - Latest Price Principle: التنفيذ يستخدم أحدث سعر صالح لا سعر لحظة التفعيل.
  - One-Replacement-In-Flight: لا دورة جديدة قبل انتهاء الحالية (نحتفظ بأحدث سعر).
  - Rollover: بعد نجاح الإنشاء تنتقل المراقبة إلى orderListId الجديد.
  - Pause/Resume: لا يمسّان أي أمر حقيقي (P2/P3).
  - Kill Switch: يوقف المراقبة فقط دون إلغاء أي أمر على Binance.

خارج النطاق (T5): persistence / recovery / audit log / demo mode. الحالة كلها في الذاكرة.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING, Optional

from ocobot.domain.models import fmt
from ocobot.domain.reposition import ExecutionResult, ExecutionState
from ocobot.domain.dynamic_exit import DynamicExitConfig, shadow_divergence


def _now_iso() -> str:
    """طابع زمني UTC بصيغة ISO-8601 (يطابق core.audit_log._now_iso)."""
    return datetime.now(timezone.utc).isoformat()

if TYPE_CHECKING:  # hint only — audit sink is duck-typed at runtime
    from ..core.audit_log import AuditLog


class MonitoringStateEnum(str, Enum):
    DISCONNECTED = "DISCONNECTED"
    CONNECTED = "CONNECTED"
    SELECTED = "SELECTED"
    MONITORING_ACTIVE = "MONITORING_ACTIVE"
    TRIGGERED = "TRIGGERED"
    REPOSITIONING = "REPOSITIONING"
    SUCCESS = "SUCCESS"
    PAUSED = "PAUSED"
    MONITORING_STOPPED = "MONITORING_STOPPED"
    CLOSED = "CLOSED"
    ABORTED = "ABORTED"
    FAILED_NEEDS_ATTENTION = "FAILED_NEEDS_ATTENTION"


class GuardPolicy(str, Enum):
    EXECUTE_LATEST = "EXECUTE_LATEST"
    HALT_NOTIFY = "HALT_NOTIFY"


class EndReason(str, Enum):
    """سبب انتهاء جلسة المراقبة (يُحمل في حدث التدقيق monitor_closed فقط)."""
    COMPLETED_TP = "completed_tp"
    COMPLETED_SL = "completed_sl"
    STOPPED_MANUAL = "stopped_manual"
    STOPPED_DISCONNECT = "stopped_disconnect"
    STOPPED_OTHER = "stopped_other"


# رسالة Kill Switch البشرية (يجب أن تطابق نص التصميم حرفيًا)
MSG_KILL_SWITCH = "تم إيقاف كل المراقبة النشطة فورًا. لم يُلغَ أي أمر على Binance."


def _dec(value) -> Optional[Decimal]:
    if value is None:
        return None
    return value if isinstance(value, Decimal) else Decimal(str(value))


@dataclass
class MonitoringState:
    enabled: bool = False
    state: MonitoringStateEnum = MonitoringStateEnum.DISCONNECTED
    symbol: str = ""
    reference_price: Optional[Decimal] = None
    trigger_pct: Optional[Decimal] = None
    tp_pct: Optional[Decimal] = None
    sl_pct: Optional[Decimal] = None
    latched: bool = False
    in_flight: bool = False
    target_order_list_id: Optional[int] = None
    tolerance_pct: Optional[Decimal] = None
    guard_pct: Optional[Decimal] = None
    last_price: Optional[Decimal] = None
    last_reposition: Optional[dict] = None
    cursor: int = 0  # عدد عمليات إعادة التموضع المكتملة
    trade_uid: str = ""  # معرّف الصفقة (ثابت عبر جلسات نفس الصفقة)
    session_no: int = 0  # رقم الجلسة ضمن الصفقة (يبدأ من 1)

    def to_dict(self) -> dict:
        """تمثيل JSON-safe (أرقام كنصوص عبر fmt). لا أسرار."""
        return {
            "enabled": self.enabled,
            "state": self.state.value,
            "symbol": self.symbol,
            "referencePrice": fmt(self.reference_price),
            "triggerPct": fmt(self.trigger_pct),
            "tpPct": fmt(self.tp_pct),
            "slPct": fmt(self.sl_pct),
            "latched": self.latched,
            "inFlight": self.in_flight,
            "targetOrderListId": self.target_order_list_id,
            "tolerancePct": fmt(self.tolerance_pct),
            "guardPct": fmt(self.guard_pct),
            "lastPrice": fmt(self.last_price),
            "lastReposition": self.last_reposition,
            "cursor": self.cursor,
            "tradeUid": self.trade_uid,
            "sessionNo": self.session_no,
        }


@dataclass
class MonitorTick:
    """نتيجة معالجة tick سعري واحد."""
    event: str  # IDLE/LATCHED/REPOSITIONED/GUARD_HALT/CLOSED/IN_FLIGHT_SKIPPED/PAUSED/ABORTED/FAILED_NEEDS_ATTENTION
    state: MonitoringStateEnum
    price: Optional[Decimal] = None
    execution_result: Optional[ExecutionResult] = None
    message: str = ""


_HUNDRED = Decimal("100")

# الحالات التي لا تتّخذ فيها الـ ticks أي إجراء
_INACTIVE_STATES = {
    MonitoringStateEnum.PAUSED,
    MonitoringStateEnum.MONITORING_STOPPED,
    MonitoringStateEnum.CLOSED,
    MonitoringStateEnum.FAILED_NEEDS_ATTENTION,
}

# أسباب Abort الدالّة على أن الأمر لم يعد موجودًا / أُغلق خارجيًا
_CLOSED_REASON_HINTS = (
    "order no longer exists",
    "no longer exists",
    "does not exist",
    "not found",
    "already closed",
    "closed externally",
    "غير موجود",
    "لم يُعثر",
    "لم يعد موجودًا",
)


class MonitoringEngine:
    """محرّك المراقبة الديناميكية — يفوّض التنفيذ إلى SafeExecutor فقط."""

    def __init__(self, executor, *, guard_policy: GuardPolicy = GuardPolicy.HALT_NOTIFY,
                 dry_run: bool = False, audit: Optional["AuditLog"] = None,
                 checkpoint_sink=None, dynamic_exit: Optional[DynamicExitConfig] = None,
                 live_atr_pct_provider=None, shadow: bool = False):
        self._executor = executor
        self.guard_policy = GuardPolicy(guard_policy)
        self.dry_run = bool(dry_run)
        self.state = MonitoringState()
        self._selected_oco = None  # مرجع الـ OCO المختار (يُضبط في start/resume)
        self._audit = audit
        self._checkpoint_sink = checkpoint_sink
        self._dynamic_exit = dynamic_exit
        self._live_atr_pct_provider = live_atr_pct_provider
        self._shadow = bool(shadow)
        self._peak = None

    def _record(self, event, details):
        # التدقيق اختياري ولا يجب أن يكسر المراقبة أبدًا (backward-compatible).
        if self._audit is not None:
            try:
                self._audit.record(event, details)
            except Exception:
                pass   # auditing must never break monitoring

    def _record_dynamic_exit_atr(self, atr_value):
        """observability (G1.65 #4/#5): يسجّل ATR٪ الحيّ + لقطة عدّادات المزوّد.
        تسجيل بحت عبر ``_record`` (audit) — لا يكسر المراقبة ولا يُغيّر أي سلوك."""
        try:
            details = {"atr_pct": float(atr_value),
                       "fail_safe": float(atr_value) == 0.0}
            stats = getattr(self._live_atr_pct_provider, "stats", None)
            if isinstance(stats, dict):
                details["provider_stats"] = {
                    "calls": stats.get("calls"),
                    "ok": stats.get("ok"),
                    "failsafe": stats.get("failsafe"),
                    "last_reason": stats.get("last_reason"),
                }
            self._record("dynamic_exit_atr", details)
        except Exception:
            pass   # observability must never break monitoring

    def _record_dynamic_exit_shadow(self, reference, st):
        """شادو-مود (G1.65 #5): يحسب ماذا كان الخروج التكيّف سيفعل ويسجّله فقط
        — **دون أي تنفيذ** (صفر تغيير سلوك). محصّن: لا يكسر المراقبة أبدًا."""
        try:
            _atr = (float(self._live_atr_pct_provider())
                    if callable(self._live_atr_pct_provider) else 0.0)
            self._record_dynamic_exit_atr(_atr)
            _peak = self._peak if self._peak is not None else reference
            _prev_stop = st.reference_price * (Decimal("1") - st.sl_pct / _HUNDRED)
            rec = shadow_divergence(reference, _peak, _prev_stop, _atr, st.sl_pct,
                                    self._dynamic_exit.params())
            self._record("dynamic_exit_shadow", rec)
        except Exception:
            pass   # shadow must never break monitoring

    def note_exit_source(self, source: str) -> None:
        """G1.46: يُسجّل علامة نسبة الخروج (exit_source) قبل الإغلاق — إضافة بحتة.

        علامة إضافية append-only تدلّ على «الوسيلة» التي تسبّبت في الخروج
        (PRICE_BRACKET/BTC_FOLLOW/POSITION_SAFETY_NET؛ MONITORING هو الافتراضي
        بلا علامة). تستعمل ``self._record`` القائم (آمن ولا يكسر المراقبة ولا
        يكتب شيئًا بلا سجل تدقيق). لا تُغيّر أي سلوك/حالة في المحرّك، ولا تمسّ
        أحداث monitor_start/monitor_closed القائمة. القيم غير المعروفة تُتجاهَل.
        """
        if source in ("MONITORING", "PRICE_BRACKET", "BTC_FOLLOW", "POSITION_SAFETY_NET"):
            self._record("exit_source", {"source": source})

    def _persist(self):
        # حفظ الـcheckpoint اختياري ولا يجب أن يكسر المراقبة أبدًا (نمط _record — T6).
        if self._checkpoint_sink is None:
            return
        try:
            self._checkpoint_sink(self.state)   # يمرّر MonitoringState الحالية
        except Exception:
            pass   # persistence must never break monitoring

    # ---- lifecycle ----
    @property
    def selected_oco(self):
        """مرجع الـ OCO المختار الذي يُستأنف/يُبدأ به (للاطلاع/الاختبار)."""
        return self._selected_oco

    def start(self, selected_oco, trigger_pct, tp_pct, sl_pct, reference_price,
              tolerance_pct=Decimal("0.1"), guard_pct=Decimal("1.0"),
              prior_trade_uid: str | None = None, prior_session_no: int = 0) -> MonitoringState:
        """يبدأ المراقبة على السعر المرجعي الحيّ الحقيقي المُمرَّر (D14).

        معرّف ثنائي المستوى: إن مُرِّر ``prior_trade_uid`` (جلسة جديدة لنفس الصفقة)
        نعيد استخدامه ونزيد ``session_no``؛ وإلا نُولّد trade_uid جديدًا ونبدأ من session_no=1.
        """
        self._selected_oco = selected_oco
        st = self.state
        st.symbol = getattr(selected_oco, "symbol", "")
        st.target_order_list_id = getattr(selected_oco, "order_list_id", None)
        st.trigger_pct = _dec(trigger_pct)
        st.tp_pct = _dec(tp_pct)
        st.sl_pct = _dec(sl_pct)
        st.reference_price = _dec(reference_price)  # D14: سعر حيّ حقيقي، لا اختلاق
        st.tolerance_pct = _dec(tolerance_pct)
        st.guard_pct = _dec(guard_pct)
        st.latched = False
        st.in_flight = False
        st.cursor = 0
        st.last_price = None
        st.last_reposition = None
        # المعرّف ثنائي المستوى (trade_uid ثابت عبر الجلسات، session_no يتصاعد)
        if prior_trade_uid:
            st.trade_uid = prior_trade_uid          # جلسة جديدة لنفس الصفقة
            st.session_no = prior_session_no + 1
        else:
            st.trade_uid = uuid.uuid4().hex[:8]     # صفقة جديدة
            st.session_no = 1
        st.enabled = True
        st.state = MonitoringStateEnum.MONITORING_ACTIVE
        start_order_snapshot = st.target_order_list_id  # لقطة orderListId عند بدء الجلسة (مرجع فقط)
        self._record("monitor_start", {
            "order_list_id": st.target_order_list_id,
            "symbol": st.symbol,
            "trigger_pct": st.trigger_pct,
            "tp_pct": st.tp_pct,
            "sl_pct": st.sl_pct,
            "reference_price": st.reference_price,
            "tolerance_pct": st.tolerance_pct,
            "guard_pct": st.guard_pct,
            "dry_run": self.dry_run,
            "trade_uid": st.trade_uid,
            "session_no": st.session_no,
            "start_ts": _now_iso(),
            "start_order_snapshot": start_order_snapshot,
        })
        self._persist()
        return st

    def resume_from_state(self, selected_oco, state) -> MonitoringState:
        """يستأنف المراقبة من حالة محفوظة (T8) دون إعادة تهيئة الحقول.

        يعكس ما يخزّنه ``start()`` من مرجع للـ selected_oco، لكن ناقص إعادة
        تهيئة حقول الحالة (نحتفظ بـ ``state`` المحفوظة كما هي). لا كتابة عمياء:
        يُستدعى فقط بعد نجاح مطابقة REST داخل ``recover()``.
        """
        self._selected_oco = selected_oco
        self.state = state
        self.state.enabled = True
        self._record("monitor_resume", {
            "order_list_id": state.target_order_list_id,
            "symbol": state.symbol,
            "state": getattr(state.state, "value", state.state),
            "cursor": state.cursor,
        })
        self._persist()
        return self.state

    def activation_level(self) -> Decimal:
        """مستوى التفعيل = reference * (1 + trigger%/100)."""
        return self.state.reference_price * (Decimal("1") + self.state.trigger_pct / _HUNDRED)

    # ---- price stream ----
    def on_price_tick(self, price) -> MonitorTick:
        _prev_state = self.state.state
        try:
            st = self.state
            price = _dec(price)

            # (0) معطّل أو حالة خاملة ⇒ سجّل السعر ولا تتّخذ إجراء
            if not st.enabled or st.state in _INACTIVE_STATES:
                st.last_price = price
                if st.state == MonitoringStateEnum.PAUSED:
                    return MonitorTick("PAUSED", st.state, price,
                                       message="المراقبة موقوفة مؤقتًا — لا إجراء.")
                return MonitorTick("IDLE", st.state, price,
                                   message="لا مراقبة نشطة — لا إجراء.")

            # (1) دورة قيد التنفيذ ⇒ احتفظ بأحدث سعر للدورة التالية (One-Replacement-In-Flight)
            if st.in_flight:
                st.last_price = price
                return MonitorTick("IN_FLIGHT_SKIPPED", st.state, price,
                                   message="دورة إعادة تموضع قيد التنفيذ — احتفظنا بأحدث سعر.")

            st.last_price = price
            if self._dynamic_exit is not None and (self._dynamic_exit.enabled or self._shadow):
                self._peak = price if self._peak is None else max(self._peak, price)

            # (2) Trigger Latching: عبور مستوى التفعيل يُثبّت latched (لا يُلغى بسحب صغير)
            if (st.state == MonitoringStateEnum.MONITORING_ACTIVE and not st.latched
                    and price >= self.activation_level()):
                st.latched = True
                st.state = MonitoringStateEnum.TRIGGERED

            # (3) latched وغير قيد تنفيذ ⇒ قيّم التنفيذ
            if st.latched and not st.in_flight:
                last = price  # Latest Price Principle: أحدث سعر صالح، لا سعر لحظة التفعيل
                activation = self.activation_level()

                # حارس الحركة المعاكسة: هبوط تحت مستوى التفعيل بأكثر من guard_pct
                guard_floor = activation * (Decimal("1") - st.guard_pct / _HUNDRED)
                if price < guard_floor:
                    if self.guard_policy == GuardPolicy.HALT_NOTIFY:
                        msg = (
                            f"حركة معاكسة تجاوزت الحارس (guard={fmt(st.guard_pct)}%): "
                            f"السعر {fmt(price)} تحت الحد {fmt(guard_floor)} — "
                            "أُوقفت إعادة التموضع، وأمر OCO سليم كما هو (لا إلغاء)."
                        )
                        self._record("guard_halt", {
                            "price": price,
                            "guard_pct": st.guard_pct,
                        })
                        return MonitorTick("GUARD_HALT", st.state, price, message=msg)
                    # EXECUTE_LATEST ⇒ نُكمل التنفيذ من أحدث سعر

                # ابدأ دورة واحدة
                st.in_flight = True
                st.state = MonitoringStateEnum.REPOSITIONING
                if self._dynamic_exit is not None and self._dynamic_exit.enabled:
                    _atr = (float(self._live_atr_pct_provider())
                            if callable(self._live_atr_pct_provider) else 0.0)
                    self._record_dynamic_exit_atr(_atr)
                    _peak = self._peak if self._peak is not None else last
                    _prev_stop = st.reference_price * (Decimal("1") - st.sl_pct / _HUNDRED)
                    result = self._executor.execute(
                        order_list_id=st.target_order_list_id,
                        tp_pct=st.tp_pct,
                        sl_pct=st.sl_pct,
                        reference_price=last,
                        dry_run=self.dry_run,
                        dynamic_exit=self._dynamic_exit,
                        peak_price=_peak,
                        prev_stop=_prev_stop,
                        live_atr_pct_value=_atr,
                    )
                else:
                    # شادو-مود (opt-in، increment #5): احسب ماذا كان الخروج التكيّف
                    # سيفعل وسجّله فقط — **دون تنفيذه**. نداء execute أدناه يبقى المسار
                    # الحالي حرفيًّا ⇒ صفر تغيير سلوك.
                    if self._shadow and self._dynamic_exit is not None:
                        self._record_dynamic_exit_shadow(last, st)
                    result = self._executor.execute(
                        order_list_id=st.target_order_list_id,
                        tp_pct=st.tp_pct,
                        sl_pct=st.sl_pct,
                        reference_price=last,
                        dry_run=self.dry_run,
                    )
                return self._interpret(result, last)

            # (4) لا شيء ليُنفَّذ الآن
            return MonitorTick("IDLE", st.state, price, message="بانتظار تجاوز مستوى التفعيل.")
        finally:
            if self.state.state != _prev_state:
                self._persist()

    def _derive_end_reason(self, reason: Optional[str], last: Optional[Decimal]) -> EndReason:
        """يستنتج سبب الإغلاق من نص السبب أو من السعر مقابل مستويات TP/SL.

        يُفضَّل الاستنتاج النصّي الصريح (tp/sl/take-profit/stop-loss)؛ وإلا يُقارَن
        السعر الأخير بمستويي TP/SL المشتقّين من المرجع والنِّسب؛ وإلا stopped_other.
        """
        text = (reason or "").lower()
        if "take" in text and "profit" in text or "take_profit" in text or "take-profit" in text \
                or "\u062c\u0646\u064a" in text:  # "جني" (الأرباح)
            return EndReason.COMPLETED_TP
        if "stop" in text and "loss" in text or "stop_loss" in text or "stop-loss" in text \
                or "\u0648\u0642\u0641" in text:  # "وقف" (الخسارة)
            return EndReason.COMPLETED_SL
        if "tp" in text:
            return EndReason.COMPLETED_TP
        if "sl" in text:
            return EndReason.COMPLETED_SL
        # اشتقاق من السعر مقابل المستويات (reference ± نِسب)
        st = self.state
        ref = st.reference_price
        if last is not None and ref is not None:
            try:
                if st.tp_pct is not None:
                    tp_level = ref * (Decimal("1") + st.tp_pct / _HUNDRED)
                    if last >= tp_level:
                        return EndReason.COMPLETED_TP
                if st.sl_pct is not None:
                    sl_level = ref * (Decimal("1") - st.sl_pct / _HUNDRED)
                    if last <= sl_level:
                        return EndReason.COMPLETED_SL
            except Exception:
                pass  # اشتقاق أفضل-جهد فقط؛ لا يكسر الإغلاق أبدًا
        return EndReason.STOPPED_OTHER

    def _interpret(self, result: ExecutionResult, last: Decimal) -> MonitorTick:
        st = self.state
        state = result.state

        if state == ExecutionState.SUCCESS:
            # Rollover: انتقل إلى orderListId الجديد، والسعر الأخير يصبح المرجع الجديد
            if result.new_order_list_id is not None:
                st.target_order_list_id = result.new_order_list_id
            st.reference_price = last
            st.latched = False
            st.in_flight = False
            st.cursor += 1
            st.state = MonitoringStateEnum.MONITORING_ACTIVE
            summary = {
                "cancelledOrderListId": result.cancelled_order_list_id,
                "newOrderListId": result.new_order_list_id,
                "referencePrice": fmt(last),
                "cursor": st.cursor,
            }
            st.last_reposition = summary
            self._record("repositioned", {
                "old_target": result.cancelled_order_list_id,
                "new_target": result.new_order_list_id,
                "cursor": st.cursor,
                "price": last,
            })
            return MonitorTick("REPOSITIONED", st.state, last, execution_result=result,
                               message=f"أُعيد التموضع إلى OCO {result.new_order_list_id}.")

        if state == ExecutionState.ABORTED:
            reason = (result.reason or "").lower()
            if any(hint in reason for hint in _CLOSED_REASON_HINTS):
                # الأمر لم يعد موجودًا / أُغلق خارجيًا ⇒ إيقاف وإخطار (لا إعادة)
                st.in_flight = False
                st.enabled = False
                st.state = MonitoringStateEnum.CLOSED
                end_reason = self._derive_end_reason(result.reason, last)
                self._record("monitor_closed", {
                    "reason": result.reason,
                    "end_reason": end_reason.value,
                    "end_ts": _now_iso(),
                    "trade_uid": st.trade_uid,
                    "session_no": st.session_no,
                })
                return MonitorTick("CLOSED", st.state, last, execution_result=result,
                                   message="الأمر لم يعد موجودًا (أُغلق خارجيًا) — أُوقفت المراقبة.")
            # Abort غير مُدمِّر (بوابة/تنفيذ جزئي) ⇒ الأمر الحقيقي سليم؛ أبقِ latched
            st.in_flight = False
            st.state = MonitoringStateEnum.MONITORING_ACTIVE
            # latched يبقى True كما هو
            self._record("monitor_aborted", {
                "reason": result.reason,
                "price": last,
                "end_reason": self._derive_end_reason(result.reason, last).value,
            })
            return MonitorTick("ABORTED", st.state, last, execution_result=result,
                               message=result.reason or "أُلغي الإجراء — الأمر الأصلي سليم.")

        if state == ExecutionState.FAILED_NEEDS_ATTENTION:
            # No Blind Retry (D9): يتوقّف بانتظار تدخّل بشري
            st.in_flight = False
            st.enabled = False
            st.state = MonitoringStateEnum.FAILED_NEEDS_ATTENTION
            self._record("monitor_failed", {"reason": result.reason})
            return MonitorTick("FAILED_NEEDS_ATTENTION", st.state, last,
                               execution_result=result,
                               message=result.reason or "فشل يحتاج تدخّلًا يدويًا — لا إعادة محاولة.")

        # حالات أخرى (نادرة، مثل GATE_PASSED في dry_run) ⇒ عاملها كـ Abort غير مُدمِّر
        st.in_flight = False
        st.state = MonitoringStateEnum.MONITORING_ACTIVE
        return MonitorTick("ABORTED", st.state, last, execution_result=result,
                           message=result.reason or f"نتيجة غير متوقّعة: {state.value}")

    # ---- controls ----
    def pause(self) -> MonitorTick:
        """يوقف الحركة الديناميكية دون مسّ الأمر الحقيقي (P2/P3)."""
        st = self.state
        if st.state in (MonitoringStateEnum.MONITORING_ACTIVE, MonitoringStateEnum.TRIGGERED):
            st.state = MonitoringStateEnum.PAUSED
        self._record("pause", {"state": st.state.value})
        self._persist()
        return MonitorTick("PAUSED", st.state, st.last_price,
                           message="أُوقفت المراقبة مؤقتًا — أمر OCO سليم كما هو.")

    def resume(self) -> MonitorTick:
        """يستأنف من نفس المرجع/latched/cursor/target."""
        st = self.state
        if st.state == MonitoringStateEnum.PAUSED:
            st.state = MonitoringStateEnum.MONITORING_ACTIVE
        self._record("resume", {"state": st.state.value})
        self._persist()
        return MonitorTick("IDLE", st.state, st.last_price,
                           message="استُؤنفت المراقبة من نفس النقطة.")

    def kill_switch(self) -> MonitorTick:
        """يوقف كل المراقبة فورًا دون إلغاء أي أمر على Binance."""
        st = self.state
        st.state = MonitoringStateEnum.MONITORING_STOPPED
        st.enabled = False
        self._record("kill_switch", {"state": st.state.value})
        self._record("monitor_closed", {
            "end_reason": EndReason.STOPPED_MANUAL.value,
            "end_ts": _now_iso(),
            "trade_uid": st.trade_uid,
            "session_no": st.session_no,
        })
        self._persist()
        return MonitorTick("PAUSED", st.state, st.last_price, message=MSG_KILL_SWITCH)

    def notify_external_close(self, reason: str = "") -> MonitorTick:
        """إغلاق OCO خارجيًا (عبر User Data Stream · T9b) — يوقف المراقبة بلا SafeExecutor.

        لا cancel/create/إعادة تموضع؛ ينقل الحالة إلى ``CLOSED`` النهائية ويُعطّل
        المراقبة، مرآةً لمسار الإغلاق الحالي في ``_interpret`` (audit=monitor_closed).
        loose-coupled عبر ``UserDataStreamConsumer.on_external_close``.
        """
        st = self.state
        st.in_flight = False
        st.enabled = False
        st.state = MonitoringStateEnum.CLOSED
        end_reason = self._derive_end_reason(reason, st.last_price)
        self._record("monitor_closed", {
            "reason": reason,
            "source": "user_data_stream",
            "end_reason": end_reason.value,
            "end_ts": _now_iso(),
            "trade_uid": st.trade_uid,
            "session_no": st.session_no,
        })
        self._persist()
        return MonitorTick("CLOSED", st.state, st.last_price,
                           message="أُغلق الأمر خارجيًا (User Data Stream) — أُوقفت المراقبة.")

    def notify_disconnect(self) -> MonitorTick:
        """يُنهي جلسة المراقبة بسبب انقطاع الاتصال (توصيله من connection.py لاحقًا).

        لا يمسّ أي أمر حقيقي على Binance؛ ينقل الحالة إلى ``MONITORING_STOPPED``
        ويُعطّل المراقبة، ويصدر monitor_closed بسبب stopped_disconnect.
        """
        st = self.state
        st.in_flight = False
        st.enabled = False
        st.state = MonitoringStateEnum.MONITORING_STOPPED
        self._record("monitor_closed", {
            "end_reason": EndReason.STOPPED_DISCONNECT.value,
            "end_ts": _now_iso(),
            "trade_uid": st.trade_uid,
            "session_no": st.session_no,
        })
        self._persist()
        return MonitorTick("CLOSED", st.state, st.last_price,
                           message="انقطع الاتصال — أُوقفت المراقبة (لا إلغاء لأي أمر على Binance).")
