# -*- coding: utf-8 -*-
"""اختبارات وحدة لحارس هبوط BTC الخالص (G1.44 / chunk_1)."""
import unittest
from decimal import Decimal

from ocobot.domain.btc_follow import (
    BtcFollowAction,
    BtcFollowConfig,
    BtcFollowPhase,
    BtcFollowState,
    BtcSample,
    evaluate,
)


def _samples(pairs):
    return [BtcSample(ts=t, price=Decimal(str(p))) for t, p in pairs]


class TestBtcFollowGuard(unittest.TestCase):
    def setUp(self):
        # عتبة 0.8% خلال نافذة 3s، تأكيد 1s، مُفعّل للاختبار.
        self.cfg = BtcFollowConfig(
            enabled=True,
            drop_pct=Decimal("0.8"),
            window_seconds=3.0,
            confirm_seconds=1.0,
        )
        self.idle = BtcFollowState()

    def test_default_config_is_off(self):
        self.assertFalse(BtcFollowConfig().enabled)

    def test_disabled_is_noop(self):
        cfg = BtcFollowConfig(enabled=False)
        s = _samples([(0.0, 60000), (1.0, 59000)])
        d = evaluate(s, cfg, self.idle, now=1.0)
        self.assertIs(d.action, BtcFollowAction.NOOP)
        self.assertEqual(d.reason, "disabled")
        self.assertIs(d.state.phase, BtcFollowPhase.IDLE)

    def test_insufficient_data_is_noop(self):
        d = evaluate(_samples([(1.0, 60000)]), self.cfg, self.idle, now=1.0)
        self.assertIs(d.action, BtcFollowAction.NOOP)
        self.assertEqual(d.reason, "insufficient_data")

    def test_empty_samples_is_noop(self):
        d = evaluate([], self.cfg, self.idle, now=5.0)
        self.assertIs(d.action, BtcFollowAction.NOOP)
        self.assertEqual(d.reason, "insufficient_data")

    def test_below_threshold_noop(self):
        # هبوط 0.3% فقط < 0.8%.
        s = _samples([(0.0, 60000), (1.0, 59820)])
        d = evaluate(s, self.cfg, self.idle, now=1.0)
        self.assertIs(d.action, BtcFollowAction.NOOP)
        self.assertEqual(d.reason, "below_threshold")
        self.assertIs(d.state.phase, BtcFollowPhase.IDLE)

    def test_drop_detected_arms(self):
        # هبوط 1.0% ≥ 0.8%.
        s = _samples([(0.0, 60000), (1.0, 59400)])
        d = evaluate(s, self.cfg, self.idle, now=1.0)
        self.assertIs(d.action, BtcFollowAction.ARM)
        self.assertIs(d.phase, BtcFollowPhase.ARMED)
        self.assertEqual(d.reason, "drop_detected")
        self.assertEqual(d.state.armed_at, 1.0)
        self.assertEqual(d.state.armed_ref_price, Decimal("60000"))

    def test_confirming_within_window(self):
        armed = BtcFollowState(
            phase=BtcFollowPhase.ARMED, armed_at=1.0, armed_ref_price=Decimal("60000")
        )
        s = _samples([(0.0, 60000), (1.0, 59400), (1.5, 59300)])
        d = evaluate(s, self.cfg, armed, now=1.5)  # elapsed 0.5 < 1.0
        self.assertIs(d.action, BtcFollowAction.ARM)
        self.assertEqual(d.reason, "confirming")
        self.assertIs(d.phase, BtcFollowPhase.ARMED)

    def test_confirmed_drop_tightens(self):
        armed = BtcFollowState(
            phase=BtcFollowPhase.ARMED, armed_at=1.0, armed_ref_price=Decimal("60000")
        )
        # استمرّ الهبوط: ذروة النافذة 60000، الحالي 59100 ⇒ 1.5%.
        s = _samples([(0.0, 60000), (1.0, 59400), (2.1, 59100)])
        d = evaluate(s, self.cfg, armed, now=2.1)  # elapsed 1.1 ≥ 1.0
        self.assertIs(d.action, BtcFollowAction.TIGHTEN)
        self.assertEqual(d.reason, "confirmed_drop")
        self.assertIs(d.state.phase, BtcFollowPhase.IDLE)
        self.assertGreaterEqual(d.drop_pct, Decimal("0.8"))

    def test_recovered_fakeout_noop(self):
        armed = BtcFollowState(
            phase=BtcFollowPhase.ARMED, armed_at=1.0, armed_ref_price=Decimal("60000")
        )
        # ارتدّ: ذروة النافذة والحالي متساويان ⇒ ~0% < 0.8%.
        s = _samples([(1.0, 59400), (2.1, 59950)])
        d = evaluate(s, self.cfg, armed, now=2.1)
        self.assertIs(d.action, BtcFollowAction.NOOP)
        self.assertEqual(d.reason, "recovered_fakeout")
        self.assertIs(d.state.phase, BtcFollowPhase.IDLE)

    def test_full_sequence_idle_to_tighten(self):
        st = BtcFollowState()
        d1 = evaluate(
            _samples([(0.0, 60000), (1.0, 59400)]), self.cfg, st, now=1.0
        )
        self.assertIs(d1.action, BtcFollowAction.ARM)
        d2 = evaluate(
            _samples([(0.0, 60000), (1.0, 59400), (1.4, 59350)]),
            self.cfg,
            d1.state,
            now=1.4,
        )
        self.assertIs(d2.action, BtcFollowAction.ARM)
        self.assertEqual(d2.reason, "confirming")
        d3 = evaluate(
            _samples([(0.0, 60000), (1.0, 59400), (2.1, 59100)]),
            self.cfg,
            d2.state,
            now=2.1,
        )
        self.assertIs(d3.action, BtcFollowAction.TIGHTEN)
        self.assertIs(d3.state.phase, BtcFollowPhase.IDLE)


if __name__ == "__main__":
    unittest.main()
