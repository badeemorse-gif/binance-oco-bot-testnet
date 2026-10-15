# -*- coding: utf-8 -*-
"""اختبارات G1.56 · c7 — وحدة تحكّم الوضع المتتبّع (rec_tracker.py) + التوصيل."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest
from decimal import Decimal

from ocobot.domain.rec_tracker import (MODE_LIVE, MODE_OBSERVE, MODE_OFF,
                                       RecommendationTracker, TrackerParams,
                                       max_delta_pct)
from ocobot.domain.recommender import Recommendation


class _Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def _rec(tp="5.0", sl="4.0", trig="0.7"):
    return Recommendation(tp_pct=Decimal(tp), sl_pct=Decimal(sl),
                          trigger_pct=Decimal(trig), gap_ticks=1,
                          rationale={}, flags=[])


class MaxDeltaTests(unittest.TestCase):
    def test_delta(self):
        self.assertAlmostEqual(max_delta_pct(_rec("5.0"), _rec("5.3")), 0.3, places=9)
        self.assertEqual(max_delta_pct(None, _rec()), float("inf"))


class ModeTests(unittest.TestCase):
    def test_default_observe(self):
        self.assertEqual(RecommendationTracker().mode, MODE_OBSERVE)

    def test_invalid_mode_raises(self):
        with self.assertRaises(ValueError):
            RecommendationTracker(mode="bogus")
        t = RecommendationTracker()
        with self.assertRaises(ValueError):
            t.set_mode("bogus")

    def test_mode_change_audited(self):
        t = RecommendationTracker(mode=MODE_OBSERVE)
        t.set_mode(MODE_LIVE)
        events = [r for r in t.audit_log if r["event"] == "mode_change"]
        self.assertTrue(any(r["mode"] == MODE_LIVE for r in events))


class OffObserveTests(unittest.TestCase):
    def test_off_ignores(self):
        t = RecommendationTracker(mode=MODE_OFF)
        d = t.offer(_rec())
        self.assertFalse(d.applied)
        self.assertEqual(d.reason, "off")
        self.assertIsNone(t.last_applied)

    def test_observe_never_applies_but_records(self):
        t = RecommendationTracker(mode=MODE_OBSERVE)
        d = t.offer(_rec())
        self.assertFalse(d.applied)
        self.assertEqual(d.reason, "observe")
        self.assertIsNotNone(t.last_observed)
        self.assertTrue(any(r["event"] == "tracker_offer" for r in t.audit_log))


class LiveGuardTests(unittest.TestCase):
    def setUp(self):
        self.clock = _Clock()
        self.t = RecommendationTracker(
            mode=MODE_LIVE,
            params=TrackerParams(min_delta_pct=0.2, cooldown_s=60.0,
                                 max_changes_per_session=2),
            clock=self.clock)

    def test_first_applies(self):
        d = self.t.offer(_rec("5.0"))
        self.assertTrue(d.applied)
        self.assertEqual(d.reason, "first")
        self.assertEqual(self.t.changes_count, 1)

    def test_cooldown_blocks(self):
        self.t.offer(_rec("5.0"))
        self.clock.t += 10  # < cooldown
        d = self.t.offer(_rec("9.0"))
        self.assertFalse(d.applied)
        self.assertEqual(d.reason, "cooldown")

    def test_hysteresis_blocks_small_delta(self):
        self.t.offer(_rec("5.0"))
        self.clock.t += 100  # تجاوز التهدئة
        d = self.t.offer(_rec("5.05"))  # فرق 0.05 < 0.2
        self.assertFalse(d.applied)
        self.assertEqual(d.reason, "hysteresis")

    def test_applies_after_cooldown_and_delta(self):
        self.t.offer(_rec("5.0"))
        self.clock.t += 100
        d = self.t.offer(_rec("6.0"))
        self.assertTrue(d.applied)
        self.assertEqual(d.reason, "applied")
        self.assertEqual(self.t.changes_count, 2)

    def test_session_cap(self):
        self.t.offer(_rec("5.0"))         # changes=1
        self.clock.t += 100
        self.t.offer(_rec("6.0"))         # changes=2
        self.clock.t += 100
        d = self.t.offer(_rec("7.0"))     # cap=2 ⇒ blocked
        self.assertFalse(d.applied)
        self.assertEqual(d.reason, "session_cap")

    def test_reset_session(self):
        self.t.offer(_rec("5.0"))
        self.t.reset_session()
        self.assertEqual(self.t.changes_count, 0)
        self.assertIsNone(self.t.last_applied)

    def test_audit_sink_called(self):
        sink = []
        t = RecommendationTracker(mode=MODE_LIVE, clock=_Clock(),
                                  audit=sink.append)
        t.offer(_rec("5.0"))
        self.assertTrue(any(r["applied"] for r in sink))


class WiringTests(unittest.TestCase):
    def test_panel_mode_combo_drives_tracker(self):
        from ocobot.ui._qt import QApplication
        from ocobot.ui.rec_panel import RecommendationPanel
        app = QApplication.instance() or QApplication([])
        tracker = RecommendationTracker()
        panel = RecommendationPanel(on_mode_change=tracker.set_mode)
        panel.set_mode(MODE_LIVE)
        self.assertEqual(tracker.mode, MODE_LIVE)
        panel.set_mode(MODE_OFF)
        self.assertEqual(tracker.mode, MODE_OFF)


if __name__ == "__main__":
    unittest.main()
