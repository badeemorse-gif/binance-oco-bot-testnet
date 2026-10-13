"""اختبارات محوّل حالة الحارس (G1.31 / chunk_3) — offscreen، بلا شبكة.

يغطّي منطق ``GuardianStatusAdapter`` و ``derive_ui_state`` بمُشرِف وهميّ
(FakeSupervisor) خالص — لا حاجة لـ``QApplication`` للمحوّل نفسه. يتحقّق خاصّةً
من أن وضع ``OFF`` **لا يستدعي** ``supervisor.tick()`` (منع التدخّل عند الإطفاء).
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest
from decimal import Decimal

from ocobot.domain.guardian import GuardianAction, GuardianDecision
from ocobot.domain.guardian_status import (
    GuardianMode,
    GuardianStatusStore,
    GuardianUiState,
)
from ocobot.ui.guardian_wiring import GuardianStatusAdapter, derive_ui_state


class FakeSupervisor:
    """مُشرِف وهميّ: يحاكي السطح العامّ (dry_run / _armed / last_result / tick)."""

    def __init__(self, decision=None, armed=False, last_result=None):
        self.dry_run = True
        self._armed = armed
        self.last_decision = None
        self.last_result = last_result
        self._decision = decision
        self.tick_calls = 0

    def tick(self):
        self.tick_calls += 1
        self.last_decision = self._decision
        return self._decision


def _decision(action, qty="1.5", reason="r"):
    return GuardianDecision(action=action, protective_qty=Decimal(qty), reason=reason)


class DeriveUiStateTests(unittest.TestCase):
    def test_off_is_disabled(self):
        self.assertEqual(
            derive_ui_state(GuardianMode.OFF, _decision(GuardianAction.INTERVENE), True),
            GuardianUiState.DISABLED,
        )

    def test_none_decision_is_sleeping(self):
        self.assertEqual(
            derive_ui_state(GuardianMode.OBSERVE, None, False), GuardianUiState.SLEEPING
        )

    def test_armed_is_intervened(self):
        self.assertEqual(
            derive_ui_state(GuardianMode.LIVE, _decision(GuardianAction.WAIT), True),
            GuardianUiState.INTERVENED,
        )

    def test_intervene_is_intervened(self):
        self.assertEqual(
            derive_ui_state(GuardianMode.LIVE, _decision(GuardianAction.INTERVENE), False),
            GuardianUiState.INTERVENED,
        )

    def test_wait_is_watching(self):
        self.assertEqual(
            derive_ui_state(GuardianMode.OBSERVE, _decision(GuardianAction.WAIT), False),
            GuardianUiState.WATCHING,
        )

    def test_noop_is_sleeping(self):
        self.assertEqual(
            derive_ui_state(GuardianMode.OBSERVE, _decision(GuardianAction.NOOP), False),
            GuardianUiState.SLEEPING,
        )


class GuardianStatusAdapterTests(unittest.TestCase):
    def test_off_pushes_disabled_and_does_not_tick(self):
        sup = FakeSupervisor(decision=_decision(GuardianAction.INTERVENE))
        store = GuardianStatusStore()
        adapter = GuardianStatusAdapter(
            supervisor=sup, store=store, mode_getter=lambda: GuardianMode.OFF
        )
        result = adapter.tick()
        self.assertIsNone(result)
        self.assertEqual(sup.tick_calls, 0)  # OFF يمنع نداء t() tick نهائيًّا
        self.assertEqual(store.status.state, GuardianUiState.DISABLED)
        self.assertEqual(store.status.mode, GuardianMode.OFF)

    def test_observe_sets_dry_run_true_and_ticks(self):
        sup = FakeSupervisor(decision=_decision(GuardianAction.WAIT))
        store = GuardianStatusStore()
        adapter = GuardianStatusAdapter(
            supervisor=sup, store=store, mode_getter=lambda: GuardianMode.OBSERVE
        )
        adapter.tick()
        self.assertEqual(sup.tick_calls, 1)
        self.assertTrue(sup.dry_run)  # Observe ⇒ dry_run True
        self.assertEqual(store.status.state, GuardianUiState.WATCHING)

    def test_live_sets_dry_run_false_and_ticks(self):
        sup = FakeSupervisor(decision=_decision(GuardianAction.NOOP))
        store = GuardianStatusStore()
        adapter = GuardianStatusAdapter(
            supervisor=sup, store=store, mode_getter=lambda: GuardianMode.LIVE
        )
        adapter.tick()
        self.assertEqual(sup.tick_calls, 1)
        self.assertFalse(sup.dry_run)  # Live ⇒ dry_run False
        self.assertEqual(store.status.state, GuardianUiState.SLEEPING)

    def test_intervene_captures_last_action(self):
        sup = FakeSupervisor(
            decision=_decision(GuardianAction.INTERVENE, qty="2.5", reason="naked_timeout"),
            last_result={"stop_price": "100.00"},
        )
        store = GuardianStatusStore()
        adapter = GuardianStatusAdapter(
            supervisor=sup,
            store=store,
            mode_getter=lambda: GuardianMode.LIVE,
            time_fn=lambda: "2026-10-10T00:00:00Z",
        )
        adapter.tick()
        self.assertEqual(store.status.state, GuardianUiState.INTERVENED)
        la = store.status.last_action
        self.assertIsNotNone(la)
        self.assertEqual(la.qty, "2.5")
        self.assertEqual(la.reason, "naked_timeout")
        self.assertEqual(la.price, "100.00")
        self.assertEqual(la.action, "placed_protective_stop")  # Live ⇒ not dry_run

    def test_armed_true_is_intervened(self):
        sup = FakeSupervisor(decision=_decision(GuardianAction.WAIT), armed=True)
        store = GuardianStatusStore()
        adapter = GuardianStatusAdapter(
            supervisor=sup, store=store, mode_getter=lambda: GuardianMode.LIVE
        )
        adapter.tick()
        self.assertEqual(store.status.state, GuardianUiState.INTERVENED)

    def test_observe_intervene_marks_observed_naked(self):
        sup = FakeSupervisor(
            decision=_decision(GuardianAction.INTERVENE, qty="1.0"),
        )
        store = GuardianStatusStore()
        adapter = GuardianStatusAdapter(
            supervisor=sup, store=store, mode_getter=lambda: GuardianMode.OBSERVE
        )
        adapter.tick()
        self.assertEqual(store.status.state, GuardianUiState.INTERVENED)
        self.assertEqual(store.status.last_action.action, "observed_naked")  # dry_run

    def test_decision_none_is_sleeping(self):
        sup = FakeSupervisor(decision=None)
        store = GuardianStatusStore()
        adapter = GuardianStatusAdapter(
            supervisor=sup, store=store, mode_getter=lambda: GuardianMode.OBSERVE
        )
        adapter.tick()
        self.assertEqual(sup.tick_calls, 1)
        self.assertEqual(store.status.state, GuardianUiState.SLEEPING)

    def test_none_supervisor_is_disabled_no_crash(self):
        store = GuardianStatusStore()
        adapter = GuardianStatusAdapter(
            supervisor=None, store=store, mode_getter=lambda: GuardianMode.LIVE
        )
        result = adapter.tick()
        self.assertIsNone(result)
        self.assertEqual(store.status.state, GuardianUiState.DISABLED)
        self.assertEqual(store.status.mode, GuardianMode.OFF)

    def test_mode_getter_raises_falls_back_to_off(self):
        sup = FakeSupervisor(decision=_decision(GuardianAction.INTERVENE))
        store = GuardianStatusStore()

        def _boom():
            raise RuntimeError("boom")

        adapter = GuardianStatusAdapter(supervisor=sup, store=store, mode_getter=_boom)
        adapter.tick()
        self.assertEqual(sup.tick_calls, 0)  # fallback OFF ⇒ لا tick
        self.assertEqual(store.status.state, GuardianUiState.DISABLED)


class DynamicMonitoringScreenGuardianTests(unittest.TestCase):
    """فحص خفيف أن الشاشة تكشف guardian_indicator ووضعًا افتراضيًّا OFF."""

    def test_screen_exposes_indicator_and_default_off(self):
        from ocobot.ui._qt import QApplication
        from ocobot.ui.monitoring import DynamicMonitoringScreen

        _app = QApplication.instance() or QApplication([])
        screen = DynamicMonitoringScreen()
        self.assertIsNotNone(screen.guardian_indicator)
        self.assertEqual(screen.guardian_mode(), GuardianMode.OFF)
        screen.set_guardian_mode(GuardianMode.OBSERVE)
        self.assertEqual(screen.guardian_mode(), GuardianMode.OBSERVE)


if __name__ == "__main__":
    unittest.main()
