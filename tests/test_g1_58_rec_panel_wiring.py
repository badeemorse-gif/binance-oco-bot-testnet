# -*- coding: utf-8 -*-
"""اختبارات G1.58 — تركيب لوحة مُرشِّح النِّسب (RecommendationPanel) في شاشة المراقبة.

offscreen، بلا شبكة. تغطّي عقد G1.58 (acceptance_checks):
  (أ) RecommendationPanel مركّبة ضمن DynamicMonitoringScreen (مباشرةً وعبر build_app).
  (ب) «ملء مرّة واحدة» يملأ self._pct_edits[trigger_pct/tp_pct/sl_pct] من الاقتراح.
  (ج) تبديل الوضع من اللوحة يضبط RecommendationTracker.set_mode.
  (د) حلقة إعادة الحساب عبر رَنَر محقون (Observe) تحدّث اللوحة وتُقدّم للمتتبّع.
  (هـ) بلا provider/runner ⇒ no-op آمن؛ وLive لا يملأ النِّسب (لا تموضع تلقائي — G1.59).
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest
from decimal import Decimal

from ocobot.ui._qt import QApplication
from ocobot.ui.theme import apply_theme
from ocobot.ui.monitoring import DynamicMonitoringScreen
from ocobot.ui.rec_panel import RecommendationPanel, MODE_OFF, MODE_LIVE
from ocobot.domain.recommender import Recommendation
from ocobot.domain.models import fmt


def _rec():
    return Recommendation(
        tp_pct=Decimal("4"),
        sl_pct=Decimal("2"),
        trigger_pct=Decimal("1.5"),
        gap_ticks=3,
        rationale={"regimeLabel": "trend"},
        flags=["ok"],
    )


class _FakeRunner:
    """رَنَر متزامن للاختبار: ينفّذ fn ثم on_result/on_error فورًا (بلا خيوط/شبكة)."""

    def __init__(self):
        self.calls = 0

    def submit(self, fn, *args, on_result=None, on_error=None):
        self.calls += 1
        try:
            res = fn(*args)
        except Exception as exc:  # pragma: no cover - دفاعي
            if on_error:
                on_error(exc)
            return None
        if on_result:
            on_result(res)
        return None


class G1_58_RecPanelWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        try:
            apply_theme(cls.app)
        except Exception:
            pass

    def test_panel_mounted_direct(self):
        screen = DynamicMonitoringScreen(runner=None)
        self.assertTrue(hasattr(screen, "rec_panel"))
        self.assertIsInstance(screen.rec_panel, RecommendationPanel)
        # اللوحة طفلة فعليّة للشاشة (أُضيفت إلى root).
        self.assertIsNotNone(screen.findChild(RecommendationPanel))

    def test_panel_mounted_via_build_app(self):
        from ocobot.ui.app import build_app
        _app, window = build_app()
        mon = window.findChild(DynamicMonitoringScreen)
        self.assertIsNotNone(mon, "DynamicMonitoringScreen يجب أن تُبنى عبر build_app")
        self.assertIsNotNone(
            mon.findChild(RecommendationPanel),
            "RecommendationPanel يجب أن تكون مركّبة داخل شاشة المراقبة",
        )

    def test_fill_once_populates_pct_edits(self):
        screen = DynamicMonitoringScreen(runner=None)
        rec = _rec()
        screen.rec_panel.update_recommendation(rec)
        screen._on_rec_fill_once(rec)
        self.assertEqual(screen._pct_edits["trigger_pct"].text(), fmt(rec.trigger_pct))
        self.assertEqual(screen._pct_edits["tp_pct"].text(), fmt(rec.tp_pct))
        self.assertEqual(screen._pct_edits["sl_pct"].text(), fmt(rec.sl_pct))

    def test_mode_change_from_panel_sets_tracker(self):
        screen = DynamicMonitoringScreen(runner=None)
        # الافتراضي observe؛ التبديل من اللوحة يجب أن ينعكس على المتتبّع.
        screen.rec_panel.set_mode(MODE_OFF)
        self.assertEqual(screen._rec_tracker.mode, MODE_OFF)
        screen.rec_panel.set_mode(MODE_LIVE)
        self.assertEqual(screen._rec_tracker.mode, MODE_LIVE)

    def test_recompute_with_fake_runner_updates_panel_and_tracker(self):
        rec = _rec()
        runner = _FakeRunner()
        screen = DynamicMonitoringScreen(runner=runner, recommendation_provider=lambda: rec)
        screen._recompute_recommendation()
        self.assertEqual(runner.calls, 1)
        self.assertIs(screen.rec_panel.current_recommendation(), rec)
        # الوضع الافتراضي observe ⇒ المتتبّع يرصد دون اعتماد.
        self.assertIs(screen._rec_tracker.last_observed, rec)

    def test_recompute_noop_without_provider_or_runner(self):
        # بلا provider.
        s1 = DynamicMonitoringScreen(runner=_FakeRunner())
        s1._recompute_recommendation()  # يجب ألا يرفع ولا يستدعي الرَنَر
        self.assertEqual(s1.runner.calls, 0)
        # بلا runner.
        s2 = DynamicMonitoringScreen(runner=None, recommendation_provider=lambda: _rec())
        s2._recompute_recommendation()  # لا يرفع
        self.assertIsNone(s2.rec_panel.current_recommendation())

    def test_live_mode_does_not_autofill_rules(self):
        rec = _rec()
        runner = _FakeRunner()
        screen = DynamicMonitoringScreen(runner=runner, recommendation_provider=lambda: rec)
        screen.rec_panel.set_mode(MODE_LIVE)
        screen._recompute_recommendation()
        # Live يعرض/يدقّق فقط؛ لا يملأ حقول النِّسب تلقائيًّا (لا تموضع — G1.59).
        self.assertEqual(screen._pct_edits["trigger_pct"].text(), "")
        self.assertEqual(screen._pct_edits["tp_pct"].text(), "")
        self.assertEqual(screen._pct_edits["sl_pct"].text(), "")


if __name__ == "__main__":
    unittest.main()
