"""اختبارات G1.30 (chunk_4) — مُشرِف شبكة أمان المركز (guardian_supervisor.py).

تُختبر الوحدة بمحاكاة عميل في الذاكرة + مزوّد حالة بسيط + ساعة محقونة، بلا شبكة
وبلا Qt. تغطّي سيناريوهات المحاكاة الأربعة المطلوبة:

  1) عارٍ فوق العتبة ⇒ INTERVENE ⇒ place_protective_stop يضع وقفًا واحدًا
     (PLACED في وضع غير dry_run المحاكى) + إيقاف المراقبة (kill_switch) + تنبيه.
  2) محميّ (بيع حمائي قائم) ⇒ لا تدخّل (NOOP) وعدم استدعاء place_stop_loss_limit.
  3) تموضع صحّي جارٍ (in_flight و naked_seconds < threshold) ⇒ WAIT ⇒ لا تدخّل.
  4) لا بيع مزدوج (بنيويًّا): قفل الرصيد ⇒ free=0 ⇒ NOOP؛ وبيع قائم ⇒ NOOP؛
     وأن المُشرِف لا يتدخّل مرّتين لنفس العُري (idempotent).
"""
import unittest
from decimal import Decimal
from types import SimpleNamespace

from ocobot.domain.guardian import GuardianAction, GuardianConfig
from ocobot.domain.guardian_supervisor import GuardianSupervisor


# ---- أدوات محاكاة في الذاكرة (بلا شبكة) ------------------------------------
class _FakeBroker:
    """عميل محاكاة يحقّق عقد ProtectiveStopClient؛ يسجّل الاستدعاءات.

    لا يُعرّف أيّ دالة إلغاء إطلاقًا (المنفّذ/المحوّل لا يُلغيان أبدًا).
    """

    def __init__(self, open_orders=None, free="0"):
        self._open_orders = list(open_orders or [])
        self._free = Decimal(str(free))
        self.calls = []
        self.place_calls = []

    def get_open_sell_orders(self, symbol):
        self.calls.append(("get_open_sell_orders", symbol))
        return list(self._open_orders)

    def get_free_asset_qty(self, asset):
        self.calls.append(("get_free_asset_qty", asset))
        return self._free

    def place_stop_loss_limit(self, symbol, quantity, stop_price,
                              limit_price, client_order_id):
        self.calls.append(("place_stop_loss_limit", symbol))
        self.place_calls.append({
            "symbol": symbol,
            "quantity": quantity,
            "stop_price": stop_price,
            "limit_price": limit_price,
            "client_order_id": client_order_id,
        })
        return {"orderId": 9001, "status": "NEW", "clientOrderId": client_order_id}


class _FakeEngine:
    """محرّك محاكاة: state + selected_oco + kill_switch (الدوال الموجودة فقط)."""

    def __init__(self, state, selected):
        self.state = state
        self.selected_oco = selected
        self.kill_switch_calls = 0

    def kill_switch(self):
        self.kill_switch_calls += 1
        # يحاكي السلوك الموجود: إيقاف المراقبة دون إلغاء أي أمر.
        self.state.enabled = False
        self.state.state = SimpleNamespace(value="MONITORING_STOPPED")


class _Clock:
    """ساعة محقونة قابلة للتقديم اليدوي."""

    def __init__(self, t=0.0):
        self.t = float(t)

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += float(dt)


def _state(symbol="ETHUSDT", state_name="MONITORING_ACTIVE", in_flight=False,
           enabled=True, last_price="100", filters=None):
    return SimpleNamespace(
        symbol=symbol,
        state=SimpleNamespace(value=state_name),
        enabled=enabled,
        in_flight=in_flight,
        last_price=Decimal(str(last_price)) if last_price is not None else None,
        reference_price=Decimal(str(last_price)) if last_price is not None else None,
        filters=filters,
    )


def _filters(symbol="ETHUSDT"):
    return SimpleNamespace(
        symbol=symbol,
        tick_size=Decimal("0.01"),
        step_size=Decimal("0.001"),
        min_qty=Decimal("0.001"),
        min_notional=Decimal("10"),
    )


def _selected(qty="5", filters=None):
    return SimpleNamespace(quantity=Decimal(str(qty)), filters=filters)


def _supervisor(engine, broker, clock, *, dry_run=False, alerts=None,
                base_asset="ETH", threshold=4.0):
    alerts = alerts if alerts is not None else []
    cfg = GuardianConfig(threshold_seconds=threshold, emergency_sl_pct=Decimal("1"))
    sup = GuardianSupervisor(
        state_provider=lambda: engine,
        client=broker,
        alert_cb=lambda msg: alerts.append(msg),
        time_fn=clock,
        config=cfg,
        dry_run=dry_run,
        base_asset_fn=lambda sym: base_asset,
        engine=engine,
        filters_fn=lambda sym: _filters(sym),
        cid_factory=lambda: "grd-test-1",
    )
    return sup, alerts


