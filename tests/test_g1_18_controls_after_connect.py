import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest
from decimal import Decimal
from unittest import mock

from ocobot.ui._qt import QApplication
from ocobot.ui.theme import apply_theme
from ocobot.ui.selected_oco import SelectedOcoScreen
from ocobot.ui.monitoring import DynamicMonitoringScreen
from ocobot.ui.app import make_connect_wrapper
from ocobot.core.connection_state import ConnectionStatus
from ocobot.domain.models import SelectedOCO, SymbolFilters, fmt
from ocobot.domain.monitoring import MonitoringStateEnum
from tests._fakes import FakeResult, FakeContent, FakeWindow, FakeCfg


# --------------------------------------------------------------------------- #
# أدوات التزامن/الإخطار (نفس قالب G1.17) — بلا خيوط/شبكة.                      #
# --------------------------------------------------------------------------- #
class _SyncRunner:
    """Runner منفّذ متزامنًا (كما في اختبارات الواجهة الأخرى) — بلا خيوط/شبكة."""

    def submit(self, fn, *a, on_result=None, on_error=None, **k):
        try:
            r = fn(*a, **k)
        except Exception as exc:  # pragma: no cover - دفاعي
            if on_error:
                on_error(exc)
            return None
        if on_result:
            on_result(r)
        return r


class _FakeWindowWithRunner(FakeWindow):
    """FakeWindow + runner: make_connect_wrapper يحتاج window.runner لـ set_source."""

    def __init__(self, connection_notifier, content, runner):
        super().__init__(connection_notifier, content)
        self.runner = runner


class _Notifier:
    def __init__(self):
        self.state = None

    def set_state(self, state):
        self.state = state


# --------------------------------------------------------------------------- #
# فيكات الاعتماديات التي ستُحقن داخل make_connect_wrapper (G1.18).            #
# تُبنى من أسماء module-level في ocobot.ui.app فنُرقّعها لتعيد هذه الفيكات،    #
# فلا شبكة حقيقية إطلاقًا والمتعاونون المحقونون فيكات حتميّة.                   #
# --------------------------------------------------------------------------- #
class FakeExecutor:
    """يسجّل كل استدعاء execute() (توقيع SafeExecutor الموضعي) — بلا شبكة."""

    def __init__(self):
        self.calls = []

    def execute(self, order_list_id, tp_pct, sl_pct, reference_price, dry_run=False):
        self.calls.append({
            "order_list_id": order_list_id,
            "tp_pct": tp_pct,
            "sl_pct": sl_pct,
            "reference_price": reference_price,
            "dry_run": dry_run,
        })
        # نتيجة بسيطة تحمل state=SUCCESS كي يكمل مسار النتيجة في الشاشة دون كسر.
        return mock.Mock(state="SUCCESS", new_order_list_id=999)


class FakeEngine:
    """محرّك وهمي يسجّل start/pause/resume/kill_switch (نمط test_ui_convert_on_start_g1_13)."""

    def __init__(self):
        self.start_calls = []
        self.pause_calls = 0
        self.resume_calls = 0
        self.kill_switch_calls = 0
        # شاشة المراقبة تقرأ engine.state.state عبر getattr الآمن.
        self.state = mock.Mock(state=None, enabled=False)

    def start(self, selected_oco, trigger_pct, tp_pct, sl_pct, reference_price,
              *args, **kwargs):
        self.start_calls.append({
            "selected": selected_oco,
            "order_list_id": getattr(selected_oco, "order_list_id", None),
            "trigger_pct": trigger_pct,
            "tp_pct": tp_pct,
            "sl_pct": sl_pct,
            "reference_price": reference_price,
        })
        self.state.state = MonitoringStateEnum.MONITORING_ACTIVE
        self.state.enabled = True
        return None

    def pause(self):
        self.pause_calls += 1
        self.state.state = MonitoringStateEnum.PAUSED
        return mock.Mock(message="paused")

    def resume(self):
        self.resume_calls += 1
        self.state.state = MonitoringStateEnum.MONITORING_ACTIVE
        return mock.Mock(message="resumed")

    def kill_switch(self):
        self.kill_switch_calls += 1
        self.state.state = MonitoringStateEnum.MONITORING_STOPPED
        self.state.enabled = False
        return mock.Mock(message="killed")


