"""اختبارات محرّك المراقبة الديناميكية (M3 / T4).

تُغطّي معايير القبول الثلاثة + Latest Price + Latching + Rollover +
One-In-Flight + Guard + External-close + FAILED_NEEDS_ATTENTION + مثال رقمي.
"""
import unittest
from decimal import Decimal

from ocobot.domain.monitoring import (
    GuardPolicy,
    MonitoringEngine,
    MonitoringStateEnum,
    MSG_KILL_SWITCH,
)
from ocobot.domain.reposition import ExecutionState
from tests._fakes_monitoring import (
    FakeSafeExecutor,
    FakeSelectedOCO,
    make_result,
)


def _success(new_id=99, cancelled=31):
    return make_result(ExecutionState.SUCCESS, new_order_list_id=new_id,
                       cancelled_order_list_id=cancelled)


class TestAcceptance(unittest.TestCase):
    def test_acceptance1_jump_over_multiple_triggers_one_reposition(self):
        """قفزة فوق عدة مضاعفات تفعيل ⇒ إعادة تموضع واحدة من أحدث سعر."""
        ex = FakeSafeExecutor(result=_success())
        eng = MonitoringEngine(ex)
        eng.start(FakeSelectedOCO(), trigger_pct="1", tp_pct="4", sl_pct="2",
                  reference_price="100")
        # activation = 101؛ سعر يقفز إلى 130 (فوق 101/102/103…)
        tick = eng.on_price_tick("130")
        self.assertEqual(tick.event, "REPOSITIONED")
        self.assertEqual(len(ex.calls), 1)  # مرّة واحدة فقط
        self.assertEqual(ex.calls[0]["reference_price"], Decimal("130"))  # أحدث سعر
        self.assertEqual(eng.state.reference_price, Decimal("130"))       # المرجع الجديد
        self.assertEqual(eng.state.cursor, 1)

    def test_acceptance2_pause_keeps_oco_intact(self):
        """Pause: لا تنفيذ ولا إلغاء رغم ticks مؤهّلة؛ resume يُكمل."""
        ex = FakeSafeExecutor(result=_success())
        eng = MonitoringEngine(ex)
        eng.start(FakeSelectedOCO(), trigger_pct="1", tp_pct="4", sl_pct="2",
                  reference_price="100")
        eng.pause()
        self.assertEqual(eng.state.state, MonitoringStateEnum.PAUSED)
        eng.on_price_tick("130")
        eng.on_price_tick("140")
        self.assertEqual(len(ex.calls), 0)              # لا تنفيذ
        self.assertEqual(ex.cancel_calls, [])           # لا إلغاء
        eng.resume()
        self.assertEqual(eng.state.state, MonitoringStateEnum.MONITORING_ACTIVE)
        self.assertEqual(eng.state.reference_price, Decimal("100"))  # نفس المرجع
        self.assertEqual(eng.state.target_order_list_id, 31)         # نفس الهدف

    def test_acceptance3_kill_switch_cancels_nothing(self):
        """Kill Switch: لا execute/cancel/create، الحالة MONITORING_STOPPED، رسالة مطابقة."""
        ex = FakeSafeExecutor(result=_success())
        eng = MonitoringEngine(ex)
        eng.start(FakeSelectedOCO(), trigger_pct="1", tp_pct="4", sl_pct="2",
                  reference_price="100")
        tick = eng.kill_switch()
        self.assertEqual(eng.state.state, MonitoringStateEnum.MONITORING_STOPPED)
        self.assertFalse(eng.state.enabled)
        self.assertEqual(tick.message, MSG_KILL_SWITCH)
        self.assertEqual(len(ex.calls), 0)
        self.assertEqual(ex.cancel_calls, [])
        self.assertEqual(ex.create_calls, [])
        # ticks بعد الـ kill لا تفعل شيئًا
        eng.on_price_tick("200")
        self.assertEqual(len(ex.calls), 0)


