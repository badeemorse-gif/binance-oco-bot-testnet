# -*- coding: utf-8 -*-
"""اختبارات G1.59 — تطبيق Live لمتتبّع مُرشِّح النِّسب على «دورة التموضع التالية فقط».

تُغطّي العقد (state/defects/G1.59.json):
  - الاعتماد/الرفض وفق ضوابط المتتبّع (first/applied/cooldown/hysteresis/session_cap)
    منعكسًا على نِسب الدورة التالية عبر RepositionRecommendationBridge.pcts_for_next_cycle.
  - الحارس الصريح `enabled`: مع إيقافه لا تتغيّر نِسب الدورة التالية حتى لو اعتُمد Live.
  - Observe/Off لا يغيّران نِسب الدورة التالية (تبقى الأساس base).
  - build_draft_from_bridge قراءة فقط (P2): لا إلغاء/إنشاء ولا مسّ للأمر المفتوح
    لحظيًا، وتطابق تامّ مع build_draft المباشرة ⇒ ثبات رسائل/سلوك التموضع.
  - تدقيق audit يسجّل reason + applied_to_next_cycle لكل عرض.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest
from decimal import Decimal

from ocobot.domain.exchange_info import ExchangeInfoService
from ocobot.domain.oco_reader import OcoReader
from ocobot.domain.rec_tracker import (MODE_LIVE, MODE_OBSERVE, MODE_OFF,
                                       RecommendationTracker, TrackerParams)
from ocobot.domain.recommender import Recommendation
from ocobot.domain.reposition import (NextCyclePcts,
                                       RepositionRecommendationBridge,
                                       SafeExecutor)
from tests._fakes import FakeClient


class _Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


def _rec(tp="5.0", sl="4.0", trig="0.7"):
    return Recommendation(tp_pct=Decimal(tp), sl_pct=Decimal(sl),
                          trigger_pct=Decimal(trig), gap_ticks=1,
                          rationale={}, flags=[])


def _tracker(mode=MODE_LIVE, clock=None, cap=20):
    return RecommendationTracker(
        mode=mode,
        params=TrackerParams(min_delta_pct=0.2, cooldown_s=60.0,
                             max_changes_per_session=cap),
        clock=clock or _Clock())


def _executor(client):
    exi = ExchangeInfoService(client, monotonic=lambda: 1.0)
    reader = OcoReader(client)
    return SafeExecutor(client, reader, exi)


class BaselineTests(unittest.TestCase):
    def test_base_used_before_any_live(self):
        br = RepositionRecommendationBridge(
            _tracker(mode=MODE_OBSERVE), base_tp_pct="4", base_sl_pct="2",
            base_trigger_pct="0.5")
        p = br.pcts_for_next_cycle()
        self.assertIsInstance(p, NextCyclePcts)
        self.assertEqual(p.source, "base")
        self.assertEqual(p.tp_pct, Decimal("4"))
        self.assertEqual(p.sl_pct, Decimal("2"))
        self.assertEqual(p.trigger_pct, Decimal("0.5"))

    def test_observe_does_not_change_next_cycle(self):
        br = RepositionRecommendationBridge(
            _tracker(mode=MODE_OBSERVE), base_tp_pct="4", base_sl_pct="2")
        d = br.offer(_rec("9", "9", "9"))
        self.assertFalse(d.applied)
        self.assertEqual(d.reason, "observe")
        p = br.pcts_for_next_cycle()
        self.assertEqual(p.source, "base")
        self.assertEqual(p.tp_pct, Decimal("4"))

    def test_off_does_not_change_next_cycle(self):
        br = RepositionRecommendationBridge(
            _tracker(mode=MODE_OFF), base_tp_pct="4", base_sl_pct="2")
        d = br.offer(_rec("9", "9", "9"))
        self.assertFalse(d.applied)
        self.assertEqual(d.reason, "off")
        self.assertEqual(br.pcts_for_next_cycle().source, "base")


class LiveApplyTests(unittest.TestCase):
    def setUp(self):
        self.clock = _Clock()
        self.br = RepositionRecommendationBridge(
            _tracker(mode=MODE_LIVE, clock=self.clock, cap=2),
            base_tp_pct="4", base_sl_pct="2", base_trigger_pct="0.5")

    def test_first_live_applies_to_next_cycle(self):
        d = self.br.offer(_rec("5", "4", "0.7"))
        self.assertTrue(d.applied)
        self.assertEqual(d.reason, "first")
        p = self.br.pcts_for_next_cycle()
        self.assertEqual(p.source, "live_rec")
        self.assertEqual(p.tp_pct, Decimal("5"))
        self.assertEqual(p.sl_pct, Decimal("4"))
        self.assertEqual(p.trigger_pct, Decimal("0.7"))

    def test_cooldown_keeps_previous_applied(self):
        self.br.offer(_rec("5", "4", "0.7"))      # first applied
        self.clock.t += 10                         # < cooldown
        d = self.br.offer(_rec("9", "9", "9"))
        self.assertFalse(d.applied)
        self.assertEqual(d.reason, "cooldown")
        p = self.br.pcts_for_next_cycle()
        self.assertEqual(p.source, "live_rec")
        self.assertEqual(p.tp_pct, Decimal("5"))   # لم تتغيّر نِسب الدورة التالية

    def test_hysteresis_blocks_small_delta(self):
        self.br.offer(_rec("5", "4", "0.7"))
        self.clock.t += 100                        # تجاوز التهدئة
        d = self.br.offer(_rec("5.05", "4.0", "0.7"))  # Δ=0.05 < 0.2
        self.assertFalse(d.applied)
        self.assertEqual(d.reason, "hysteresis")
        self.assertEqual(self.br.pcts_for_next_cycle().tp_pct, Decimal("5"))

    def test_applies_after_cooldown_and_delta(self):
        self.br.offer(_rec("5", "4", "0.7"))
        self.clock.t += 100
        d = self.br.offer(_rec("6", "3", "0.9"))
        self.assertTrue(d.applied)
        self.assertEqual(d.reason, "applied")
        p = self.br.pcts_for_next_cycle()
        self.assertEqual(p.tp_pct, Decimal("6"))
        self.assertEqual(p.sl_pct, Decimal("3"))

    def test_session_cap_blocks(self):
        self.br.offer(_rec("5", "4", "0.7"))       # changes=1
        self.clock.t += 100
        self.br.offer(_rec("6", "3", "0.9"))       # changes=2
        self.clock.t += 100
        d = self.br.offer(_rec("7", "2", "1.1"))   # cap=2 ⇒ blocked
        self.assertFalse(d.applied)
        self.assertEqual(d.reason, "session_cap")
        self.assertEqual(self.br.pcts_for_next_cycle().tp_pct, Decimal("6"))


class GuardTests(unittest.TestCase):
    def test_disabled_guard_blocks_apply_to_cycle(self):
        clock = _Clock()
        br = RepositionRecommendationBridge(
            _tracker(mode=MODE_LIVE, clock=clock),
            base_tp_pct="4", base_sl_pct="2", enabled=False)
        d = br.offer(_rec("5", "4", "0.7"))
        # المتتبّع نفسه يعتمد، لكن الحارس يمنع التطبيق على التموضع
        self.assertTrue(d.applied)
        p = br.pcts_for_next_cycle()
        self.assertEqual(p.source, "base")
        self.assertEqual(p.tp_pct, Decimal("4"))
        last = br.audit_log[-1]
        self.assertTrue(last["tracker_applied"])
        self.assertFalse(last["applied_to_next_cycle"])

    def test_set_enabled_toggles(self):
        clock = _Clock()
        br = RepositionRecommendationBridge(
            _tracker(mode=MODE_LIVE, clock=clock),
            base_tp_pct="4", base_sl_pct="2", enabled=False)
        br.offer(_rec("5", "4", "0.7"))
        self.assertEqual(br.pcts_for_next_cycle().source, "base")
        br.set_enabled(True)
        clock.t += 100
        br.offer(_rec("6", "3", "0.9"))
        self.assertEqual(br.pcts_for_next_cycle().source, "live_rec")
        self.assertEqual(br.pcts_for_next_cycle().tp_pct, Decimal("6"))


class AuditTests(unittest.TestCase):
    def test_audit_records_reason_and_sink(self):
        sink = []
        clock = _Clock()
        br = RepositionRecommendationBridge(
            _tracker(mode=MODE_LIVE, clock=clock),
            base_tp_pct="4", base_sl_pct="2",
            audit=lambda r: sink.append(r))
        br.offer(_rec("5", "4", "0.7"))
        self.assertEqual(len(sink), 1)
        rec = sink[0]
        self.assertEqual(rec["event"], "reposition_bridge_offer")
        self.assertEqual(rec["reason"], "first")
        self.assertTrue(rec["applied_to_next_cycle"])
        self.assertEqual(rec["tpPct"], "5")
        self.assertEqual(rec["mode"], MODE_LIVE)


class NoLiveOrderTouchTests(unittest.TestCase):
    """build_draft_from_bridge قراءة فقط: لا إلغاء/إنشاء، وتطابق تامّ مع المباشرة."""

    def test_bridge_draft_matches_direct_and_no_writes(self):
        clock = _Clock()
        br = RepositionRecommendationBridge(
            _tracker(mode=MODE_LIVE, clock=clock),
            base_tp_pct="4", base_sl_pct="2")
        br.offer(_rec("4", "2", "0.7"))   # live-adopted == القيم المباشرة أدناه

        client = FakeClient()
        _, draft_bridge = _executor(client).build_draft_from_bridge(31, br, "60000")
        # لا كتابة إطلاقًا (لا مسّ للأمر المفتوح لحظيًا، ليست T16)
        self.assertEqual(client.cancel_calls(), [])
        self.assertEqual(client.create_calls(), [])

        client2 = FakeClient()
        _, draft_direct = _executor(client2).build_draft(31, "4", "2", "60000")
        # ثبات رسائل/سلوك التموضع: مطابقة الحقول المحسوبة مع المسار المباشر
        self.assertEqual(draft_bridge.tp_price, draft_direct.tp_price)
        self.assertEqual(draft_bridge.stop_trigger, draft_direct.stop_trigger)
        self.assertEqual(draft_bridge.stop_limit, draft_direct.stop_limit)
        self.assertEqual(draft_bridge.tp_pct, Decimal("4"))
        self.assertEqual(draft_bridge.sl_pct, Decimal("2"))

    def test_bridge_uses_base_when_no_live(self):
        br = RepositionRecommendationBridge(
            _tracker(mode=MODE_OBSERVE), base_tp_pct="4", base_sl_pct="2")
        client = FakeClient()
        _, draft = _executor(client).build_draft_from_bridge(31, br, "60000")
        self.assertEqual(draft.tp_pct, Decimal("4"))
        self.assertEqual(draft.sl_pct, Decimal("2"))
        self.assertEqual(client.cancel_calls(), [])
        self.assertEqual(client.create_calls(), [])


if __name__ == "__main__":
    unittest.main()
