"""محوّل حالة الحارس للواجهة (Guardian Status Adapter) — G1.31 / chunk_3.

محوّل **خالص بايثون** (بلا Qt، بلا شبكة، بلا I/O) يربط بين وضع الواجهة
(Off/Observe/Live) و ``GuardianSupervisor`` ومخزن الحالة ``GuardianStatusStore``.
قابل للاختبار بلا ``QApplication``.

مبدأ الأمان الحاكم:
  - الوضع ``OFF`` (أو غياب المُشرِف) ⇒ **لا يُستدعى** ``supervisor.tick()`` إطلاقًا،
    فلا يحدث أي تدخّل عندما يختار المستخدم الإطفاء. تُدفع حالة ``DISABLED`` فقط.
  - ``OBSERVE`` ⇒ ``supervisor.dry_run = True`` (رصد بلا وضع أمر).
  - ``LIVE``    ⇒ ``supervisor.dry_run = False`` (تدخّل فعلي).

لا يمسّ المسار الحار ولا يعدّل داخليّات المُشرِف؛ يقرأ فقط سطحه العامّ
(``dry_run``، ``_armed``، ``last_decision``، ``last_result``، ``tick()``).

يحترم حارس ``tests/test_ui_no_direct_network`` (لا أيّ نداء شبكي في طبقة الواجهة).
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from ocobot.domain.guardian import GuardianAction, GuardianDecision
from ocobot.domain.guardian_status import (
    GuardianMode,
    GuardianStatus,
    GuardianUiState,
    LastAction,
)


def derive_ui_state(mode, decision, armed) -> GuardianUiState:
    """دالة خالصة: تشتقّ حالة العرض من (الوضع، القرار، هل سُلّح الحارس).

    الخريطة (بالترتيب الصارم):
      - الوضع ``OFF``                       ⇒ ``DISABLED``.
      - ``decision is None``                ⇒ ``SLEEPING`` (المراقبة غير نشطة).
      - ``armed`` أو ``INTERVENE``          ⇒ ``INTERVENED``.
      - ``WAIT``                            ⇒ ``WATCHING`` (رصد عُري).
      - ``NOOP``                            ⇒ ``SLEEPING``.
    """
    if mode is GuardianMode.OFF:
        return GuardianUiState.DISABLED
    if decision is None:
        return GuardianUiState.SLEEPING
    action = getattr(decision, "action", None)
    if armed or action is GuardianAction.INTERVENE:
        return GuardianUiState.INTERVENED
    if action is GuardianAction.WAIT:
        return GuardianUiState.WATCHING
    # NOOP (أو أيّ قيمة أخرى غير متوقّعة) ⇒ نائم.
    return GuardianUiState.SLEEPING


class GuardianStatusAdapter:
    """يربط وضع الواجهة بالمُشرِف ويدفع لقطات الحالة إلى المخزن.

    التبعيات (كلّها محقونة):
      - ``supervisor``: ``GuardianSupervisor`` أو ``None`` (البيئة غير مضبوطة).
      - ``store``: ``GuardianStatusStore`` تُدفع إليه اللقطات.
      - ``mode_getter``: ``Callable`` يُعيد ``GuardianMode`` المختار من الواجهة.
      - ``time_fn``: ``Callable`` يُعيد نصّ الطابع الزمني لـ``LastAction``
        (الافتراضي دالة تُعيد نصًّا فارغًا — بلا حساب وقت).

    دفاعيّ بالكامل: لا يرمي أبدًا (أي خطأ ⇒ وضع آمن ``OFF``/``DISABLED``).
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
        # ``clock`` اسمٌ بديل مقبول لـ``time_fn`` (توافقًا)؛ الافتراضي نصّ فارغ.
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

    def _push(self, status: GuardianStatus) -> None:
        """يدفع لقطة إلى المخزن بأمان (لا يرمي)."""
        store = self._store
        if store is None:
            return
        try:
            store.set(status)
        except Exception:
            pass

    def tick(self) -> Optional[GuardianDecision]:
        """دورة إشراف واحدة محكومة بوضع الواجهة. تُعيد القرار (أو ``None``).

        في وضع ``OFF`` أو عند غياب المُشرِف: تُدفع ``DISABLED`` ولا يُستدعى
        ``supervisor.tick()`` إطلاقًا (منع التدخّل عند الإطفاء).
        """
        mode = self._read_mode()

        # الإطفاء أو غياب المُشرِف ⇒ لا تدخّل، حالة DISABLED فقط.
        if mode is GuardianMode.OFF or self._supervisor is None:
            self._push(GuardianStatus(mode=GuardianMode.OFF, state=GuardianUiState.DISABLED))
            return None

        supervisor = self._supervisor
        # Observe ⇒ dry_run=True؛ Live ⇒ dry_run=False.
        try:
            supervisor.dry_run = (mode is not GuardianMode.LIVE)
        except Exception:
            pass

        decision = None
        try:
            decision = supervisor.tick()
        except Exception:
            decision = None

        armed = False
        try:
            armed = bool(getattr(supervisor, "_armed", False))
        except Exception:
            armed = False

        state = derive_ui_state(mode, decision, armed)

        last_action = None
        if state is GuardianUiState.INTERVENED:
            last_action = self._build_last_action(supervisor, decision)

        self._push(GuardianStatus(mode=mode, state=state, last_action=last_action))
        return decision

    def _build_last_action(self, supervisor, decision) -> Optional[LastAction]:
        """يبني ``LastAction`` من القرار + ``supervisor.last_result`` (best-effort).

        دفاعيّ بالكامل: أيّ نقص ⇒ قيم نصّية فارغة بدل الرمي.
        """
        try:
            dry_run = bool(getattr(supervisor, "dry_run", False))
            action = "observed_naked" if dry_run else "placed_protective_stop"
            reason = ""
            qty = ""
            if decision is not None:
                reason = str(getattr(decision, "reason", "") or "")
                pq = getattr(decision, "protective_qty", "")
                qty = "" if pq is None else str(pq)
            price = ""
            try:
                result = getattr(supervisor, "last_result", None) or {}
                price = str(result.get("stop_price", "") or "")
            except Exception:
                price = ""
            ts = ""
            try:
                ts = str(self._time_fn() or "")
            except Exception:
                ts = ""
            return LastAction(ts=ts, action=action, reason=reason, qty=qty, price=price)
        except Exception:
            return None
