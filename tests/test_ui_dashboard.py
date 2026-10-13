import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest

from ocobot.ui._qt import QApplication
from ocobot.ui.theme import apply_theme
from ocobot.ui.dashboard import (
    DashboardScreen,
    DASHBOARD_FIELDS,
    EMPTY,
    NO_SELECTION_NOTE,
)
from ocobot.ui.content import ContentRouter
from ocobot.domain.selection import build_dashboard


def _snapshot(**overrides):
    snap = build_dashboard(
        None,
        environment=overrides.pop("environment", "testnet"),
        connection=overrides.pop("connection", "OK"),
    )
    for key, value in overrides.items():
        setattr(snap, key, value)
    return snap


class DashboardScreenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    def test_initial_state_shows_placeholders(self):
        screen = DashboardScreen()
        self.assertEqual(screen.note.text(), NO_SELECTION_NOTE)
        for _label, attr in DASHBOARD_FIELDS:
            self.assertIn(attr, screen._cards)
            self.assertEqual(screen._cards[attr].value.text(), EMPTY)

    def test_all_canonical_fields_present(self):
        screen = DashboardScreen()
        self.assertEqual(len(screen._cards), len(DASHBOARD_FIELDS))
        self.assertEqual(len(screen._cards), 11)

    def test_renders_empty_snapshot_from_build_dashboard(self):
        screen = DashboardScreen()
        screen.update_snapshot(build_dashboard(None, environment="testnet", connection="OK"))
        self.assertEqual(screen._cards["environment"].value.text(), "testnet")
        self.assertEqual(screen._cards["connection"].value.text(), "OK")
        self.assertEqual(screen._cards["monitoring_state"].value.text(), "IDLE")
        self.assertEqual(screen._cards["selected_oco"].value.text(), EMPTY)
        self.assertEqual(screen.note.text(), NO_SELECTION_NOTE)

    def test_renders_selected_snapshot(self):
        screen = DashboardScreen()
        screen.update_snapshot(_snapshot(
            selected_oco="31",
            symbol="BTCUSDT",
            current_tp="70000",
            current_sl="58500",
            monitoring_state="ACTIVE",
        ))
        self.assertEqual(screen._cards["selected_oco"].value.text(), "31")
        self.assertEqual(screen._cards["symbol"].value.text(), "BTCUSDT")
        self.assertEqual(screen._cards["current_tp"].value.text(), "70000")
        self.assertEqual(screen._cards["current_sl"].value.text(), "58500")
        self.assertEqual(screen._cards["monitoring_state"].value.text(), "ACTIVE")
        self.assertEqual(screen.note.text(), "")

    def test_refresh_synchronous_without_runner(self):
        screen = DashboardScreen()
        snap = _snapshot(symbol="ETHUSDT", selected_oco="99")
        screen.refresh(build_fn=lambda: snap)
        self.assertEqual(screen._cards["symbol"].value.text(), "ETHUSDT")
        self.assertEqual(screen._cards["selected_oco"].value.text(), "99")

    def test_registered_in_content_router(self):
        router = ContentRouter()
        page = router.screen_for("01_dashboard")
        self.assertIsInstance(page, DashboardScreen)
        self.assertTrue(router.show_screen("01_dashboard"))
        self.assertEqual(router.current_key(), "01_dashboard")


if __name__ == "__main__":
    unittest.main()
