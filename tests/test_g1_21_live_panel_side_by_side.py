import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest

from ocobot.ui._qt import QFrame, QLabel, QGridLayout, Qt, QApplication
from ocobot.ui.theme import apply_theme
from ocobot.ui.monitoring import DynamicMonitoringScreen, LIVE_FIELDS
from tests.test_ui_monitoring import _sample


class TestG121LivePanelSideBySide(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    def _build_screen(self):
        screen = DynamicMonitoringScreen()
        screen.set_selected(_sample())
        screen.show()
        QApplication.processEvents()
        return screen

    def _grid(self, screen):
        card = screen.findChild(QFrame, "MonitoringLiveCard")
        self.assertIsNotNone(card, "MonitoringLiveCard not found")
        vlay = card.layout()
        self.assertIsNotNone(vlay, "live card has no layout")
        grid = None
        for i in range(vlay.count()):
            item = vlay.itemAt(i)
            if item is not None and isinstance(item.layout(), QGridLayout):
                grid = item.layout()
                break
        self.assertIsNotNone(grid, "QGridLayout not found inside live card")
        return grid

    def test_paired_and_single_rows(self):
        screen = self._build_screen()
        grid = self._grid(screen)

        def pos(key):
            cap = screen.findChild(QLabel, "MonitoringLiveCaption_%s" % key)
            self.assertIsNotNone(cap, "caption not found for %s" % key)
            return grid.getItemPosition(grid.indexOf(cap))

        # current_tp / next_tp share a row, different columns.
        self.assertEqual(pos("current_tp")[0], pos("next_tp")[0])
        self.assertNotEqual(pos("current_tp")[1], pos("next_tp")[1])

        # current_sl / next_sl share a row, different columns.
        self.assertEqual(pos("current_sl")[0], pos("next_sl")[0])
        self.assertNotEqual(pos("current_sl")[1], pos("next_sl")[1])

        # SL pair row is immediately below the TP pair row.
        self.assertEqual(pos("current_sl")[0], pos("current_tp")[0] + 1)

        # Single full-width rows after the SL pair.
        for k in (
            "sl_limit",
            "tick_size",
            "monitoring_state",
            "last_operation",
            "connection",
            "environment",
        ):
            self.assertGreater(pos(k)[0], pos("current_sl")[0])

        # Single full-width rows before the TP pair.
        for k in (
            "symbol",
            "order_list_id",
            "current_price",
            "reference_price",
            "trigger_price",
        ):
            self.assertLess(pos(k)[0], pos("current_tp")[0])

    def test_all_live_fields_present_and_visible(self):
        screen = self._build_screen()
        for k, _ in LIVE_FIELDS:
            self.assertIn(k, screen._live)
            self.assertTrue(screen._live[k].isVisible())


if __name__ == "__main__":
    unittest.main()
