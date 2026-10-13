"""G1.13 (CHUNK 2): اختبارات سلوك "تحويل-عند-البدء" في شاشة المراقبة (04).

offscreen، بلا شبكة، بلا Binance حقيقي. تغطّي الحالات الخمس:
 (1) مرشّح تحويل + نِسب صالحة ⇒ convert_cb يُستدعى بـ(source, tp, sl)، تُرقّى
     الهوية (order_list_id=999، is_convert_candidate=False)، وengine.start يبدأ
     على الهوية المُرقّاة بالمعرّف الجديد.
 (2) هوية OCO قائمة (ليست مرشّح تحويل) ⇒ convert_cb لا يُستدعى؛ engine.start كالعادة.
 (3) فشل التحويل (ABORTED/FAILED_NEEDS_ATTENTION بلا معرّف جديد) ⇒ لا engine.start،
     لا ترقية، وتُعرَض رسالة الفشل في آخر عملية.
 (4) شاشة 02 لا تكشف أيّ زرّ ConvertToOco، وset_open_sell_orders يملأ الصفوف (شارات).
 (5) build_app يستقبل convert_cb ويمرّره فتصل شاشة 04 بـconvert_cb غير None.

كلها فيكات خفيفة ومعزولة وحتميّة (runner=None فيتزامن كل شيء).
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest
from decimal import Decimal

from ocobot.ui._qt import QWidget, QApplication
from ocobot.ui.theme import apply_theme
from ocobot.ui.monitoring import DynamicMonitoringScreen
from ocobot.ui.open_orders import OpenOrdersScreen
from ocobot.ui.app import build_app
from ocobot.domain.models import SelectedOCO, OpenSellOrder, SymbolFilters
from ocobot.domain.reposition import ExecutionState
from tests._fakes_monitoring import make_draft, make_result


# --------------------------- فيكات خفيفة ---------------------------
class FakeEngine:
    """محرّك وهمي يسجّل start() مع الهوية المُمرَّرة (مرجعها لحظة الاستدعاء)."""

    def __init__(self):
        self.start_calls = []
        self.state = None  # شاشة المراقبة تقرأ engine.state عبر getattr الآمن

    def start(self, selected_oco, trigger_pct, tp_pct, sl_pct, reference_price,
              *args, **kwargs):
        self.start_calls.append({
            "selected": selected_oco,
            "order_list_id": getattr(selected_oco, "order_list_id", None),
            "is_convert_candidate": getattr(selected_oco, "is_convert_candidate", None),
            "trigger_pct": trigger_pct,
            "tp_pct": tp_pct,
            "sl_pct": sl_pct,
            "reference_price": reference_price,
        })
        return None


class FakeConvertCb:
    """convert_cb وهمي: يسجّل الاستدعاء ويُرجع نتيجة مُهيّأة مسبقًا."""

    def __init__(self, result):
        self._result = result
        self.calls = []

    def __call__(self, source, tp_pct, sl_pct, reference_price=None, dry_run=False):
        self.calls.append({
            "source": source, "tp_pct": tp_pct, "sl_pct": sl_pct,
            "reference_price": reference_price, "dry_run": dry_run,
        })
        return self._result


def _standalone_order():
    """أمر بيع مستقل غير OCO (يصلح مصدرًا للتحويل)."""
    return OpenSellOrder(
        symbol="BTCUSDT", orderId=777, orderListId=-1, order_type="LIMIT",
        side="SELL", price="100", stopPrice="0", trailingDelta="",
        origQty="1", executedQty="0", status="NEW", time=1,
        is_oco=False, oco_group_id=None, badge="LIMIT",
    )


def _candidate_selection():
    """SelectedOCO مرشّح تحويل يحمل الأمر المصدر الكامل (source_order)."""
    order = _standalone_order()
    return SelectedOCO.from_open_sell_order(
        order, filters=SymbolFilters(symbol="BTCUSDT", tick_size=Decimal("0.01"))
    )


def _oco_selection():
    """SelectedOCO OCO قائم (ليس مرشّح تحويل)."""
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


class ConvertOnStartG113Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    def _screen(self, engine, convert_cb):
        screen = DynamicMonitoringScreen(
            engine=engine,
            price_provider=lambda: Decimal("60000.00"),
            runner=None,
            convert_cb=convert_cb,
        )
        screen._enable_toggle.setChecked(True)
        screen._pct_edits["trigger_pct"].setText("1")
        screen._pct_edits["tp_pct"].setText("4")
        screen._pct_edits["sl_pct"].setText("2")
        return screen

    # (1) مرشّح + نِسب صالحة ⇒ تحويل ناجح ⇒ ترقية ⇒ بدء على المعرّف الجديد.
    def test_candidate_converts_then_promotes_and_starts(self):
        engine = FakeEngine()
        # النتيجة الناجحة تحمل draft بـ reference_price = السعر الحيّ الذي استعمله
        # التحويل (D14) — هكذا يختبر هذا السيناريو ضمانة الإنتاج التي تبذر المرجع
        # من result.draft.reference_price حين لا يصل سعر حيّ للشاشة بعد (لا شبكة).
        result = make_result(
            ExecutionState.SUCCESS,
            new_order_list_id=999,
            draft=make_draft(Decimal("60000.00")),
        )
        cb = FakeConvertCb(result)
        screen = self._screen(engine, cb)
        selected = _candidate_selection()
        source = selected.source_order
        screen.set_selected(selected)
        # الشاشة بلا سعر حيّ بعد (كما في المشغّل الحقيقي قبل أول نبضة): نتحقّق أن
        # البدء مع ذلك ينجح باستعمال مرجع التحويل.
        self.assertIsNone(screen._current_price)

        screen._on_start_clicked()

        # convert_cb استُدعي مرة واحدة بـ(source_order, tp_pct, sl_pct).
        self.assertEqual(len(cb.calls), 1)
        self.assertIs(cb.calls[0]["source"], source)
        self.assertEqual(cb.calls[0]["tp_pct"], "4")
        self.assertEqual(cb.calls[0]["sl_pct"], "2")
        # الهوية رُقّيت في المكان.
        self.assertEqual(selected.order_list_id, 999)
        self.assertFalse(selected.is_convert_candidate)
        # engine.start بدأ على الهوية المُرقّاة بالمعرّف الجديد.
        self.assertEqual(len(engine.start_calls), 1)
        self.assertIs(engine.start_calls[0]["selected"], selected)
        self.assertEqual(engine.start_calls[0]["order_list_id"], 999)
        self.assertFalse(engine.start_calls[0]["is_convert_candidate"])
        # البدء استعمل السعر الحيّ المرجعي من نتيجة التحويل (لا None، لا شبكة).
        self.assertEqual(
            engine.start_calls[0]["reference_price"], Decimal("60000.00")
        )
        self.assertEqual(screen._current_price, Decimal("60000.00"))

    # (2) OCO قائم ⇒ لا تحويل ⇒ بدء كالعادة.
    def test_existing_oco_skips_convert_and_starts(self):
        engine = FakeEngine()
        cb = FakeConvertCb(make_result(ExecutionState.SUCCESS, new_order_list_id=999))
        screen = self._screen(engine, cb)
        selected = _oco_selection()
        screen.set_selected(selected)

        screen._on_start_clicked()

        # convert_cb لم يُستدعَ إطلاقًا.
        self.assertEqual(cb.calls, [])
        # engine.start بدأ على نفس هوية الـ OCO القائمة (31).
        self.assertEqual(len(engine.start_calls), 1)
        self.assertEqual(engine.start_calls[0]["order_list_id"], 31)

    # (3) فشل التحويل ⇒ لا بدء، لا ترقية، تُعرَض رسالة الفشل.
    def test_convert_failure_blocks_start_and_promotion(self):
        engine = FakeEngine()
        result = make_result(
            ExecutionState.FAILED_NEEDS_ATTENTION,
            new_order_list_id=None,
            reason="CREATE_FAILED_AFTER_CANCEL",
        )
        cb = FakeConvertCb(result)
        screen = self._screen(engine, cb)
        selected = _candidate_selection()
        screen.set_selected(selected)

        screen._on_start_clicked()

        # convert_cb استُدعي، لكن لا بدء ولا ترقية.
        self.assertEqual(len(cb.calls), 1)
        self.assertEqual(engine.start_calls, [])
        self.assertTrue(selected.is_convert_candidate)
        self.assertIsNone(selected.order_list_id)
        # رسالة الفشل ظهرت في اللوحة الحيّة (آخر عملية).
        last_op = screen._live["last_operation"].text()
        self.assertIn("CREATE_FAILED_AFTER_CANCEL", last_op)

    # (3-b) ABORTED بلا معرّف جديد ⇒ نفس المنع.
    def test_convert_aborted_blocks_start(self):
        engine = FakeEngine()
        result = make_result(
            ExecutionState.ABORTED, new_order_list_id=None, reason="GATE_FAILED",
        )
        cb = FakeConvertCb(result)
        screen = self._screen(engine, cb)
        selected = _candidate_selection()
        screen.set_selected(selected)

        screen._on_start_clicked()

        self.assertEqual(engine.start_calls, [])
        self.assertTrue(selected.is_convert_candidate)

    # (4) شاشة 02 لا تكشف ConvertToOco، وset_open_sell_orders يملأ الصفوف.
    def test_screen_02_no_convert_button_and_renders_rows(self):
        screen = OpenOrdersScreen()
        # لا زرّ/عنصر باسم ConvertToOco.
        self.assertIsNone(screen.findChild(QWidget, "ConvertToOco"))
        self.assertFalse(hasattr(screen, "convert_button"))
        # set_open_sell_orders يملأ صفًّا واحدًا بشارة نوعه.
        screen.set_open_sell_orders([_standalone_order()])
        self.assertEqual(screen.table.rowCount(), 1)
        self.assertEqual(screen.badge_for_row(0), "LIMIT")

    # (5) build_app يستقبل convert_cb ويمرّره فتصل شاشة 04 بـconvert_cb غير None.
    def test_build_app_forwards_convert_cb_to_monitoring(self):
        cb = FakeConvertCb(make_result(ExecutionState.SUCCESS, new_order_list_id=1))
        _app, window = build_app(convert_cb=cb)
        mon = window.content.screen_for("04_dynamic_monitoring")
        self.assertIsInstance(mon, DynamicMonitoringScreen)
        self.assertIsNotNone(mon._convert_cb)
        self.assertIs(mon._convert_cb, cb)


if __name__ == "__main__":
    unittest.main()