class FakePriceProvider:
    """مزوّد سعر حيّ وهمي — callable أو كائن له get_price. يُرجع سعرًا ثابتًا."""

    def __init__(self, price=Decimal("60000.00")):
        self._price = price

    def __call__(self):
        return self._price

    def get_price(self):
        return self._price


def _sample_selected(current_price=Decimal("60000.00")):
    """SelectedOCO OCO قائم (ليس مرشّح تحويل) مع فلاتر + سعر حيّ ابتدائي."""
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
        filters=SymbolFilters(symbol="BTCUSDT", tick_size=Decimal("0.01")),
    )


class G118ControlsAfterConnectTests(unittest.TestCase):
    """G1.18: بعد اتصال ناجح، تُعاد إعادة بناء/حقن الاعتماديات في الشاشتين 03/04
    داخل make_connect_wrapper، فتعمل الأزرار الخمسة (بدء/إيقاف مؤقت/إيقاف طارئ/
    تفعيل/أقصى إيقاف متاح) بدل الخروج المبكر عبر حُرّاس None.

    يفشل ضد الكود القديم (الذي كان يعيد الحقن لشاشة 02 فقط فتبقى 03/04 بلا
    executor/engine/price_provider ⇒ المعالجات تخرج مبكرًا) وينجح مع الإصلاح.
    """

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    def _connect(self):
        """يبني الشاشتين الحقيقيتين بلا اعتماديات ثم يقود مسار الاتصال الناجح
        الحقيقي عبر make_connect_wrapper مع ترقيع أسماء app module لحقن الفيكات.
        يُرجع (sel, mon, engine, executor, price_provider, notifier)."""
        # شاشتان حقيقيتان كما عند الإقلاع البارد: 03 بلا executor، 04 بلا engine/price.
        sel = SelectedOcoScreen(executor=None)
        mon = DynamicMonitoringScreen(engine=None, price_provider=None, runner=None)
        self.assertIsNone(sel._executor)
        self.assertIsNone(mon._engine)
        self.assertIsNone(mon._price_provider)

        notifier = _Notifier()
        runner = _SyncRunner()
        window = _FakeWindowWithRunner(
            notifier,
            FakeContent({
                "03_selected_and_edit": sel,
                "04_dynamic_monitoring": mon,
            }),
            runner,
        )
        cfg = FakeCfg()

        engine = FakeEngine()
        executor = FakeExecutor()
        price_provider = FakePriceProvider()

        # لا شبكة: نُرقّع كل الأسماء التي يبني منها بلوك G1.18 الاعتماديات.
        with mock.patch(
            "ocobot.ui.app.build_gui_client", return_value=object()
        ), mock.patch(
            "ocobot.ui.app._build_executor", return_value=executor
        ), mock.patch(
            "ocobot.ui.app.MonitoringEngine", return_value=engine
        ), mock.patch(
            "ocobot.ui.app.SelectionPriceProvider", return_value=price_provider
        ), mock.patch(
            "ocobot.ui.app.build_convert_executor", return_value=object()
        ), mock.patch(
            "ocobot.ui.app.make_convert_cb", return_value=(lambda *a, **k: None)
        ):
            wrapped = make_connect_wrapper(
                window, lambda *a, **k: FakeResult(ok=True), cfg
            )
            result = wrapped(api_key="k", api_secret="s", keys_path="")

        self.assertTrue(getattr(result, "ok", False))
        self.assertIsNotNone(notifier.state)
        self.assertEqual(notifier.state.status, ConnectionStatus.CONNECTED)
        return sel, mon, engine, executor, price_provider, notifier

    # (a) بعد الاتصال: الاعتماديات حُقنت فعليًا في الشاشتين (لا None).
    def test_post_connect_injects_dependencies(self):
        sel, mon, engine, executor, price_provider, _ = self._connect()
        self.assertIsNotNone(mon._engine)
        self.assertIsNotNone(mon._price_provider)
        self.assertIsNotNone(sel._executor)
        self.assertIs(mon._engine, engine)
        self.assertIs(mon._price_provider, price_provider)
        self.assertIs(sel._executor, executor)

    # (b) بدء: اختيار + نِسب + _on_start_clicked ⇒ engine.start استُدعي.
    def test_start_button_reaches_engine_start(self):
        _, mon, engine, _, _, _ = self._connect()
        mon.set_selected(_sample_selected())
        mon.set_current_price(Decimal("60000.00"))
        mon._pct_edits["trigger_pct"].setText("1")
        mon._pct_edits["tp_pct"].setText("4")
        mon._pct_edits["sl_pct"].setText("2")

        mon._on_start_clicked()

        self.assertTrue(engine.start_calls, "engine.start لم يُستدعَ — الحارس خرج مبكرًا")
        self.assertEqual(engine.start_calls[0]["order_list_id"], 31)
        self.assertEqual(engine.start_calls[0]["reference_price"], Decimal("60000.00"))

    # (c) إيقاف مؤقت: _on_pause_resume_clicked ⇒ engine.pause() ثم resume().
    def test_pause_resume_button_reaches_engine(self):
        _, mon, engine, _, _, _ = self._connect()
        mon.set_selected(_sample_selected())
        mon.set_current_price(Decimal("60000.00"))
        mon._pct_edits["trigger_pct"].setText("1")
        mon._pct_edits["tp_pct"].setText("4")
        mon._pct_edits["sl_pct"].setText("2")
        mon._on_start_clicked()  # ينقل الحالة إلى MONITORING_ACTIVE

        # أول ضغطة: المحرّك نشط ⇒ pause().
        mon._on_pause_resume_clicked()
        self.assertEqual(engine.pause_calls, 1, "engine.pause() لم يُبلَغ")
        self.assertEqual(engine.state.state, MonitoringStateEnum.PAUSED)

        # ثانية: الحالة PAUSED ⇒ resume().
        mon._on_pause_resume_clicked()
        self.assertEqual(engine.resume_calls, 1, "engine.resume() لم يُبلَغ")

    # (d) إيقاف طارئ: _on_kill_switch_clicked ⇒ engine.kill_switch().
    def test_kill_switch_button_reaches_engine(self):
        _, mon, engine, _, _, _ = self._connect()
        mon._on_kill_switch_clicked()
        self.assertEqual(engine.kill_switch_calls, 1, "engine.kill_switch() لم يُبلَغ")

    # (e) تفعيل: هدف ليس مرشّح تحويل + confirm=True ⇒ executor.execute استُدعي.
    def test_activate_button_reaches_executor_execute(self):
        sel, _, _, executor, _, _ = self._connect()
        sel._confirm_cb = lambda text: True  # تجاوز QMessageBox الافتراضي
        sel.set_selected(_sample_selected())  # order_list_id=31, ليس مرشّح تحويل
        sel.set_current_price(Decimal("60000.00"))
        sel._tp_pct_edit.setText("4")
        sel._sl_pct_edit.setText("2")

        sel._on_activate_clicked()

        self.assertTrue(executor.calls, "executor.execute لم يُستدعَ — الحارس خرج مبكرًا")
        self.assertEqual(executor.calls[0]["order_list_id"], 31)
        self.assertEqual(executor.calls[0]["reference_price"], Decimal("60000.00"))

    # (f) أقصى إيقاف متاح: اختيار + سعر مرجعي + tick_size ⇒ قيمة غير فارغة.
    def test_max_available_stop_proceeds_past_guard(self):
        sel, _, _, _, _, _ = self._connect()
        sel.set_selected(_sample_selected())
        sel.set_current_price(Decimal("60000.00"))
        # تأكيد توفّر tick_size على الفلاتر.
        self.assertIsNotNone(sel._selected.filters.tick_size)

        sel._on_max_available_stop()

        value = sel._live_max_stop.text()
        self.assertNotEqual(value, "—", "أقصى إيقاف بقي فارغًا — الحارس خرج مبكرًا")
        self.assertTrue(value.strip())


if __name__ == "__main__":
    unittest.main()