# ---- (1) عارٍ فوق العتبة ⇒ تدخّل ووقف واحد --------------------------------
class TestNakedBeyondThresholdIntervenes(unittest.TestCase):
    def test_naked_places_one_stop_and_stops_monitoring(self):
        f = _filters()
        engine = _FakeEngine(_state(filters=f), _selected("5", filters=f))
        broker = _FakeBroker(open_orders=[], free="5")
        clock = _Clock(1000.0)
        sup, alerts = _supervisor(engine, broker, clock, dry_run=False)

        # أول tick: يبدأ تعقّب العُري، لا يزال تحت العتبة ⇒ WAIT.
        d0 = sup.tick()
        self.assertEqual(d0.action, GuardianAction.WAIT)
        self.assertEqual(len(broker.place_calls), 0)

        # تقدّم الزمن فوق العتبة ⇒ INTERVENE ووقف واحد.
        clock.advance(5.0)
        d1 = sup.tick()
        self.assertEqual(d1.action, GuardianAction.INTERVENE)
        self.assertEqual(len(broker.place_calls), 1)      # وُضع مرّة واحدة فقط
        self.assertEqual(engine.kill_switch_calls, 1)     # أُوقفت المراقبة
        self.assertEqual(len(alerts), 1)                  # أُطلق تنبيه واحد
        self.assertIn("ETHUSDT", alerts[0])
        # الكمية = min(free, monitored) = 5، مُنزَّلة لـ step
        self.assertEqual(broker.place_calls[0]["quantity"], Decimal("5"))
        self.assertEqual(broker.place_calls[0]["client_order_id"], "grd-test-1")


# ---- (2) محميّ ⇒ لا تدخّل --------------------------------------------------
class TestProtectedNoIntervention(unittest.TestCase):
    def test_resting_sell_present_never_intervenes(self):
        f = _filters()
        engine = _FakeEngine(_state(filters=f), _selected("5", filters=f))
        broker = _FakeBroker(open_orders=[{"orderId": 1, "type": "STOP_LOSS_LIMIT"}], free="5")
        clock = _Clock(2000.0)
        sup, alerts = _supervisor(engine, broker, clock, dry_run=False)

        # حتى بعد مرور زمن طويل: البيع القائم يمنع العُري أصلًا ⇒ NOOP دائمًا.
        for _ in range(3):
            clock.advance(10.0)
            d = sup.tick()
            self.assertEqual(d.action, GuardianAction.NOOP)
        self.assertEqual(len(broker.place_calls), 0)
        self.assertFalse(any(c[0] == "place_stop_loss_limit" for c in broker.calls))
        self.assertEqual(engine.kill_switch_calls, 0)
        self.assertEqual(len(alerts), 0)


# ---- (3) تموضع صحّي جارٍ ⇒ WAIT -------------------------------------------
class TestHealthyRepositionWaits(unittest.TestCase):
    def test_in_flight_below_threshold_waits(self):
        f = _filters()
        engine = _FakeEngine(
            _state(state_name="REPOSITIONING", in_flight=True, filters=f),
            _selected("5", filters=f),
        )
        broker = _FakeBroker(open_orders=[], free="5")
        clock = _Clock(3000.0)
        sup, alerts = _supervisor(engine, broker, clock, dry_run=False, threshold=4.0)

        d0 = sup.tick()                      # naked_seconds = 0 < threshold
        self.assertEqual(d0.action, GuardianAction.WAIT)
        clock.advance(1.5)                   # لا يزال < 4.0
        d1 = sup.tick()
        self.assertEqual(d1.action, GuardianAction.WAIT)
        self.assertEqual(len(broker.place_calls), 0)
        self.assertEqual(engine.kill_switch_calls, 0)
        self.assertEqual(len(alerts), 0)


