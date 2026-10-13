# -*- coding: utf-8 -*-
"""اختبارات G1.44 / chunk_4 — محوّل حالة حارس هبوط BTC (بلا QApplication، بلا شبكة).

يغطّي ``BtcFollowStatusAdapter`` و ``derive_btc_ui_state``:
  - OFF ⇒ enabled=False على المُشرِف + حالة DISABLED (كبح صلب).
  - OBSERVE ⇒ enabled=True, dry_run=True.
  - LIVE ⇒ enabled=True, dry_run=False.
  - tick المستقلّ يستدعي supervisor.tick() مرّة واحدة فقط حين non-OFF.
  - دفاعيّ: mode_getter يرمي ⇒ OFF.
"""
import unittest

from ocobot.domain.btc_follow import BtcFollowAction, BtcFollowDecision, BtcFollowPhase, BtcFollowState
from decimal import Decimal
from ocobot.domain.guardian_status import GuardianMode, GuardianStatusStore, GuardianUiState
from ocobot.ui.btc_follow_wiring import BtcFollowStatusAdapter, derive_btc_ui_state


class _FakeSupervisor:
    def __init__(self, btc_decision=None, btc_armed=False):
        self.ticks = 0
        self.runtime = []
        self.last_btc_decision = btc_decision
        self._btc_armed = btc_armed
        self.last_btc_result = {}

    def set_btc_runtime(self, *, enabled, dry_run):
        self.runtime.append((enabled, dry_run))

    def tick(self):
        self.ticks += 1
        return None


def _tighten():
    return BtcFollowDecision(
        action=BtcFollowAction.TIGHTEN, phase=BtcFollowPhase.IDLE,
        drop_pct=Decimal("1.5"), reason="confirmed_drop", state=BtcFollowState(),
    )


class DeriveBtcUiStateTests(unittest.TestCase):
    def test_off_is_disabled(self):
        self.assertIs(derive_btc_ui_state(GuardianMode.OFF, _tighten(), True), GuardianUiState.DISABLED)

    def test_none_decision_is_sleeping(self):
        self.assertIs(derive_btc_ui_state(GuardianMode.LIVE, None, False), GuardianUiState.SLEEPING)

    def test_tighten_or_armed_is_intervened(self):
        self.assertIs(derive_btc_ui_state(GuardianMode.LIVE, _tighten(), False), GuardianUiState.INTERVENED)
        d = BtcFollowDecision(action=BtcFollowAction.NOOP, phase=BtcFollowPhase.IDLE,
                              drop_pct=Decimal("0"), reason="x", state=BtcFollowState())
        self.assertIs(derive_btc_ui_state(GuardianMode.OBSERVE, d, True), GuardianUiState.INTERVENED)

    def test_arm_is_watching(self):
        d = BtcFollowDecision(action=BtcFollowAction.ARM, phase=BtcFollowPhase.ARMED,
                              drop_pct=Decimal("0.9"), reason="confirming", state=BtcFollowState())
        self.assertIs(derive_btc_ui_state(GuardianMode.OBSERVE, d, False), GuardianUiState.WATCHING)


class BtcFollowAdapterTests(unittest.TestCase):
    def _mk(self, mode, sup):
        box = {"m": mode}
        store = GuardianStatusStore()
        adapter = BtcFollowStatusAdapter(supervisor=sup, store=store, mode_getter=lambda: box["m"])
        return adapter, store, box

    def test_off_sets_disabled_runtime_and_no_tick(self):
        sup = _FakeSupervisor()
        adapter, store, _ = self._mk(GuardianMode.OFF, sup)
        adapter.tick()
        self.assertEqual(sup.ticks, 0)                 # OFF ⇒ لا tick
        self.assertEqual(sup.runtime[-1], (False, True))
        self.assertIs(store.status.state, GuardianUiState.DISABLED)

    def test_observe_runtime(self):
        sup = _FakeSupervisor(btc_decision=_tighten())
        adapter, store, _ = self._mk(GuardianMode.OBSERVE, sup)
        adapter.tick()
        self.assertEqual(sup.ticks, 1)
        self.assertEqual(sup.runtime[-1], (True, True))

    def test_live_runtime(self):
        sup = _FakeSupervisor(btc_decision=_tighten())
        adapter, store, _ = self._mk(GuardianMode.LIVE, sup)
        adapter.tick()
        self.assertEqual(sup.ticks, 1)
        self.assertEqual(sup.runtime[-1], (True, False))
        self.assertIs(store.status.state, GuardianUiState.INTERVENED)

    def test_apply_runtime_does_not_tick(self):
        sup = _FakeSupervisor()
        adapter, store, _ = self._mk(GuardianMode.LIVE, sup)
        adapter.apply_runtime()
        self.assertEqual(sup.ticks, 0)                 # apply_runtime بلا tick
        self.assertEqual(sup.runtime[-1], (True, False))

    def test_mode_getter_raises_falls_back_to_off(self):
        sup = _FakeSupervisor()

        def _boom():
            raise RuntimeError("boom")

        adapter = BtcFollowStatusAdapter(supervisor=sup, store=GuardianStatusStore(), mode_getter=_boom)
        adapter.tick()
        self.assertEqual(sup.ticks, 0)

    def test_push_status_only_no_tick(self):
        sup = _FakeSupervisor(btc_decision=_tighten())
        adapter, store, _ = self._mk(GuardianMode.LIVE, sup)
        adapter.push_status(GuardianMode.LIVE)
        self.assertEqual(sup.ticks, 0)                 # push_status لا يستدعي tick
        self.assertIs(store.status.state, GuardianUiState.INTERVENED)


if __name__ == "__main__":
    unittest.main()