class TestPrinciples(unittest.TestCase):
    def test_latest_price_principle(self):
        """المرجع المُمرَّر للمنفّذ = أحدث tick لا سعر لحظة التفعيل."""
        ex = FakeSafeExecutor(result=_success())
        eng = MonitoringEngine(ex)
        eng.start(FakeSelectedOCO(), trigger_pct="1", tp_pct="4", sl_pct="2",
                  reference_price="100")
        tick = eng.on_price_tick("125")
        self.assertEqual(tick.event, "REPOSITIONED")
        self.assertEqual(ex.calls[0]["reference_price"], Decimal("125"))

    def test_trigger_latching_survives_small_pullback(self):
        """عبور التفعيل ثم سحب صغير ضمن guard ⇒ latched يبقى True (لا يُلغى)."""
        # نستخدم HALT_NOTIFY وسحبًا صغيرًا ضمن الحارس حتى لا يُنفَّذ فورًا ونفحص latched
        ex = FakeSafeExecutor(result=_success())
        eng = MonitoringEngine(ex, guard_policy=GuardPolicy.HALT_NOTIFY)
        eng.start(FakeSelectedOCO(), trigger_pct="1", tp_pct="4", sl_pct="2",
                  reference_price="100", guard_pct="1.0")
        # فعّل عند 101 ثم اسحب إلى 100.5 (ضمن guard 1% من 101 = 99.99) — يُنفَّذ من أحدث سعر
        eng.state  # activation=101
        # أول عبور: 101 -> latched + تنفيذ (نتيجة نجاح) => reference=101
        first = eng.on_price_tick("101")
        self.assertEqual(first.event, "REPOSITIONED")
        # نتأكّد أن latched صار True قبل التنفيذ عبر مسار منفصل بلا تنفيذ:
        ex2 = FakeSafeExecutor(results=[
            make_result(ExecutionState.ABORTED, reason="gate failed non-destructive")
        ])
        eng2 = MonitoringEngine(ex2, guard_policy=GuardPolicy.EXECUTE_LATEST)
        eng2.start(FakeSelectedOCO(), trigger_pct="1", tp_pct="4", sl_pct="2",
                   reference_price="100")
        eng2.on_price_tick("101.5")   # يعبر، ينفّذ، لكن Abort غير مُدمِّر ⇒ latched يبقى
        self.assertTrue(eng2.state.latched)
        # سحب صغير لاحق لا يُلغي latched
        eng2.on_price_tick("100.8")
        self.assertTrue(eng2.state.latched)

    def test_rollover_updates_target_and_next_reposition_uses_new_id(self):
        ex = FakeSafeExecutor(results=[
            _success(new_id=99, cancelled=31),
            _success(new_id=150, cancelled=99),
        ])
        eng = MonitoringEngine(ex)
        eng.start(FakeSelectedOCO(order_list_id=31), trigger_pct="1", tp_pct="4",
                  sl_pct="2", reference_price="100")
        eng.on_price_tick("120")                     # reposition #1 => target 99
        self.assertEqual(eng.state.target_order_list_id, 99)
        self.assertEqual(eng.state.reference_price, Decimal("120"))
        # المرجع الآن 120؛ activation = 121.2؛ tick مؤهّل جديد
        eng.on_price_tick("140")                     # reposition #2 على الـ id الجديد
        self.assertEqual(ex.calls[1]["order_list_id"], 99)   # استهدف الـ id الجديد
        self.assertEqual(eng.state.target_order_list_id, 150)
        self.assertEqual(eng.state.cursor, 2)

    def test_one_replacement_in_flight_skips_new_tick(self):
        ex = FakeSafeExecutor(result=_success())
        eng = MonitoringEngine(ex)
        eng.start(FakeSelectedOCO(), trigger_pct="1", tp_pct="4", sl_pct="2",
                  reference_price="100")
        eng.state.latched = True
        eng.state.in_flight = True   # محاكاة دورة قيد التنفيذ
        tick = eng.on_price_tick("130")
        self.assertEqual(tick.event, "IN_FLIGHT_SKIPPED")
        self.assertEqual(len(ex.calls), 0)
        self.assertEqual(eng.state.last_price, Decimal("130"))  # احتُفظ بأحدث سعر


class TestGuard(unittest.TestCase):
    def test_guard_halt_notify_no_execute_no_cancel(self):
        ex = FakeSafeExecutor(result=_success())
        eng = MonitoringEngine(ex, guard_policy=GuardPolicy.HALT_NOTIFY)
        eng.start(FakeSelectedOCO(), trigger_pct="1", tp_pct="4", sl_pct="2",
                  reference_price="100", guard_pct="1.0")
        # فعّل أولًا (نجعله latched دون تنفيذ فوري باستخدام tick تفعيل ثم سحب حادّ)
        eng.state.latched = True
        eng.state.state = MonitoringStateEnum.TRIGGERED
        # activation=101؛ guard_floor = 101*(1-0.01)=99.99؛ سعر 95 << 99.99
        tick = eng.on_price_tick("95")
        self.assertEqual(tick.event, "GUARD_HALT")
        self.assertEqual(len(ex.calls), 0)
        self.assertEqual(ex.cancel_calls, [])

    def test_guard_execute_latest_executes(self):
        ex = FakeSafeExecutor(result=_success())
        eng = MonitoringEngine(ex, guard_policy=GuardPolicy.EXECUTE_LATEST)
        eng.start(FakeSelectedOCO(), trigger_pct="1", tp_pct="4", sl_pct="2",
                  reference_price="100", guard_pct="1.0")
        eng.state.latched = True
        eng.state.state = MonitoringStateEnum.TRIGGERED
        tick = eng.on_price_tick("95")   # حركة معاكسة لكن السياسة تُنفّذ من أحدث سعر
        self.assertEqual(tick.event, "REPOSITIONED")
        self.assertEqual(len(ex.calls), 1)
        self.assertEqual(ex.calls[0]["reference_price"], Decimal("95"))


