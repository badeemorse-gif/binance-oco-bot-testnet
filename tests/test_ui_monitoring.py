"""اختبارات شاشة المراقبة الديناميكية (T13.s4) — offscreen، بلا شبكة.

تغطّي الفحوص الأربعة للعقد (WORKING_MEMORY.json / acceptance_checks):
  (أ) Kill Switch يوقف كل المراقبة دون إلغاء أي أمر على Binance (cancel_calls == []).
  (ب) Pause يُبقي OCO الحقيقي كما هو (لا cancel/create؛ لا يمسّ الأمر).
  (ج) كل حقول "لا تختفي أثناء المراقبة" ظاهرة (اللوحة الحيّة الكاملة).
  (د) السعر الحيّ من مصدر حيّ محقون (WS مع سقوط REST) لا Preview ثابت.

كلها offscreen ونقيّة: MonitoringEngine حقيقي يفوّض إلى FakeSafeExecutor
(cancel_calls يبقى [] لأن المحرّك لا يلغي مباشرة)، والسعر عبر FakePriceSource/
PriceFeedController محقونين (بلا socket/urllib). runner=None يجعل جلب السعر
متزامنًا. تحترم حارس tests/test_ui_no_direct_network (لا شبكة في طبقة الواجهة).
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest
from decimal import Decimal

from ocobot.ui._qt import QApplication
from ocobot.ui.theme import apply_theme
from ocobot.ui.monitoring import (
    DynamicMonitoringScreen,
    LIVE_FIELDS,
    EMPTY,
)
from ocobot.ui.content import ContentRouter
from ocobot.ui.main_window import MainWindow
from ocobot.domain.models import SelectedOCO, SymbolFilters, fmt
from ocobot.domain.monitoring import (
    MonitoringEngine,
    MonitoringStateEnum,
    MSG_KILL_SWITCH,
)
from ocobot.core.market_feed import PriceFeedController
from tests._fakes_monitoring import FakeSafeExecutor, FakePriceSource


def _sample(current_price=None, tick_size=Decimal("0.01")):
    """هوية SelectedOCO محددة (بلا شبكة) بفلاتر tick + سعر مرجعي اختياري."""
    return SelectedOCO(
        order_list_id=31,
        symbol="BTCUSDT",
        quantity=Decimal("0.5"),
        tp=Decimal("70000.00"),
        stop_trigger=Decimal("58500.00"),
        stop_limit=Decimal("58000.00"),
        leg_ids=[11, 12],
        status="EXECUTING",
        current_price=current_price,
        filters=SymbolFilters(symbol="BTCUSDT", tick_size=tick_size),
    )


class DynamicMonitoringScreenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    # --- acceptance: مسجّلة في content.py لمفتاح 04_dynamic_monitoring ------
    def test_registered_in_content_router(self):
        router = ContentRouter()
        page = router.screen_for("04_dynamic_monitoring")
        self.assertIsInstance(page, DynamicMonitoringScreen)
        self.assertTrue(router.show_screen("04_dynamic_monitoring"))
        self.assertEqual(router.current_key(), "04_dynamic_monitoring")

    # --- acceptance #3: كل حقول "لا تختفي أثناء المراقبة" ظاهرة ------------
    def test_all_never_hide_fields_present(self):
        screen = DynamicMonitoringScreen(runner=None)
        screen.show()
        # كل الحقول المعرّفة في LIVE_FIELDS مبنيّة وظاهرة (لا تختفي).
        for key, _label in LIVE_FIELDS:
            self.assertIn(key, screen._live, "حقل مفقود: %s" % key)
            self.assertTrue(
                screen._live[key].isVisible(),
                "حقل غير ظاهر: %s" % key,
            )
        # ملموس: الحقول الأساسية موجودة بالاسم.
        for expected in (
            "symbol", "order_list_id", "current_price", "reference_price",
            "trigger_price", "current_tp", "current_sl", "next_tp", "next_sl",
            "sl_limit", "tick_size", "monitoring_state", "last_operation",
            "connection", "environment",
        ):
            self.assertIn(expected, screen._live)

    def test_never_hide_fields_stay_visible_during_monitoring(self):
        fake = FakeSafeExecutor()
        engine = MonitoringEngine(fake)
        screen = DynamicMonitoringScreen(
            engine=engine, price_provider=lambda: Decimal("60000.00"), runner=None
        )
        screen.show()
        screen.set_selected(_sample(current_price=Decimal("60000.00")))
        screen._enable_toggle.setChecked(True)
        screen._pct_edits["trigger_pct"].setText("1")
        screen._pct_edits["tp_pct"].setText("4")
        screen._pct_edits["sl_pct"].setText("2")
        screen._on_start_clicked()
        # أثناء المراقبة النشطة تبقى كل الحقول ظاهرة.
        self.assertEqual(
            engine.state.state, MonitoringStateEnum.MONITORING_ACTIVE
        )
        for key, _label in LIVE_FIELDS:
            self.assertTrue(screen._live[key].isVisible(), key)

    # --- acceptance #1: Kill Switch يوقف المراقبة بلا أي إلغاء أمر ---------
    def test_kill_switch_stops_monitoring_without_cancel(self):
        fake = FakeSafeExecutor()
        engine = MonitoringEngine(fake)
        screen = DynamicMonitoringScreen(
            engine=engine, price_provider=lambda: Decimal("60000.00"), runner=None
        )
        screen.set_selected(_sample(current_price=Decimal("60000.00")))
        screen._enable_toggle.setChecked(True)
        screen._pct_edits["trigger_pct"].setText("1")
        screen._pct_edits["tp_pct"].setText("4")
        screen._pct_edits["sl_pct"].setText("2")
        screen._on_start_clicked()
        self.assertEqual(engine.state.state, MonitoringStateEnum.MONITORING_ACTIVE)
        # Kill Switch.
        screen._on_kill_switch_clicked()
        # المراقبة توقّفت.
        self.assertEqual(engine.state.state, MonitoringStateEnum.MONITORING_STOPPED)
        self.assertFalse(engine.state.enabled)
        # لم يُلغَ أي أمر على Binance: المحرّك لا يستدعي أي cancel إطلاقًا.
        self.assertEqual(fake.cancel_calls, [])
        self.assertEqual(fake.calls, [])
        # الرسالة تطابق نص التصميم حرفيًا.
        self.assertIn(MSG_KILL_SWITCH, screen._live["last_operation"].text())

    # --- acceptance #2: Pause يُبقي OCO الحقيقي كما هو --------------------
    def test_pause_keeps_real_oco_intact(self):
        fake = FakeSafeExecutor()
        engine = MonitoringEngine(fake)
        screen = DynamicMonitoringScreen(
            engine=engine, price_provider=lambda: Decimal("60000.00"), runner=None
        )
        selected = _sample(current_price=Decimal("60000.00"))
        screen.set_selected(selected)
        screen._enable_toggle.setChecked(True)
        screen._pct_edits["trigger_pct"].setText("1")
        screen._pct_edits["tp_pct"].setText("4")
        screen._pct_edits["sl_pct"].setText("2")
        screen._on_start_clicked()
        target_before = engine.state.target_order_list_id
        # Pause.
        screen._on_pause_resume_clicked()
        self.assertEqual(engine.state.state, MonitoringStateEnum.PAUSED)
        # لا تنفيذ ولا إلغاء ولا مسّ للأمر الحقيقي.
        self.assertEqual(fake.calls, [])
        self.assertEqual(fake.cancel_calls, [])
        self.assertEqual(engine.state.target_order_list_id, target_before)
        # الزر صار Resume، والحالة المعروضة PAUSED.
        self.assertEqual(screen.pause_resume_button.text(), "استئناف")
        self.assertEqual(screen._live["monitoring_state"].text(), "PAUSED")
        # Resume يعيد التفعيل دون مسّ الأمر أيضًا.
        screen._on_pause_resume_clicked()
        self.assertEqual(engine.state.state, MonitoringStateEnum.MONITORING_ACTIVE)
        self.assertEqual(fake.cancel_calls, [])

    # --- acceptance #4: السعر الحيّ من مصدر حيّ محقون لا Preview ثابت -----
    def test_live_price_from_injected_provider_not_static(self):
        # PriceFeedController حقيقي بمصدر WS وهمي (بلا شبكة) — يعكس WS+REST fallback.
        ws = FakePriceSource(prices=[Decimal("60123.45")])
        rest = FakePriceSource(prices=[Decimal("60000.00")])
        controller = PriceFeedController(ws_source=ws, rest_source=rest, symbol="BTCUSDT")
        screen = DynamicMonitoringScreen(
            engine=None, price_provider=controller.get_price, runner=None
        )
        screen.set_selected(_sample())
        # قبل أي جلب: لا سعر ثابت موهِم — القيمة '—' (D14).
        self.assertEqual(screen._live["current_price"].text(), EMPTY)
        # جلب السعر عبر المزوّد الحيّ المحقون.
        screen.refresh_price()
        self.assertEqual(screen._live["current_price"].text(), fmt(Decimal("60123.45")))
        self.assertEqual(controller.mode, "WS")
        # سقوط REST: عند فشل WS يُستخدم REST مع تنبيه (لا Preview ثابت).
        ws.raise_error = True
        screen.refresh_price()
        self.assertEqual(screen._live["current_price"].text(), fmt(Decimal("60000.00")))
        self.assertEqual(controller.mode, "REST")

    def test_no_static_preview_before_price_D14(self):
        screen = DynamicMonitoringScreen(runner=None)
        screen.set_selected(_sample(current_price=None))
        # بلا سعر حيّ: current_price يبقى '—' والمستويات التالية '—' (لا Preview).
        self.assertEqual(screen._live["current_price"].text(), EMPTY)
        self.assertEqual(screen._live["next_tp"].text(), EMPTY)
        self.assertEqual(screen._live["next_sl"].text(), EMPTY)

    # --- التكامل عبر MainWindow: حقن engine + price_provider --------------
    def test_main_window_forwards_engine_and_price(self):
        fake = FakeSafeExecutor()
        engine = MonitoringEngine(fake)
        provider = lambda: Decimal("60000.00")
        win = MainWindow(engine=engine, price_provider=provider)
        scr = win.content.screen_for("04_dynamic_monitoring")
        self.assertIsInstance(scr, DynamicMonitoringScreen)
        self.assertIs(scr._engine, engine)
        self.assertIs(scr._price_provider, provider)

    def test_main_window_backward_compatible_defaults(self):
        win = MainWindow()  # بلا engine/price — يجب أن يبقى سليمًا (defaults=None)
        scr = win.content.screen_for("04_dynamic_monitoring")
        self.assertIsInstance(scr, DynamicMonitoringScreen)
        self.assertIsNone(scr._engine)
        self.assertIsNone(scr._price_provider)


if __name__ == "__main__":
    unittest.main()
