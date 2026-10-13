# -*- coding: utf-8 -*-
"""اختبارات وحدة لمُنسّق حارس هبوط BTC والتحكيم (G1.44 / chunk_2)."""
import unittest
from decimal import Decimal

from ocobot.domain.btc_follow import BtcFollowAction, BtcFollowConfig, BtcFollowPhase
from ocobot.domain.btc_follow_supervisor import BtcFollowSupervisor, should_btc_tighten


class _FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class TestBtcFollowSupervisor(unittest.TestCase):
    def setUp(self):
        self.cfg = BtcFollowConfig(
            enabled=True,
            drop_pct=Decimal("0.8"),
            window_seconds=3.0,
            confirm_seconds=1.0,
        )

    def test_disabled_default_is_noop(self):
        sup = BtcFollowSupervisor()  # الافتراضي OFF
        sup.ingest(60000, ts=0.0)
        sup.ingest(59000, ts=1.0)
        d = sup.tick(now=1.0)
        self.assertIs(d.action, BtcFollowAction.NOOP)
        self.assertEqual(d.reason, "disabled")

    def test_arm_then_tighten_sequence(self):
        sup = BtcFollowSupervisor(config=self.cfg)
        sup.ingest(60000, ts=0.0)
        sup.ingest(59400, ts=1.0)   # هبوط 1%
        d1 = sup.tick(now=1.0)
        self.assertIs(d1.action, BtcFollowAction.ARM)
        self.assertIs(sup.state.phase, BtcFollowPhase.ARMED)
        # ضمن نافذة التأكيد
        sup.ingest(59350, ts=1.4)
        d2 = sup.tick(now=1.4)
        self.assertIs(d2.action, BtcFollowAction.ARM)
        self.assertEqual(d2.reason, "confirming")
        # تأكّد الهبوط بعد ثانية
        sup.ingest(59100, ts=2.1)
        d3 = sup.tick(now=2.1)
        self.assertIs(d3.action, BtcFollowAction.TIGHTEN)
        self.assertIs(sup.state.phase, BtcFollowPhase.IDLE)

    def test_poll_failsafe_on_price_fn_error(self):
        def boom():
            raise RuntimeError("feed down")

        sup = BtcFollowSupervisor(config=self.cfg, price_fn=boom)
        # يجب ألّا يرمي، ولا يضيف عيّنات.
        sup.poll(now=1.0)
        self.assertEqual(sup.sample_count, 0)
        d = sup.tick(now=1.0)
        self.assertIs(d.action, BtcFollowAction.NOOP)
        self.assertEqual(d.reason, "insufficient_data")

    def test_poll_uses_price_fn(self):
        prices = iter([Decimal("60000"), Decimal("59400")])
        sup = BtcFollowSupervisor(config=self.cfg, price_fn=lambda: next(prices))
        sup.poll(now=0.0)
        sup.poll(now=1.0)
        self.assertEqual(sup.sample_count, 2)
        d = sup.tick(now=1.0)
        self.assertIs(d.action, BtcFollowAction.ARM)

    def test_ingest_ignores_nonpositive(self):
        sup = BtcFollowSupervisor(config=self.cfg)
        sup.ingest(0, ts=0.0)
        sup.ingest(-5, ts=0.5)
        self.assertEqual(sup.sample_count, 0)

    def test_prune_bounds_samples(self):
        sup = BtcFollowSupervisor(config=self.cfg, max_samples=16)
        for i in range(200):
            sup.ingest(60000, ts=float(i) * 0.01)
        # التقليم يحدّ العدد الأقصى.
        self.assertLessEqual(sup.sample_count, 16)

    def test_reset_clears_state(self):
        sup = BtcFollowSupervisor(config=self.cfg)
        sup.ingest(60000, ts=0.0)
        sup.ingest(59400, ts=1.0)
        sup.tick(now=1.0)
        sup.reset()
        self.assertEqual(sup.sample_count, 0)
        self.assertIs(sup.state.phase, BtcFollowPhase.IDLE)
        self.assertIsNone(sup.last_decision)


class TestBtcArbitration(unittest.TestCase):
    def _tighten(self):
        cfg = BtcFollowConfig(enabled=True)
        sup = BtcFollowSupervisor(config=cfg)
        sup.ingest(60000, ts=0.0)
        sup.ingest(59400, ts=1.0)
        sup.tick(now=1.0)              # ARM
        sup.ingest(59100, ts=2.1)
        return sup.tick(now=2.1)       # TIGHTEN

    def test_guardian_priority_blocks_btc(self):
        d = self._tighten()
        self.assertIs(d.action, BtcFollowAction.TIGHTEN)
        # شبكة أمان المركز متدخّلة ⇒ حارس BTC لا يتصرّف (أولوية قصوى).
        self.assertFalse(
            should_btc_tighten(
                d,
                has_resting_protective_sell=False,
                free_qty=Decimal("10"),
                monitored_qty=Decimal("10"),
                guardian_intervening=True,
            )
        )

    def test_btc_acts_when_free_qty_and_confirmed(self):
        d = self._tighten()
        self.assertTrue(
            should_btc_tighten(
                d,
                has_resting_protective_sell=True,
                free_qty=Decimal("10"),
                monitored_qty=Decimal("10"),
                guardian_intervening=False,
            )
        )

    def test_btc_blocked_when_no_free_qty(self):
        d = self._tighten()
        self.assertFalse(
            should_btc_tighten(
                d,
                has_resting_protective_sell=True,
                free_qty=Decimal("0"),
                monitored_qty=Decimal("10"),
                guardian_intervening=False,
            )
        )

    def test_non_tighten_does_not_act(self):
        cfg = BtcFollowConfig(enabled=True)
        sup = BtcFollowSupervisor(config=cfg)
        sup.ingest(60000, ts=0.0)
        sup.ingest(59400, ts=1.0)
        d = sup.tick(now=1.0)  # ARM فقط
        self.assertIs(d.action, BtcFollowAction.ARM)
        self.assertFalse(
            should_btc_tighten(
                d,
                has_resting_protective_sell=False,
                free_qty=Decimal("10"),
                monitored_qty=Decimal("10"),
                guardian_intervening=False,
            )
        )


if __name__ == "__main__":
    unittest.main()
