# -*- coding: utf-8 -*-
"""اختبارات دمج حارس هبوط BTC في GuardianSupervisor (G1.44 / chunk_3)."""
import unittest
from decimal import Decimal
from types import SimpleNamespace

from ocobot.domain.guardian import GuardianConfig
from ocobot.domain.guardian_supervisor import GuardianSupervisor
from ocobot.domain.btc_follow import (
    BtcFollowAction,
    BtcFollowDecision,
    BtcFollowPhase,
    BtcFollowState,
)


class _FakeBtc:
    """بديل btc_follow يُعيد قرارًا ثابتًا لكل tick."""

    def __init__(self, action):
        self._action = action
        self.ticks = 0

    def tick(self, now=None):
        self.ticks += 1
        return BtcFollowDecision(
            action=self._action,
            phase=BtcFollowPhase.IDLE,
            drop_pct=Decimal("1.5"),
            reason="confirmed_drop",
            state=BtcFollowState(),
        )


class _Client:
    def __init__(self, resting, free):
        self._resting = list(resting)
        self._free = free
        self.placed = []

    def get_open_sell_orders(self, symbol):
        return list(self._resting)

    def get_free_asset_qty(self, asset):
        return self._free

    def place_stop_loss_limit(self, **kw):
        self.placed.append(kw)
        return {"ok": True}


_FILTERS = SimpleNamespace(
    symbol="ADAUSDT",
    tick_size=Decimal("0.0001"),
    step_size=Decimal("0.1"),
    gap_ticks=2,
)


def _state(symbol="ADAUSDT", state="MONITORING_ACTIVE", qty=Decimal("10")):
    return SimpleNamespace(
        symbol=symbol,
        enabled=True,
        state=state,
        in_flight=False,
        last_price=Decimal("0.42"),
        reference_price=Decimal("0.42"),
        selected_oco=SimpleNamespace(quantity=qty, filters=_FILTERS),
        filters=_FILTERS,
    )


class TestGuardianBtcIntegration(unittest.TestCase):
    def _make(self, *, dry_run, resting, exit_fn=None,
              btc_action=BtcFollowAction.TIGHTEN, state_name="MONITORING_ACTIVE"):
        client = _Client(resting=resting, free=Decimal("10"))
        calls = {"exit": [], "alerts": []}

        def default_exit(**kw):
            calls["exit"].append(kw)
            return {"action": "EXIT_TRIGGERED", "placed": True}

        sup = GuardianSupervisor(
            state_provider=lambda: _state(state=state_name),
            client=client,
            alert_cb=lambda t: None,
            config=GuardianConfig(),
            dry_run=dry_run,
            base_asset_fn=lambda s: "ADA",
            filters_fn=lambda s: _FILTERS,
            reference_price_fn=lambda st: Decimal("0.42"),
            btc_follow=_FakeBtc(btc_action),
            btc_exit_fn=exit_fn if exit_fn is not None else default_exit,
            btc_alert_cb=lambda t: calls["alerts"].append(t),
        )
        return sup, client, calls

    def test_btc_tighten_executes_live(self):
        sup, client, calls = self._make(dry_run=False, resting=["oco-leg"])
        sup.tick()
        self.assertEqual(len(calls["exit"]), 1)
        self.assertEqual(sup.last_btc_result.get("action"), "EXIT_TRIGGERED")
        self.assertTrue(calls["alerts"])

    def test_btc_idempotent_single_exit(self):
        sup, client, calls = self._make(dry_run=False, resting=["oco-leg"])
        sup.tick()
        sup.tick()
        sup.tick()
        self.assertEqual(len(calls["exit"]), 1)

    def test_btc_dry_run_observe_no_exit(self):
        sup, client, calls = self._make(dry_run=True, resting=["oco-leg"])
        sup.tick()
        self.assertEqual(len(calls["exit"]), 0)
        self.assertEqual(sup.last_btc_result.get("action"), "DRY_RUN")

    def test_btc_not_tighten_does_not_exit(self):
        sup, client, calls = self._make(
            dry_run=False, resting=["oco-leg"], btc_action=BtcFollowAction.ARM
        )
        sup.tick()
        self.assertEqual(len(calls["exit"]), 0)

    def test_guardian_priority_blocks_btc(self):
        # مركز عارٍ + FAILED_NEEDS_ATTENTION ⇒ شبكة الأمان تتدخّل ⇒ BTC لا يُستشار.
        sup, client, calls = self._make(
            dry_run=True, resting=[], state_name="FAILED_NEEDS_ATTENTION"
        )
        sup.tick()
        self.assertIsNone(sup.last_btc_decision)
        self.assertEqual(len(calls["exit"]), 0)

    def test_btc_none_is_pure_noop(self):
        client = _Client(resting=["oco-leg"], free=Decimal("10"))
        sup = GuardianSupervisor(
            state_provider=lambda: _state(),
            client=client,
            alert_cb=lambda t: None,
            config=GuardianConfig(),
            dry_run=False,
            base_asset_fn=lambda s: "ADA",
            filters_fn=lambda s: _FILTERS,
        )
        sup.tick()
        self.assertIsNone(getattr(sup, "last_btc_decision", None))


if __name__ == "__main__":
    unittest.main()
