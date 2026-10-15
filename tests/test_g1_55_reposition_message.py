"""G1.55 — تصحيح نسبة رسالة إعادة التموضع (offscreen، بلا شبكة).

يُثبت:
  - REPOSITIONED بلا عبور حدّ (السعر بين الحدّين) ⇒ الرسالة لا تُنسب لحدّ القوس،
    وتُظهر وصف «ارتفاع السعر (مُشغّل التموضع)» + السعر الحالي (مثال المستخدم 104.72).
  - عبور علوي/سفلي فعلي ⇒ تُنسب للحدّ الصحيح (سلوك G1.34 محفوظ، بلا انحدار).
  - عزل: رسالة تليجرام repositioned في alerts.formatting غير متأثّرة بتسمية الواجهة.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest
from decimal import Decimal
from types import SimpleNamespace

from ocobot.ui._qt import QApplication
from ocobot.ui.theme import apply_theme
from ocobot.ui.monitoring import DynamicMonitoringScreen
from ocobot.domain.models import SelectedOCO, SymbolFilters, fmt


LOWER = Decimal("103")
UPPER = Decimal("105.5")
BETWEEN = Decimal("104.72")   # مثال المستخدم: بين الحدّين ⇒ لا عبور
NEW_ID = 60001


def _sample():
    return SelectedOCO(
        order_list_id=59000,
        symbol="BTCUSDT",
        quantity=Decimal("0.1"),
        tp=Decimal("110.00"),
        stop_trigger=Decimal("100.00"),
        stop_limit=Decimal("99.90"),
        leg_ids=[1, 2],
        status="EXECUTING",
        current_price=Decimal("104.00"),
        filters=SymbolFilters(symbol="BTCUSDT", tick_size=Decimal("0.01")),
    )


def _repositioned_tick():
    draft = SimpleNamespace(
        tp_price=Decimal("110.0"),
        stop_trigger=Decimal("100.0"),
        stop_limit=Decimal("99.9"),
        quantity=Decimal("0.1"),
    )
    res = SimpleNamespace(new_order_list_id=NEW_ID, draft=draft)
    return SimpleNamespace(
        event="REPOSITIONED",
        message="أُعيد التموضع إلى OCO %s" % NEW_ID,  # الصيغة القديمة التي يجب أن تختفي
        execution_result=res,
    )


class G1_55_RepositionMessageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    def _screen(self):
        s = DynamicMonitoringScreen(runner=None)
        s.show()
        s.set_selected(_sample())
        s._bracket_enable_toggle.setChecked(True)
        s._bracket_lower_edit.setText(str(LOWER))
        s._bracket_upper_edit.setText(str(UPPER))
        return s

    def test_bound_touched_for_between_is_none(self):
        s = self._screen()
        self.assertEqual(s._bound_touched_for(BETWEEN), (None, None))

    def test_bound_touched_for_real_crossings(self):
        s = self._screen()
        self.assertEqual(s._bound_touched_for(Decimal("105.60")), ("العلوي", UPPER))
        self.assertEqual(s._bound_touched_for(Decimal("102.50")), ("السفلي", LOWER))

    def test_between_bounds_no_fabricated_bound(self):
        s = self._screen()
        s._on_live_tick((BETWEEN, _repositioned_tick()))
        msg = s._last_operation
        self.assertIn("تم التنقل من التموضع إلى أمر جديد OCO %s" % NEW_ID, msg)
        self.assertIn("ارتفاع السعر (مُشغّل التموضع)", msg)
        self.assertNotIn("الحد العلوي", msg)
        self.assertNotIn("الحد السفلي", msg)
        self.assertNotIn(fmt(UPPER), msg)   # لا يُذكر 105.5 كحدٍّ مَلموس
        self.assertIn(fmt(BETWEEN), msg)    # السعر الحالي الحقيقي يظهر
        self.assertNotIn("أعيد التموضع", msg)

    def test_genuine_upper_cross_still_labeled(self):
        s = self._screen()
        s._on_live_tick((Decimal("105.60"), _repositioned_tick()))
        msg = s._last_operation
        self.assertIn("الحد العلوي", msg)
        self.assertIn(fmt(UPPER), msg)

    def test_genuine_lower_cross_still_labeled(self):
        s = self._screen()
        s._on_live_tick((Decimal("102.50"), _repositioned_tick()))
        msg = s._last_operation
        self.assertIn("الحد السفلي", msg)
        self.assertIn(fmt(LOWER), msg)

    def test_active_order_reason_between_bounds(self):
        s = self._screen()
        s._on_live_tick((BETWEEN, _repositioned_tick()))
        self.assertEqual(s._active_order.get("reason"), "ارتفاع السعر (مُشغّل التموضع)")
        self.assertIsNone(s._active_order.get("bound_label"))

    def test_alerts_reposition_message_isolated(self):
        # عزل فرع التنبيهات: رسالة تليجرام repositioned لا تتأثّر بتسمية الواجهة الجديدة.
        from ocobot.alerts.formatting import build_reposition_message
        rec = {
            "event": "repositioned",
            "details": {
                "symbol": "BTCUSDT",
                "new_order_list_id": NEW_ID,
                "reference_price": "100",
                "tp_pct": "4",
                "sl_pct": "2",
            },
        }
        out = build_reposition_message(rec)
        self.assertIn("🔁", out)
        self.assertNotIn("ارتفاع السعر (مُشغّل التموضع)", out)


if __name__ == "__main__":
    unittest.main()
