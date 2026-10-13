# -*- coding: utf-8 -*-
"""G1.22 — حارس اللوحة الحيّة: سعرا الحالي/التالي "متقابلان" في صفّي TP/SL.

يتحقق — على نمط باقي اختبارات واجهة المراقبة (offscreen، بلا شبكة) — من أنّ
صفَّي جني الأرباح (TP) ووقف الخسارة (SL) في شبكة اللوحة الحيّة أُعيد ترتيبهما إلى
خمسة أعمدة بترتيب RTL (col0 أقصى اليمين):

    col0 = caption_current
    col1 = value_current
    col2 = السهم "←"  (QLabel مستقل، غير مُضاف إلى self._live)
    col3 = value_next
    col4 = caption_next

أي أنّ value_current و value_next متجاوران لا يفصلهما سوى عمود السهم (الأسعار
"تتقابل"). صفّ TP مباشرةً فوق صفّ SL. خانتا قيمة TP خضراوان بنص أبيض Bold،
وخانتا قيمة SL حمراوان بنص أبيض Bold.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest

from ocobot.ui._qt import QFrame, QLabel, QGridLayout, QApplication
from ocobot.ui.theme import apply_theme, PALETTE
from ocobot.ui.monitoring import DynamicMonitoringScreen
from tests.test_ui_monitoring import _sample


class TestG122LivePanelFacingPrices(unittest.TestCase):
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

    def _pos_caption(self, screen, grid, key):
        cap = screen.findChild(QLabel, "MonitoringLiveCaption_%s" % key)
        self.assertIsNotNone(cap, "caption not found for %s" % key)
        return grid.getItemPosition(grid.indexOf(cap))

    def _pos_value(self, screen, grid, key):
        val = screen._live.get(key)
        self.assertIsNotNone(val, "value not found for %s" % key)
        return grid.getItemPosition(grid.indexOf(val))

    def _arrow(self, screen, pair):
        return screen.findChild(QLabel, "MonitoringLiveArrow_%s" % pair)

    def _assert_facing_row(self, screen, grid, pair, cur_key, next_key):
        cap_cur = self._pos_caption(screen, grid, cur_key)
        val_cur = self._pos_value(screen, grid, cur_key)
        val_next = self._pos_value(screen, grid, next_key)
        cap_next = self._pos_caption(screen, grid, next_key)

        arrow = self._arrow(screen, pair)
        self.assertIsNotNone(arrow, "arrow widget missing for %s" % pair)
        arrow_pos = grid.getItemPosition(grid.indexOf(arrow))

        row = cap_cur[0]
        # All five cells live on the same row.
        for name, p in (
            ("value_current", val_cur),
            ("arrow", arrow_pos),
            ("value_next", val_next),
            ("caption_next", cap_next),
        ):
            self.assertEqual(
                p[0], row, "%s not on the %s row (row=%d got=%d)" % (name, pair, row, p[0])
            )

        # RTL column order: caption_current(0) value_current(1) arrow(2) value_next(3) caption_next(4)
        self.assertEqual(cap_cur[1], 0, "%s caption_current must be col0" % pair)
        self.assertEqual(val_cur[1], 1, "%s value_current must be col1" % pair)
        self.assertEqual(arrow_pos[1], 2, "%s arrow must be col2" % pair)
        self.assertEqual(val_next[1], 3, "%s value_next must be col3" % pair)
        self.assertEqual(cap_next[1], 4, "%s caption_next must be col4" % pair)

        # Facing prices: value_current and value_next separated ONLY by the arrow col.
        self.assertEqual(
            val_next[1] - val_cur[1], 2,
            "%s value cells are not separated by exactly one (arrow) column" % pair,
        )
        self.assertEqual(
            arrow_pos[1], val_cur[1] + 1,
            "%s arrow is not directly between the two value cells" % pair,
        )
        return row

    def test_tp_row_facing_prices_with_arrow(self):
        screen = self._build_screen()
        grid = self._grid(screen)
        self._assert_facing_row(screen, grid, "tp", "current_tp", "next_tp")

    def test_sl_row_facing_prices_with_arrow(self):
        screen = self._build_screen()
        grid = self._grid(screen)
        self._assert_facing_row(screen, grid, "sl", "current_sl", "next_sl")

    def test_tp_row_directly_above_sl_row(self):
        screen = self._build_screen()
        grid = self._grid(screen)
        tp_row = self._pos_value(screen, grid, "current_tp")[0]
        sl_row = self._pos_value(screen, grid, "current_sl")[0]
        self.assertEqual(
            sl_row, tp_row + 1, "SL row must be directly below the TP row"
        )

    def test_arrows_text_is_left_facing(self):
        screen = self._build_screen()
        for pair in ("tp", "sl"):
            arrow = self._arrow(screen, pair)
            self.assertIsNotNone(arrow, "arrow widget missing for %s" % pair)
            self.assertIn("←", arrow.text(), "arrow %s must contain '←'" % pair)

    def test_arrow_not_added_to_live_dict(self):
        screen = self._build_screen()
        # Arrows are standalone; the live dict stays at the 15 documented keys.
        self.assertEqual(len(screen._live), 15, "self._live must keep exactly 15 keys")
        self.assertNotIn("tp", screen._live)
        self.assertNotIn("sl", screen._live)

    def test_tp_value_cells_green_white_bold(self):
        screen = self._build_screen()
        for key in ("current_tp", "next_tp"):
            ss = screen._live[key].styleSheet()
            self.assertIn(PALETTE["GREEN"], ss, "%s missing green background" % key)
            self.assertIn(PALETTE["TEXT"], ss, "%s missing white text colour" % key)
            self.assertIn("font-weight:700", ss, "%s text must be bold" % key)
            self.assertNotIn(PALETTE["RED"], ss, "%s must not carry red" % key)

    def test_sl_value_cells_red_white_bold(self):
        screen = self._build_screen()
        for key in ("current_sl", "next_sl"):
            ss = screen._live[key].styleSheet()
            self.assertIn(PALETTE["RED"], ss, "%s missing red background" % key)
            self.assertIn(PALETTE["TEXT"], ss, "%s missing white text colour" % key)
            self.assertIn("font-weight:700", ss, "%s text must be bold" % key)
            self.assertNotIn(PALETTE["GREEN"], ss, "%s must not carry green" % key)


if __name__ == "__main__":
    unittest.main()
