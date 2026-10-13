# -*- coding: utf-8 -*-
"""محوّل حالة حارس هبوط BTC للواجهة (BTC-follow Status Adapter) — G1.44 / chunk_4.

محوّل **خالص بايثون** (بلا Qt، بلا شبكة، بلا I/O) يربط وضع الواجهة
(Off/Observe/Live) لحارس هبوط BTC بـ ``GuardianSupervisor`` ومخزن حالة
``GuardianStatusStore`` خاصّ بمؤشّر BTC. قابل للاختبار بلا ``QApplication``.

مبدأ حاكم (مرآة ``GuardianStatusAdapter`` مع فروق مقصودة):
  - الوضع ``OFF`` ⇒ ``supervisor.set_btc_runtime(enabled=False, dry_run=True)``
    فيصبح حارس BTC NOOP تامًّا داخل ``supervisor.tick()`` (لا خروج ولا تنبيه).
  - ``OBSERVE`` ⇒ ``enabled=True, dry_run=True`` (معاينة/تنبيه بلا تنفيذ).
  - ``LIVE``    ⇒ ``enabled=True, dry_run=False`` (تضييق فعلي عبر مسار الخروج).

**قيد التنسيق الحرج**: هذا المحوّل لا يستدعي ``supervisor.tick()`` بنفسه. فحارس
هبوط BTC وشبكة أمان المركز يتشاركان مُشرِفًا واحدًا، ويجب أن تُستدعى
``supervisor.tick()`` **مرّة واحدة** لكل دورة. لذا:
  - ``apply_runtime()``: يضبط بوّابة تشغيل BTC على المُشرِف فقط (بلا tick).
  - ``push_status(decision)``: يشتقّ ``GuardianUiState`` من آخر قرار/تسليح BTC
    ويدفع لقطة إلى المخزن.
  - ``tick()``: دورة قائمة بذاتها (لمسار اختباري مستقلّ) تضبط البوّابة ثم تستدعي
    ``supervisor.tick()`` مرّة واحدة ثم تدفع الحالة — لكنها غير مستعملة في الربط
    المدموج في ``main_window`` (التِّك يُستدعى هناك مرّة واحدة مشتركة).

دفاعيّ بالكامل: لا يرمي أبدًا (أي خطأ ⇒ وضع آمن ``OFF``/``DISABLED``).
يحترم حارس ``tests/test_ui_no_direct_network`` (لا أيّ نداء شبكي في طبقة الواجهة).
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from ocobot.domain.btc_follow import BtcFollowAction
from ocobot.domain.guardian_status import (
    GuardianMode,
    GuardianStatus,
    GuardianUiState,
    LastAction,
)


def derive_btc_ui_state(mode, btc_decision, armed) -> GuardianUiState:
    """دالة خالصة: تشتقّ حالة عرض مؤشّر BTC من (الوضع، قرار BTC، هل سُلّح).

    الخريطة (بالترتيب الصارم):
      - الوضع ``OFF``                         ⇒ ``DISABLED``.
      - ``btc_decision is None``              ⇒ ``SLEEPING`` (لا رصد بعد).
      - ``armed`` أو ``TIGHTEN``              ⇒ ``INTERVENED``.
      - ``ARM``                               ⇒ ``WATCHING`` (رصد هبوط/تأكيد).
      - خلاف ذلك (``NOOP``)                    ⇒ ``SLEEPING``.
    """
    if mode is GuardianMode.OFF:
        return GuardianUiState.DISABLED
    if btc_decision is None:
        return GuardianUiState.SLEEPING
    action = getattr(btc_decision, "action", None)
    if armed or action is BtcFollowAction.TIGHTEN:
        return GuardianUiState.INTERVENED
    if action is BtcFollowAction.ARM:
        return GuardianUiState.WATCHING
    return GuardianUiState.SLEEPING


class BtcFollowStatusAdapter:
    """يربط وضع الواجهة لحارس BTC بالمُشرِف ويدفع لقطات الحالة إلى المخزن.

    التبعيات (كلّها محقونة):
      - ``supervisor``: ``GuardianSupervisor`` أو ``None``.
      - ``store``: ``GuardianStatusStore`` تُدفع إليه لقطات مؤشّر BTC.
      - ``mode_getter``: ``Callable`` يُعيد ``GuardianMode`` المختار من الواجهة.
      - ``time_fn``/``clock``: ``Callable`` يُعيد نصّ طابع زمني لـ``LastAction``.
    """

    def __init__(
        self,
        supervisor: Any = None,
        store: Any = None,
        mode_getter: Optional[Callable[[], GuardianMode]] = None,
        time_fn: Optional[Callable[[], str]] = None,
        clock: Optional[Callable[[], str]] = None,
    ):
        self._supervisor = supervisor
        self._store = store
        self._mode_getter = mode_getter
        self._time_fn = time_fn or clock or (lambda: "")

    def _read_mode(self) -> GuardianMode:
        """يقرأ الوضع من ``mode_getter`` بأمان؛ أيّ خطأ/None ⇒ ``OFF``."""
        getter = self._mode_getter
        if getter is None:
            return GuardianMode.OFF
        try:
            mode = getter()
        except Exception:
            return GuardianMode.OFF
        return mode if mode is not None else GuardianMode.OFF

    def apply_runtime(self) -> GuardianMode:
        """يضبط بوّابة تشغيل حارس BTC على المُشرِف وفق الوضع — **بلا tick**.

        OFF ⇒ enabled=False؛ Observe ⇒ dry_run=True؛ Live ⇒ dry_run=False.
        دفاعيّ: لا يرمي أبدًا. يُعيد الوضع المقروء (للمستدعي).
        """
        mode = self._read_mode()
        sup = self._supervisor
        if sup is not None and hasattr(sup, "set_btc_runtime"):
            try:
                sup.set_btc_runtime(
                    enabled=(mode is not GuardianMode.OFF),
                    dry_run=(mode is not GuardianMode.LIVE),
                )
            except Exception:
                pass
        return mode

    def push_status(self, mode: Optional[GuardianMode] = None) -> None:
        """يشتقّ ويدفع لقطة ``GuardianStatus`` لمؤشّر BTC (بلا tick). دفاعيّ."""
        if mode is None:
            mode = self._read_mode()
        sup = self._supervisor
        if mode is GuardianMode.OFF or sup is None:
            self._push(GuardianStatus(mode=GuardianMode.OFF, state=GuardianUiState.DISABLED))
            return
        btc_decision = getattr(sup, "last_btc_decision", None)
        armed = False
        try:
            armed = bool(getattr(sup, "_btc_armed", False))
        except Exception:
            armed = False
        state = derive_btc_ui_state(mode, btc_decision, armed)
        last_action = None
        if state is GuardianUiState.INTERVENED:
            last_action = self._build_last_action(sup, btc_decision)
        self._push(GuardianStatus(mode=mode, state=state, last_action=last_action))

    def tick(self) -> Optional[Any]:
        """دورة مستقلّة قائمة بذاتها: تضبط البوّابة ⇒ ``supervisor.tick()`` مرّة ⇒ دفع.

        **لا تُستعمل** في الربط المدموج (``main_window``) حيث يُستدعى التِّك مرّة
        مشتركة؛ موجودة للمسار الاختباري المستقلّ. دفاعيّة بالكامل.
        """
        mode = self.apply_runtime()
        if mode is GuardianMode.OFF or self._supervisor is None:
            self._push(GuardianStatus(mode=GuardianMode.OFF, state=GuardianUiState.DISABLED))
            return None
        decision = None
        try:
            decision = self._supervisor.tick()
        except Exception:
            decision = None
        self.push_status(mode)
        return decision

    def _push(self, status: GuardianStatus) -> None:
        store = self._store
        if store is None:
            return
        try:
            store.set(status)
        except Exception:
            pass

    def _build_last_action(self, supervisor, btc_decision) -> Optional[LastAction]:
        """يبني ``LastAction`` من قرار BTC + ``supervisor.last_btc_result``. دفاعيّ."""
        try:
            result = getattr(supervisor, "last_btc_result", None) or {}
            placed = bool(result.get("placed", False))
            action = "btc_tighten_exit" if placed else "btc_observe"
            reason = ""
            if btc_decision is not None:
                reason = str(getattr(btc_decision, "reason", "") or "")
            drop = ""
            try:
                drop = str(result.get("drop_pct", "") or "")
                if not drop and btc_decision is not None:
                    drop = str(getattr(btc_decision, "drop_pct", "") or "")
            except Exception:
                drop = ""
            ts = ""
            try:
                ts = str(self._time_fn() or "")
            except Exception:
                ts = ""
            return LastAction(ts=ts, action=action, reason=reason, qty="", price=drop)
        except Exception:
            return None
