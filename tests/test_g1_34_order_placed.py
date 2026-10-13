"""اختبار عيب G1.34 (offscreen، بلا شبكة).

يُثبت أنه بعد ملامسة القوس ووضع أمر جديد (نبضة REPOSITIONED):
  - حالة العرض تنتقل إلى ORDER_PLACED (لا تبقى تموضعًا/MONITORING_ACTIVE).
  - رسالة المراقبة تصير «تم التنقل من التموضع إلى أمر جديد OCO [ListId] بناءً على
    الحد [السفلي/العلوي] [القيمة] - السعر الحالي [X]»، وتختفي «أعيد التموضع إلى OCO …».
  - بانل «الأمر النشط بعد الملامسة» يظهر تحت خانات الحدود بكل الحقول ويبقى حتى ملامسة جديدة.
  - اللوحة الحيّة (جني الأرباح/وقف الخسارة الحاليّان) تعكس قيم الأمر الجديد.

يحاكي نفس بيئة test_g1_10_live_panel_rollover.py: منصّة offscreen، QApplication
وحيد، DynamicMonitoringScreen(runner=None)، وهوية SelectedOCO محدّدة. نتيجة النبضة
بديلٌ خفيف (SimpleNamespace) يقرأه الكود عبر getattr فقط.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest
from decimal import Decimal
from types import SimpleNamespace

from ocobot.ui._qt import QApplication, QLabel
from ocobot.ui.theme import apply_theme
from ocobot.ui.monitoring import DynamicMonitoringScreen
from ocobot.domain.models import SelectedOCO, SymbolFilters, fmt


def _sample():
    """هوية SelectedOCO محددة بقيم ابتدائية معروفة (مطابقة لمثال المستخدم 53524)."""
    return SelectedOCO(
        order_list_id=53524,
        symbol="BTCUSDT",
        quantity=Decimal("0.1"),
        tp=Decimal("85000.00"),
        stop_trigger=Decimal("82000.00"),
        stop_limit=Decimal("81900.00"),
        leg_ids=[11, 12],
        status="EXECUTING",
        current_price=Decimal("83610.00"),
        filters=SymbolFilters(symbol="BTCUSDT", tick_size=Decimal("0.01")),
    )


# قيم الأمر الجديد بعد الملامسة.
NEW_ID = 53525
NEW_TP = Decimal("84800.00")
NEW_STOP = Decimal("82500.00")
NEW_STOP_LIMIT = Decimal("82400.00")
NEW_QTY = Decimal("0.1")
LOWER = Decimal("83600")
UPPER = Decimal("83615")
TOUCH_PRICE = Decimal("83598.01")  # دون الحدّ السفلي ⇒ ملامسة الحد السفلي


def _repositioned_tick(price=TOUCH_PRICE):
    draft = SimpleNamespace(
        tp_price=NEW_TP,
        stop_trigger=NEW_STOP,
        stop_limit=NEW_STOP_LIMIT,
        quantity=NEW_QTY,
    )
    res = SimpleNamespace(new_order_list_id=NEW_ID, draft=draft)
    return SimpleNamespace(
        event="REPOSITIONED",
        message="أُعيد التموضع إلى OCO %s" % NEW_ID,  # الصيغة القديمة التي يجب أن تختفي
        execution_result=res,
    )


class OrderPlacedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    def _screen_with_bracket(self):
        screen = DynamicMonitoringScreen(runner=None)
        screen.show()
        screen.set_selected(_sample())
        # ضبط القوس: مفعّل، حدّ سفلي 83600 وعلوي 83615 (مثال المستخدم).
        screen._bracket_enable_toggle.setChecked(True)
        screen._bracket_lower_edit.setText(str(LOWER))
        screen._bracket_upper_edit.setText(str(UPPER))
        return screen

    def test_state_becomes_order_placed_and_new_message(self):
        screen = self._screen_with_bracket()
        screen._on_live_tick((TOUCH_PRICE, _repositioned_tick()))

        # (1) الحالة العرضية = ORDER_PLACED.
        self.assertEqual(screen._live["monitoring_state"].text(), "ORDER_PLACED")

        # (2) الرسالة الجديدة بالصيغة المطلوبة.
        msg = screen._last_operation
        self.assertIn("تم التنقل من التموضع إلى أمر جديد OCO %s" % NEW_ID, msg)
        self.assertIn("الحد السفلي", msg)
        self.assertIn(fmt(LOWER), msg)
        self.assertIn("السعر الحالي", msg)
        self.assertIn(fmt(TOUCH_PRICE), msg)
        # (3) الصيغة القديمة اختفت.
        self.assertNotIn("أعيد التموضع", msg)

    def test_active_order_panel_appears_with_fields(self):
        screen = self._screen_with_bracket()
        # قبل الملامسة: البانل مخفيّ.
        self.assertTrue(screen._active_order_card.isHidden())

        screen._on_live_tick((TOUCH_PRICE, _repositioned_tick()))

        # بعد الملامسة: البانل ظاهر بكل الحقول.
        self.assertFalse(screen._active_order_card.isHidden())
        self.assertEqual(
            screen.findChild(QLabel, "MonitoringActiveOrder_list_id").text(), str(NEW_ID)
        )
        self.assertEqual(
            screen.findChild(QLabel, "MonitoringActiveOrder_type").text(), "SELL OCO"
        )
        self.assertEqual(
            screen.findChild(QLabel, "MonitoringActiveOrder_limit").text(), fmt(NEW_TP)
        )
        self.assertEqual(
            screen.findChild(QLabel, "MonitoringActiveOrder_stop").text(), fmt(NEW_STOP)
        )
        self.assertEqual(
            screen.findChild(QLabel, "MonitoringActiveOrder_qty").text(), fmt(NEW_QTY)
        )
        self.assertIn(
            "ملامسة الحد السفلي",
            screen.findChild(QLabel, "MonitoringActiveOrder_reason").text(),
        )
        # وقت التفعيل غير فارغ.
        self.assertNotEqual(
            screen.findChild(QLabel, "MonitoringActiveOrder_time").text(), "—"
        )

    def test_live_panel_reflects_new_order_values(self):
        screen = self._screen_with_bracket()
        screen._on_live_tick((TOUCH_PRICE, _repositioned_tick()))

        # الخانات الحالية تعكس قيم الأمر الجديد لا التموضع القديم.
        self.assertEqual(screen._live["current_tp"].text(), fmt(NEW_TP))
        self.assertEqual(screen._live["current_sl"].text(), fmt(NEW_STOP))
        self.assertEqual(screen._selected.order_list_id, NEW_ID)
        self.assertIn(str(NEW_ID), screen._live["order_list_id"].text())

    def test_upper_touch_labels_upper_bound(self):
        screen = self._screen_with_bracket()
        up_price = Decimal("83616.00")  # فوق الحدّ العلوي ⇒ ملامسة الحد العلوي
        screen._on_live_tick((up_price, _repositioned_tick(up_price)))
        msg = screen._last_operation
        self.assertIn("الحد العلوي", msg)
        self.assertIn(fmt(UPPER), msg)

    def test_panel_persists_until_new_touch(self):
        screen = self._screen_with_bracket()
        screen._on_live_tick((TOUCH_PRICE, _repositioned_tick()))
        self.assertFalse(screen._active_order_card.isHidden())
        # نبضة خاملة (IDLE) لا تمسح البانل ولا الحالة العرضية.
        idle = SimpleNamespace(event="IDLE", message="بانتظار تجاوز مستوى التفعيل.",
                               execution_result=None)
        screen._on_live_tick((Decimal("83605.00"), idle))
        self.assertFalse(screen._active_order_card.isHidden())
        self.assertEqual(screen._live["monitoring_state"].text(), "ORDER_PLACED")


if __name__ == "__main__":
    unittest.main()
