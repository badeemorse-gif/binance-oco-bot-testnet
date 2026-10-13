"""اختبارات عنصر مؤشّر الحارس (G1.31 / chunk_2) — offscreen، بلا شبكة."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest

from ocobot.ui._qt import QApplication
from ocobot.ui.guardian_indicator import GuardianIndicator
from ocobot.domain.guardian_status import (
    GuardianMode,
    GuardianStatus,
    GuardianUiState,
    LastAction,
)

_app = QApplication.instance() or QApplication([])


class GuardianIndicatorTests(unittest.TestCase):
    def test_default_is_disabled_and_empty_action(self):
        w = GuardianIndicator()
        self.assertIn("مطفأ", w.state_text())
        self.assertEqual(w.last_action_text(), "")

    def test_sleeping_live_mode(self):
        w = GuardianIndicator()
        w.update_status(GuardianStatus(mode=GuardianMode.LIVE, state=GuardianUiState.SLEEPING))
        self.assertIn("نائم", w.state_text())
        self.assertIn("تدخّل", w.mode_text())  # mode=LIVE => "الوضع: تدخّل"

    def test_watching_observe_mode(self):
        w = GuardianIndicator()
        w.update_status(GuardianStatus(mode=GuardianMode.OBSERVE, state=GuardianUiState.WATCHING))
        self.assertIn("عُري", w.state_text())
        self.assertIn("مراقبة", w.mode_text())

    def test_intervened_shows_last_action(self):
        w = GuardianIndicator()
        la = LastAction(
            ts="2026-10-10T00:00:00Z",
            action="placed_protective_stop",
            reason="naked_timeout",
            qty="1.5",
            price="100.00",
        )
        w.update_status(
            GuardianStatus(mode=GuardianMode.LIVE, state=GuardianUiState.INTERVENED, last_action=la)
        )
        self.assertIn("تدخّل", w.state_text())
        txt = w.last_action_text()
        self.assertIn("1.5", txt)
        self.assertIn("100.00", txt)
        self.assertIn("naked_timeout", txt)

    def test_update_back_to_disabled_clears_action(self):
        w = GuardianIndicator()
        la = LastAction(ts="t", action="placed_protective_stop", qty="1")
        w.update_status(GuardianStatus(state=GuardianUiState.INTERVENED, last_action=la))
        self.assertNotEqual(w.last_action_text(), "")
        w.update_status(GuardianStatus())  # back to default (OFF/DISABLED, no action)
        self.assertIn("مطفأ", w.state_text())
        self.assertEqual(w.last_action_text(), "")


if __name__ == "__main__":
    unittest.main()