class TestTerminalStates(unittest.TestCase):
    def test_external_close_sets_closed_and_disables(self):
        ex = FakeSafeExecutor(results=[
            make_result(ExecutionState.ABORTED,
                        reason="order no longer exists on the exchange")
        ])
        eng = MonitoringEngine(ex)
        eng.start(FakeSelectedOCO(), trigger_pct="1", tp_pct="4", sl_pct="2",
                  reference_price="100")
        tick = eng.on_price_tick("130")
        self.assertEqual(tick.event, "CLOSED")
        self.assertEqual(eng.state.state, MonitoringStateEnum.CLOSED)
        self.assertFalse(eng.state.enabled)

    def test_non_destructive_abort_keeps_monitoring_and_latched(self):
        ex = FakeSafeExecutor(results=[
            make_result(ExecutionState.ABORTED, reason="pre-cancel gate failed")
        ])
        eng = MonitoringEngine(ex)
        eng.start(FakeSelectedOCO(), trigger_pct="1", tp_pct="4", sl_pct="2",
                  reference_price="100")
        tick = eng.on_price_tick("130")
        self.assertEqual(tick.event, "ABORTED")
        self.assertEqual(eng.state.state, MonitoringStateEnum.MONITORING_ACTIVE)
        self.assertTrue(eng.state.latched)
        self.assertFalse(eng.state.in_flight)

    def test_failed_needs_attention_halts_no_blind_retry(self):
        ex = FakeSafeExecutor(results=[
            make_result(ExecutionState.FAILED_NEEDS_ATTENTION,
                        reason="cancel ok, create failed"),
            _success(),  # لو حدثت محاولة ثانية (يجب ألا تحدث) لكشفناها
        ])
        eng = MonitoringEngine(ex)
        eng.start(FakeSelectedOCO(), trigger_pct="1", tp_pct="4", sl_pct="2",
                  reference_price="100")
        tick = eng.on_price_tick("130")
        self.assertEqual(tick.event, "FAILED_NEEDS_ATTENTION")
        self.assertEqual(eng.state.state, MonitoringStateEnum.FAILED_NEEDS_ATTENTION)
        self.assertFalse(eng.state.enabled)
        # tick تالٍ لا يُطلق أي تنفيذ جديد (No Blind Retry)
        eng.on_price_tick("140")
        self.assertEqual(len(ex.calls), 1)


class TestNumericExample(unittest.TestCase):
    def test_numeric_reference_005_trigger_1pct(self):
        """reference 0.05000، trigger 1% => activation 0.05050؛ tick 0.05060 => exec@0.05060."""
        ex = FakeSafeExecutor(result=_success())
        eng = MonitoringEngine(ex)
        eng.start(FakeSelectedOCO(symbol="XYZUSDT"), trigger_pct="1", tp_pct="4",
                  sl_pct="2", reference_price="0.05000")
        self.assertEqual(eng.activation_level(), Decimal("0.05050"))
        tick = eng.on_price_tick("0.05060")
        self.assertEqual(tick.event, "REPOSITIONED")
        self.assertEqual(ex.calls[0]["reference_price"], Decimal("0.05060"))

    def test_below_activation_is_idle_no_execute(self):
        ex = FakeSafeExecutor(result=_success())
        eng = MonitoringEngine(ex)
        eng.start(FakeSelectedOCO(), trigger_pct="1", tp_pct="4", sl_pct="2",
                  reference_price="100")
        tick = eng.on_price_tick("100.5")   # تحت activation=101
        self.assertEqual(tick.event, "IDLE")
        self.assertFalse(eng.state.latched)
        self.assertEqual(len(ex.calls), 0)

    def test_dry_run_flag_forwarded_to_executor(self):
        ex = FakeSafeExecutor(result=_success())
        eng = MonitoringEngine(ex, dry_run=True)
        eng.start(FakeSelectedOCO(), trigger_pct="1", tp_pct="4", sl_pct="2",
                  reference_price="100")
        eng.on_price_tick("130")
        self.assertTrue(ex.calls[0]["dry_run"])

    def test_to_dict_is_json_safe(self):
        ex = FakeSafeExecutor(result=_success())
        eng = MonitoringEngine(ex)
        eng.start(FakeSelectedOCO(), trigger_pct="1", tp_pct="4", sl_pct="2",
                  reference_price="100")
        d = eng.state.to_dict()
        self.assertEqual(d["referencePrice"], "100")
        self.assertIsInstance(d["state"], str)


if __name__ == "__main__":
    unittest.main()
