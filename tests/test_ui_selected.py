import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest

from ocobot.ui._qt import QApplication
from ocobot.ui.theme import apply_theme
from ocobot.ui.selected_oco import SelectedOcoScreen, NO_SELECTION_NOTE, EMPTY
from ocobot.ui.content import ContentRouter
from ocobot.ui.main_window import MainWindow
from ocobot.ui.open_orders import OpenOrdersScreen
from ocobot.domain.selection import Selector
from ocobot.domain.oco_reader import OcoReader
from ocobot.domain.exchange_info import ExchangeInfoService
from ocobot.domain.models import fmt
from tests._fakes import FakeClient


def _selected():
    """هوية OCO محددة حقيقية عبر Selector (بلا شبكة، عبر الفيك)."""
    return Selector(
        OcoReader(FakeClient()),
        ExchangeInfoService(FakeClient(), monotonic=lambda: 1.0),
    ).select(31)


class SelectedOcoScreenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    # --- acceptance: مسجّلة في content.py لمفتاح 03_selected_and_edit ------

    def test_registered_in_content_router(self):
        router = ContentRouter()
        page = router.screen_for("03_selected_and_edit")
        self.assertIsInstance(page, SelectedOcoScreen)
        self.assertTrue(router.show_screen("03_selected_and_edit"))
        self.assertEqual(router.current_key(), "03_selected_and_edit")

    def test_initial_state_shows_no_selection_note(self):
        screen = SelectedOcoScreen()
        screen.show()
        self.assertTrue(screen._note.isVisible())
        self.assertEqual(screen._note.text(), NO_SELECTION_NOTE)
        for value in screen._fields.values():
            self.assertEqual(value.text(), EMPTY)

    # --- عرض الهوية الكاملة عبر SelectedOCO (قيم فعلية من الفيك) ----------

    def test_set_selected_renders_full_identity(self):
        selected = _selected()
        screen = SelectedOcoScreen()
        screen.set_selected(selected)
        self.assertEqual(screen._fields["orderListId"].text(), "31")
        self.assertEqual(screen._fields["symbol"].text(), "BTCUSDT")
        self.assertEqual(screen._fields["quantity"].text(), fmt(selected.quantity))
        self.assertEqual(screen._fields["tp"].text(), fmt(selected.tp))
        self.assertEqual(
            screen._fields["stopTrigger"].text(), fmt(selected.stop_trigger)
        )
        self.assertEqual(
            screen._fields["stopLimit"].text(), fmt(selected.stop_limit)
        )
        self.assertEqual(screen._fields["legIds"].text(), "11 / 12")
        self.assertEqual(screen._fields["status"].text(), "EXECUTING")

    # --- D7: قفل الكمية معروض ---------------------------------------------

    def test_quantity_lock_shown_D7(self):
        screen = SelectedOcoScreen()
        screen.show()
        screen.set_selected(_selected())
        self.assertTrue(screen._lock.isVisible())
        self.assertIn("مقفولة", screen._lock.text())

    def test_clear_resets_to_note(self):
        screen = SelectedOcoScreen()
        screen.show()
        screen.set_selected(_selected())
        screen.clear()
        for value in screen._fields.values():
            self.assertEqual(value.text(), EMPTY)
        self.assertTrue(screen._note.isVisible())

    def test_refresh_synchronous_without_runner(self):
        selected = _selected()
        screen = SelectedOcoScreen()
        screen.refresh(build_fn=lambda: selected)
        self.assertEqual(screen._fields["symbol"].text(), "BTCUSDT")

    # --- acceptance: الاختيار يُبلّغ orderListId (P1) ----------------------

    def test_open_orders_selection_emits_order_id(self):
        captured = []
        scr = OpenOrdersScreen(on_select=captured.append)
        scr.set_orders(OcoReader(FakeClient()).list_open_ocos())
        scr.select_row(0)
        self.assertTrue(captured)
        self.assertEqual(captured[-1], 31)

    # --- acceptance: الاختيار يؤسّس السياق الحيّ ويعرض الهوية ---------------

    def test_selection_establishes_live_context_and_displays(self):
        class _SyncRunner:
            def submit(self, fn, *a, on_result=None, on_error=None, **k):
                r = fn(*a, **k)
                if on_result:
                    on_result(r)
                return r

        selector = Selector(
            OcoReader(FakeClient()),
            ExchangeInfoService(FakeClient(), monotonic=lambda: 1.0),
        )
        mw = MainWindow(runner=_SyncRunner(), select_fn=selector.select)
        oo = mw.content.screen_for("02_open_orders")
        oo.set_orders(OcoReader(FakeClient()).list_open_ocos())
        oo.select_row(0)
        sel = mw.content.screen_for("03_selected_and_edit")
        self.assertEqual(sel._fields["orderListId"].text(), "31")
        self.assertEqual(sel._fields["symbol"].text(), "BTCUSDT")
        self.assertEqual(mw.content.current_key(), "03_selected_and_edit")

    # --- G1.3: التحديد يُبلَّغ للمراقبة الديناميكية (04) ولوحة القيادة (01) ---

    def test_selection_propagates_to_monitoring_and_dashboard(self):
        class _SyncRunner:
            def submit(self, fn, *a, on_result=None, on_error=None, **k):
                r = fn(*a, **k)
                if on_result:
                    on_result(r)
                return r

        selector = Selector(
            OcoReader(FakeClient()),
            ExchangeInfoService(FakeClient(), monotonic=lambda: 1.0),
        )
        mw = MainWindow(runner=_SyncRunner(), select_fn=selector.select)
        oo = mw.content.screen_for("02_open_orders")
        oo.set_orders(OcoReader(FakeClient()).list_open_ocos())
        oo.select_row(0)

        mon = mw.content.screen_for("04_dynamic_monitoring")
        self.assertIsNotNone(mon._selected)
        self.assertEqual(mon._selected.order_list_id, 31)

        dash = mw.content.screen_for("01_dashboard")
        # لوحة القيادة تعكس الاختيار: بطاقة selected_oco تُظهر "31" والملاحظة تُفرَّغ.
        self.assertEqual(dash._cards["selected_oco"].value.text(), "31")
        self.assertEqual(dash.note.text(), "")


if __name__ == "__main__":
    unittest.main()
