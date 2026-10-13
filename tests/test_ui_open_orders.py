import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest
from decimal import Decimal

from ocobot.ui._qt import Qt, QApplication
from ocobot.ui.theme import apply_theme
from ocobot.ui.open_orders import (
    OpenOrdersScreen,
    COLUMN_HEADERS,
    ROW_KEYS,
    QTY_COLUMN,
    EMPTY,
)
from ocobot.ui.content import ContentRouter
from ocobot.domain.oco_reader import OcoReader
from tests._fakes import FakeClient


# رؤوس الأعمدة الثمانية verbatim من docs/ui_mockups/02_open_orders (التصميم §3.2 B).
EXPECTED_HEADERS = [
    "#",
    "معرّف قائمة الأوامر",
    "الرمز",
    "الحالة",
    "الكمية",
    "سعر البيع / جني الأرباح",
    "مُشغِّل الإيقاف",
    "سعر الحد بعد التفعيل",
]


class OpenOrdersScreenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    # --- acceptance_check #1: الأعمدة المطلوبة كاملة وبالترتيب -------------

    def test_eight_columns_present_and_in_order(self):
        screen = OpenOrdersScreen()
        self.assertEqual(COLUMN_HEADERS, EXPECTED_HEADERS)
        self.assertEqual(screen.table.columnCount(), 8)
        self.assertEqual(screen.column_headers(), EXPECTED_HEADERS)

    def test_initial_state_is_empty(self):
        screen = OpenOrdersScreen()
        self.assertEqual(screen.table.rowCount(), 0)

    # --- تعبئة الصفوف من مخرجات oco_reader (بلا شبكة، عبر الفيك) -----------

    def test_populates_row_from_oco_reader(self):
        screen = OpenOrdersScreen()
        ocos = OcoReader(FakeClient()).list_open_ocos()
        screen.set_orders(ocos)

        self.assertEqual(screen.table.rowCount(), 1)
        # العمود "#": تسلسلي يبدأ من 1.
        self.assertEqual(screen.table.item(0, 0).text(), "1")
        row = ocos[0].to_row()
        for col, key in enumerate(ROW_KEYS, start=1):
            self.assertEqual(screen.table.item(0, col).text(), str(row[key]))
        # قيم فعلية من الفيك (BTCUSDT / EXECUTING / 3 أسعار D1).
        self.assertEqual(screen.table.item(0, 1).text(), "31")
        self.assertEqual(screen.table.item(0, 2).text(), "BTCUSDT")
        self.assertEqual(screen.table.item(0, 3).text(), "EXECUTING")

    # --- acceptance_check #2 + D7: الكمية Read-only ------------------------

    def test_qty_cell_is_read_only(self):
        screen = OpenOrdersScreen()
        screen.set_orders(OcoReader(FakeClient()).list_open_ocos())
        qty_item = screen.table.item(0, QTY_COLUMN)
        self.assertIsNotNone(qty_item)
        # ItemIsEditable يجب أن يكون مطفأً على خلية الكمية (D7).
        self.assertFalse(bool(qty_item.flags() & Qt.ItemFlag.ItemIsEditable))

    def test_all_cells_non_editable(self):
        screen = OpenOrdersScreen()
        screen.set_orders(OcoReader(FakeClient()).list_open_ocos())
        for col in range(screen.table.columnCount()):
            item = screen.table.item(0, col)
            self.assertIsNotNone(item)
            self.assertFalse(bool(item.flags() & Qt.ItemFlag.ItemIsEditable))

    def test_refresh_synchronous_without_runner(self):
        screen = OpenOrdersScreen()
        ocos = OcoReader(FakeClient()).list_open_ocos()
        screen.refresh(build_fn=lambda: ocos)
        self.assertEqual(screen.table.rowCount(), 1)
        self.assertEqual(screen.table.item(0, 2).text(), "BTCUSDT")

    def test_clear_empties_table(self):
        screen = OpenOrdersScreen()
        screen.set_orders(OcoReader(FakeClient()).list_open_ocos())
        screen.clear()
        self.assertEqual(screen.table.rowCount(), 0)

    def test_missing_values_render_placeholder(self):
        screen = OpenOrdersScreen()
        screen.set_orders([{"orderListId": 7}])
        self.assertEqual(screen.table.item(0, 2).text(), EMPTY)

    # --- acceptance: مسجّلة في content.py لمفتاح 02_open_orders ------------

    def test_registered_in_content_router(self):
        router = ContentRouter()
        page = router.screen_for("02_open_orders")
        self.assertIsInstance(page, OpenOrdersScreen)
        self.assertTrue(router.show_screen("02_open_orders"))
        self.assertEqual(router.current_key(), "02_open_orders")

    # --- G1.3: set_orders يعيد تظليل الصف المتذكَّر بعد إعادة التعبئة -------

    def test_set_orders_rehighlights_remembered_selection(self):
        ocos = OcoReader(FakeClient()).list_open_ocos()
        scr = OpenOrdersScreen()
        scr.set_orders(ocos)
        scr.select_row(0)
        remembered = scr._selected_order_id
        self.assertIsNotNone(remembered)
        scr.set_orders(ocos)  # إعادة تعبئة (كما في Refresh/User Data Stream)
        self.assertEqual(scr.selected_order_id(), remembered)

    # --- G1.15 DoD d: refresh يبتلع خطأ build_fn ويسجّله في last_error -------

    def test_refresh_handles_build_fn_error_gracefully(self):
        screen = OpenOrdersScreen()
        def boom():
            raise RuntimeError("boom")
        screen.refresh(build_fn=boom)   # must NOT raise
        self.assertEqual(screen.table.rowCount(), 0)
        self.assertIsNotNone(screen.last_error)


if __name__ == "__main__":
    unittest.main()