# ---- (4) لا بيع مزدوج (بنيويًّا) + idempotent ------------------------------
class TestNoDoubleSell(unittest.TestCase):
    def test_locked_balance_zero_free_noop(self):
        # قفل الرصيد ⇒ free=0 ⇒ min(free, monitored)=0 ⇒ لا عُري ⇒ NOOP، لا وضع.
        f = _filters()
        engine = _FakeEngine(_state(filters=f), _selected("5", filters=f))
        broker = _FakeBroker(open_orders=[], free="0")
        clock = _Clock(4000.0)
        sup, alerts = _supervisor(engine, broker, clock, dry_run=False)

        clock.advance(100.0)
        d = sup.tick()
        self.assertEqual(d.action, GuardianAction.NOOP)
        self.assertEqual(len(broker.place_calls), 0)
        self.assertEqual(engine.kill_switch_calls, 0)

    def test_resting_sell_aborts_structurally(self):
        # بيع حمائي قائم ⇒ NOOP (منع البيع المزدوج) حتى مع كمية حرّة كبيرة.
        f = _filters()
        engine = _FakeEngine(_state(filters=f), _selected("9", filters=f))
        broker = _FakeBroker(open_orders=[{"orderListId": 42, "type": "STOP_LOSS_LIMIT"}], free="9")
        clock = _Clock(5000.0)
        sup, alerts = _supervisor(engine, broker, clock, dry_run=False)

        clock.advance(50.0)
        d = sup.tick()
        self.assertEqual(d.action, GuardianAction.NOOP)
        self.assertEqual(len(broker.place_calls), 0)

    def test_idempotent_no_second_intervention_for_same_naked(self):
        # عارٍ فوق العتبة ⇒ تدخّل مرّة واحدة؛ أي tick لاحق (ولا تزال نفس حالة
        # العُري) لا يضع أمرًا ثانيًا ولا يوقف المراقبة ثانيةً ولا يطلق تنبيهًا ثانيًا.
        f = _filters()
        engine = _FakeEngine(_state(filters=f), _selected("5", filters=f))
        broker = _FakeBroker(open_orders=[], free="5")
        clock = _Clock(6000.0)
        sup, alerts = _supervisor(engine, broker, clock, dry_run=False)

        # tick أول: يرسّخ لحظة أول اكتشاف للعُري (naked_since) ⇒ WAIT تحت العتبة.
        self.assertEqual(sup.tick().action, GuardianAction.WAIT)
        clock.advance(10.0)
        d1 = sup.tick()
        self.assertEqual(d1.action, GuardianAction.INTERVENE)
        self.assertEqual(len(broker.place_calls), 1)

        # إبقاء حالة العُري كما هي (engine.state ما زال يحمل الرمز، لكن kill_switch
        # عطّل enabled؛ لمحاكاة «نفس العُري» نعيد تفعيل المراقبة يدويًّا ونعيد tick).
        engine.state.enabled = True
        engine.state.state = SimpleNamespace(value="MONITORING_ACTIVE")
        clock.advance(10.0)
        d2 = sup.tick()
        self.assertEqual(d2.action, GuardianAction.INTERVENE)   # القرار نفسه
        self.assertEqual(len(broker.place_calls), 1)            # لكن لا وضع ثانٍ
        self.assertEqual(engine.kill_switch_calls, 1)          # لا إيقاف ثانٍ
        self.assertEqual(len(alerts), 1)                        # لا تنبيه ثانٍ

    def test_dry_run_plans_without_placing(self):
        # الوضع الآمن الافتراضي (dry_run=True): يتدخّل منطقيًّا لكن لا وضع فعلي.
        f = _filters()
        engine = _FakeEngine(_state(filters=f), _selected("5", filters=f))
        broker = _FakeBroker(open_orders=[], free="5")
        clock = _Clock(7000.0)
        sup, alerts = _supervisor(engine, broker, clock, dry_run=True)

        # tick أول يرسّخ naked_since ⇒ WAIT؛ ثم تجاوز العتبة ⇒ INTERVENE (dry_run).
        self.assertEqual(sup.tick().action, GuardianAction.WAIT)
        clock.advance(10.0)
        d = sup.tick()
        self.assertEqual(d.action, GuardianAction.INTERVENE)
        self.assertEqual(len(broker.place_calls), 0)   # DRY_RUN: لا وضع فعلي
        self.assertEqual(engine.kill_switch_calls, 1)  # تُوقَف المراقبة احترازيًّا
        self.assertEqual(len(alerts), 1)
        self.assertEqual(sup.last_result["action"], "DRY_RUN")


# ---- عدم وجود أيّ دالة إلغاء في العميل/المسار ------------------------------
class TestNeverCancels(unittest.TestCase):
    def test_broker_fake_defines_no_cancel(self):
        for name in ("cancel_order", "cancel_oco", "cancel", "delete_order", "cancel_all"):
            self.assertFalse(hasattr(_FakeBroker(), name))

    def test_supervisor_tick_never_calls_cancel(self):
        f = _filters()
        engine = _FakeEngine(_state(filters=f), _selected("5", filters=f))
        broker = _FakeBroker(open_orders=[], free="5")
        clock = _Clock(8000.0)
        sup, _alerts = _supervisor(engine, broker, clock, dry_run=False)
        clock.advance(10.0)
        sup.tick()
        self.assertFalse(
            any("cancel" in c[0].lower() or "delete" in c[0].lower() for c in broker.calls)
        )


# ---- خمول خارج المراقبة النشطة (لا أثر على المسار الحار) -------------------
class TestInactiveWhenNotMonitoring(unittest.TestCase):
    def test_disabled_state_returns_none_and_no_io_write(self):
        f = _filters()
        engine = _FakeEngine(_state(enabled=False, filters=f), _selected("5", filters=f))
        broker = _FakeBroker(open_orders=[], free="5")
        clock = _Clock(9000.0)
        sup, alerts = _supervisor(engine, broker, clock, dry_run=False)
        clock.advance(100.0)
        self.assertIsNone(sup.tick())
        self.assertEqual(len(broker.place_calls), 0)
        self.assertEqual(engine.kill_switch_calls, 0)

    def test_inactive_state_name_returns_none(self):
        f = _filters()
        engine = _FakeEngine(_state(state_name="PAUSED", filters=f), _selected("5", filters=f))
        broker = _FakeBroker(open_orders=[], free="5")
        clock = _Clock(9500.0)
        sup, _alerts = _supervisor(engine, broker, clock, dry_run=False)
        clock.advance(100.0)
        self.assertIsNone(sup.tick())
        self.assertEqual(len(broker.place_calls), 0)


if __name__ == "__main__":
    unittest.main()
