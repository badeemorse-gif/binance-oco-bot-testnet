"""اختبار عيب G1.10 (offscreen، بلا شبكة).

يُثبت أنه بعد نبضة إعادة تموضع ناجحة (REPOSITIONED)، تُدحرَج الخانات الثلاث
في اللوحة الحيّة لشاشة المراقبة الديناميكية إلى قيم الـ OCO الجديد:
  - self._live["order_list_id"]  → المعرّف الجديد.
  - self._live["current_tp"]     → جني الأرباح الجديد.
  - self._live["current_sl"]     → وقف الخسارة الجديد (stop_trigger).

يحاكي البيئة نفسها التي يستخدمها test_ui_monitoring.py: منصّة offscreen،
QApplication وحيد، DynamicMonitoringScreen(runner=None)، وهوية SelectedOCO
محدّدة. نتيجة النبضة بديلٌ خفيف (SimpleNamespace) لأن الكود المُعدَّل يقرأ عبر
getattr فقط على tick.event/tick.execution_result وعلى
res.new_order_list_id/res.draft.tp_price/.stop_trigger/.stop_limit.
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


def _sample():
    """هوية SelectedOCO محددة بقيم ابتدائية معروفة (نفس نمط الاختبار القائم)."""
    return SelectedOCO(
        order_list_id=31,
        symbol="BTCUSDT",
        quantity=Decimal("0.5"),
        tp=Decimal("70000.00"),
        stop_trigger=Decimal("58500.00"),
        stop_limit=Decimal("58000.00"),
        leg_ids=[11, 12],
        status="EXECUTING",
        current_price=Decimal("60000.00"),
        filters=SymbolFilters(symbol="BTCUSDT", tick_size=Decimal("0.01")),
    )


class LivePanelRolloverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    def test_repositioned_tick_rolls_over_three_live_fields(self):
        # (1) بناء الشاشة كما في اختبار الواجهة القائم (بلا رَنَر → متزامن).
        screen = DynamicMonitoringScreen(runner=None)
        screen.show()

        # (2) ضبط OCO مختار بقيم ابتدائية معروفة وتحديث اللوحة.
        screen.set_selected(_sample())
        initial_id_text = screen._live["order_list_id"].text()
        initial_tp_text = screen._live["current_tp"].text()
        initial_sl_text = screen._live["current_sl"].text()
        # تحقّق مبدئي: الخانات تعرض القيم الابتدائية.
        self.assertEqual(initial_id_text, "31")
        self.assertEqual(initial_tp_text, fmt(Decimal("70000.00")))
        self.assertEqual(initial_sl_text, fmt(Decimal("58500.00")))

        # (3) نبضة إعادة تموضع ناجحة كبديل خفيف — قيم جديدة تختلف بوضوح.
        NEW_ID = 4242
        new_tp = Decimal("72500.00")
        new_sl_trigger = Decimal("60500.00")
        new_sl_limit = Decimal("60000.00")
        draft = SimpleNamespace(
            tp_price=new_tp,
            stop_trigger=new_sl_trigger,
            stop_limit=new_sl_limit,
        )
        res = SimpleNamespace(new_order_list_id=NEW_ID, draft=draft)
        tick = SimpleNamespace(
            event="REPOSITIONED",
            message="أُعيد التموضع إلى OCO %s" % NEW_ID,
            execution_result=res,
        )

        # (4) تغذية النبضة على خيط الواجهة (كما يفعل الرَنَر).
        screen._on_live_tick((Decimal("61000.00"), tick))

        # (5) تأكيد الدحرجة إلى قيم الـ OCO الجديد.
        self.assertEqual(screen._selected.order_list_id, NEW_ID)
        self.assertEqual(screen._selected.tp, new_tp)
        self.assertEqual(screen._selected.stop_trigger, new_sl_trigger)
        self.assertEqual(screen._selected.stop_limit, new_sl_limit)

        # الخانة تعرض المعرّف الجديد.
        self.assertIn(str(NEW_ID), screen._live["order_list_id"].text())

        # نصوص TP/SL تغيّرت عن الابتدائية وتعكس القيم الجديدة المنسّقة.
        new_tp_text = screen._live["current_tp"].text()
        new_sl_text = screen._live["current_sl"].text()
        self.assertNotEqual(new_tp_text, initial_tp_text)
        self.assertNotEqual(new_sl_text, initial_sl_text)
        self.assertEqual(new_tp_text, fmt(new_tp))
        self.assertEqual(new_sl_text, fmt(new_sl_trigger))


if __name__ == "__main__":
    unittest.main()
