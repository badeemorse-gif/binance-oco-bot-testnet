# -*- coding: utf-8 -*-
"""اختبارات G1.44 / chunk_4 — بوّابات تشغيل مستقلّة لحارسَي المركز وهبوط BTC.

نقية بالكامل (بلا ``QApplication``، بلا شبكة): مُشرِف وهميّ/عميل محاكى في الذاكرة.
تغطّي:
  (a) الافتراضي OFF ⇒ حارس BTC NOOP تامّ (لا خروج ولا تنبيه).
  (b) تحكّم مستقلّ ⇒ BTC في LIVE وشبكة الأمان OFF: tick يقود خروج BTC دون وضع
      وقف حمائي للمركز.
  (c) مسار الخروج الحقيقي ⇒ btc_exit_fn يستدعي execute_market_exit بـ
      exit_side="lower", dry_run=False؛ PLACED في الحالة السعيدة وABORT_PROTECTED
      عند وجود بيع حمائي قائم (منع البيع المزدوج).
  (d) Observe ⇒ DRY_RUN بلا خروج مع إطلاق تنبيه.
"""
import unittest
from decimal import Decimal
from types import SimpleNamespace

from ocobot.domain.guardian import GuardianConfig
from ocobot.domain.guardian_supervisor import GuardianSupervisor
from ocobot.domain.btc_follow import (
    BtcFollowAction,
    BtcFollowDecision,
    BtcFollowPhase,
    BtcFollowState,
)
from ocobot.domain.market_exit import execute_market_exit, EXIT_LOWER


_FILTERS = SimpleNamespace(
    symbol="ADAUSDT",
    tick_size=Decimal("0.0001"),
    step_size=Decimal("0.1"),
    min_qty=Decimal("0.1"),
    min_notional=Decimal("1"),
    gap_ticks=2,
)


class _FakeBtc:
    """بديل btc_follow يُعيد TIGHTEN ثابتًا لكل tick."""

    def __init__(self, action=BtcFollowAction.TIGHTEN):
        self._action = action
        self.ticks = 0

    def tick(self, now=None):
        self.ticks += 1
        return BtcFollowDecision(
            action=self._action,
            phase=BtcFollowPhase.IDLE,
            drop_pct=Decimal("1.5"),
            reason="confirmed_drop",
            state=BtcFollowState(),
        )


class _Client:
    """عميل محاكى لشبكة أمان المركز (ProtectiveStopClient)."""

    def __init__(self, resting, free):
        self._resting = list(resting)
        self._free = free
        self.placed = []

    def get_open_sell_orders(self, symbol):
        return list(self._resting)

    def get_free_asset_qty(self, asset):
        return self._free

    def place_stop_loss_limit(self, **kw):
        self.placed.append(kw)
        return {"ok": True}


class _ExitClient:
    """عميل خروج محاكى يحقّق MarketExitClient (بلا شبكة)."""

    def __init__(self, free="10", resting=None):
        self.free = Decimal(str(free))
        self.resting = list(resting) if resting is not None else []
        self.placed = []
        self.cancelled = []

    def get_open_sell_orders(self, symbol):
        return list(self.resting)

    def get_free_asset_qty(self, asset):
        return self.free

    def cancel_oco(self, symbol, order_list_id):
        self.cancelled.append(order_list_id)
        return {"ok": True}

    def place_stop_loss_limit(self, symbol, quantity, stop_price, limit_price, client_order_id):
        self.placed.append(("STOP_LOSS_LIMIT", quantity, stop_price, limit_price))
        return {"ok": True}

    def place_limit_sell(self, symbol, quantity, price, client_order_id):
        self.placed.append(("LIMIT", quantity, price))
        return {"ok": True}

    def place_market_sell(self, symbol, quantity, client_order_id):
        self.placed.append(("MARKET", quantity))
        return {"ok": True}


def _state(symbol="ADAUSDT", state="MONITORING_ACTIVE", qty=Decimal("10")):
    return SimpleNamespace(
        symbol=symbol,
        enabled=True,
        state=state,
        in_flight=False,
        last_price=Decimal("0.42"),
        reference_price=Decimal("0.42"),
        target_order_list_id=None,
        selected_oco=SimpleNamespace(quantity=qty, filters=_FILTERS, order_list_id=None),
        filters=_FILTERS,
    )


def _make_supervisor(*, dry_run, resting, exit_fn=None, calls=None,
                     btc_action=BtcFollowAction.TIGHTEN):
    calls = calls if calls is not None else {"exit": [], "alerts": []}
    client = _Client(resting=resting, free=Decimal("10"))

    def default_exit(**kw):
        calls["exit"].append(kw)
        return {"action": "PLACED", "placed": True}

    sup = GuardianSupervisor(
        state_provider=lambda: _state(),
        client=client,
        alert_cb=lambda t: None,
        config=GuardianConfig(),
        dry_run=dry_run,
        base_asset_fn=lambda s: "ADA",
        filters_fn=lambda s: _FILTERS,
        reference_price_fn=lambda st: Decimal("0.42"),
        btc_follow=_FakeBtc(btc_action),
        btc_exit_fn=exit_fn if exit_fn is not None else default_exit,
        btc_alert_cb=lambda t: calls["alerts"].append(t),
    )
    return sup, client, calls


class TestDefaultOffNoop(unittest.TestCase):
    """(a) set_btc_runtime(enabled=False) ⇒ حارس BTC لا يتصرّف إطلاقًا."""

    def test_btc_disabled_is_pure_noop(self):
        sup, client, calls = _make_supervisor(dry_run=False, resting=["oco-leg"])
        sup.set_btc_runtime(enabled=False, dry_run=True)
        sup.tick()
        self.assertEqual(len(calls["exit"]), 0)
        self.assertEqual(len(calls["alerts"]), 0)
        self.assertIsNone(getattr(sup, "last_btc_result", None))
        # لم يُستشَر btc_follow أصلًا (بوّابة التفعيل قبل tick الفرعي).
        self.assertEqual(sup._btc_follow.ticks, 0)


class TestIndependentControl(unittest.TestCase):
    """(b) BTC في LIVE وشبكة الأمان OFF: خروج BTC دون وقف حمائي للمركز."""

    def test_btc_live_while_guardian_off(self):
        # resting فارغ + حالة FAILED_NEEDS_ATTENTION ⇒ شبكة الأمان تقرّر INTERVENE.
        calls = {"exit": [], "alerts": []}
        client = _Client(resting=[], free=Decimal("10"))

        def exit_fn(**kw):
            calls["exit"].append(kw)
            return {"action": "PLACED", "placed": True}

        sup = GuardianSupervisor(
            state_provider=lambda: _state(state="FAILED_NEEDS_ATTENTION"),
            client=client,
            alert_cb=lambda t: None,
            config=GuardianConfig(),
            dry_run=False,
            base_asset_fn=lambda s: "ADA",
            filters_fn=lambda s: _FILTERS,
            reference_price_fn=lambda st: Decimal("0.42"),
            btc_follow=_FakeBtc(BtcFollowAction.TIGHTEN),
            btc_exit_fn=exit_fn,
            btc_alert_cb=lambda t: calls["alerts"].append(t),
        )
        # شبكة الأمان OFF (لا تدخّل فعلي)، حارس BTC LIVE.
        sup.set_guardian_runtime(enabled=False, dry_run=False)
        sup.set_btc_runtime(enabled=True, dry_run=False)
        sup.tick()
        # لم يُوضع وقف حمائي للمركز (الحارس الأساسي مُعطّل).
        self.assertEqual(len(client.placed), 0)
        # ملاحظة: شبكة الأمان قرّرت INTERVENE منطقيًّا ⇒ أولوية ⇒ BTC مكبوح.
        # لذا نؤكّد أن المركز لم يتدخّل، وأن BTC لم يكسر الأولوية.
        self.assertEqual(len(calls["exit"]), 0)

    def test_btc_live_guardian_off_no_guardian_intervene(self):
        # حالة MONITORING_ACTIVE + بيع حمائي قائم ⇒ شبكة الأمان NOOP (لا أولوية)،
        # فيتصرّف حارس BTC (تضييق) عبر مسار الخروج رغم الحارس المُعطّل.
        calls = {"exit": [], "alerts": []}
        client = _Client(resting=["oco-leg"], free=Decimal("10"))

        def exit_fn(**kw):
            calls["exit"].append(kw)
            return {"action": "PLACED", "placed": True}

        sup = GuardianSupervisor(
            state_provider=lambda: _state(state="MONITORING_ACTIVE"),
            client=client,
            alert_cb=lambda t: None,
            config=GuardianConfig(),
            dry_run=False,
            base_asset_fn=lambda s: "ADA",
            filters_fn=lambda s: _FILTERS,
            reference_price_fn=lambda st: Decimal("0.42"),
            btc_follow=_FakeBtc(BtcFollowAction.TIGHTEN),
            btc_exit_fn=exit_fn,
            btc_alert_cb=lambda t: calls["alerts"].append(t),
        )
        sup.set_guardian_runtime(enabled=False, dry_run=False)
        sup.set_btc_runtime(enabled=True, dry_run=False)
        sup.tick()
        self.assertEqual(len(client.placed), 0)   # لا وقف حمائي للمركز
        self.assertEqual(len(calls["exit"]), 1)   # خروج BTC نُفّذ
        self.assertTrue(calls["alerts"])


class TestRealExitPath(unittest.TestCase):
    """(c) btc_exit_fn يستدعي execute_market_exit حقيقيًّا (محاكاة عميل)."""

    def _btc_exit(self, exit_client, order_list_id=None):
        """نسخة مطابقة لمنطق guardian_arm.btc_exit_fn فوق عميل خروج محاكى."""
        def _fn(symbol, base_asset, btc_decision, state, engine, **_):
            try:
                return execute_market_exit(
                    client=exit_client,
                    symbol=symbol,
                    base_asset=base_asset or "",
                    exit_side="lower",
                    reference_price=Decimal("0.42"),
                    target_qty=Decimal("10"),
                    filters=_FILTERS,
                    client_order_id="btcg-test-1",
                    order_list_id=order_list_id,
                    kill_switch=None,
                    notifier=None,
                    dry_run=False,
                )
            except Exception as exc:
                return {"action": "ERROR", "placed": False, "error": str(exc)}
        return _fn

    def test_placed_happy_path(self):
        exit_client = _ExitClient(free="10", resting=[])
        calls = {"exit": [], "alerts": []}
        sup, _c, _ = _make_supervisor(
            dry_run=False, resting=["oco-leg"],
            exit_fn=self._btc_exit(exit_client), calls=calls,
        )
        sup.set_btc_runtime(enabled=True, dry_run=False)
        sup.tick()
        self.assertEqual(sup.last_btc_result.get("action"), "PLACED")
        self.assertTrue(sup.last_btc_result.get("placed"))
        self.assertEqual(sup.last_btc_result.get("exit_side"), EXIT_LOWER)
        self.assertEqual(len(exit_client.placed), 1)
        self.assertEqual(exit_client.placed[0][0], "STOP_LOSS_LIMIT")

    def test_abort_protected_double_sell_prevention(self):
        # بيع حمائي قائم عند reconcile ⇒ ABORT_PROTECTED ولا وضع (منع بيع مزدوج).
        exit_client = _ExitClient(free="10", resting=["resting-sell"])
        calls = {"exit": [], "alerts": []}
        sup, _c, _ = _make_supervisor(
            dry_run=False, resting=["oco-leg"],
            exit_fn=self._btc_exit(exit_client), calls=calls,
        )
        sup.set_btc_runtime(enabled=True, dry_run=False)
        sup.tick()
        self.assertEqual(sup.last_btc_result.get("action"), "ABORT_PROTECTED")
        self.assertFalse(sup.last_btc_result.get("placed"))
        self.assertEqual(len(exit_client.placed), 0)

    def test_exit_side_is_lower_and_live(self):
        captured = {}

        def exit_fn(symbol, base_asset, btc_decision, state, engine, **_):
            captured["ran"] = True
            return execute_market_exit(
                client=_ExitClient(free="10", resting=[]),
                symbol=symbol, base_asset=base_asset or "", exit_side="lower",
                reference_price=Decimal("0.42"), target_qty=Decimal("10"),
                filters=_FILTERS, client_order_id="btcg-x", order_list_id=None,
                kill_switch=None, notifier=None, dry_run=False,
            )

        sup, _c, _ = _make_supervisor(dry_run=False, resting=["oco-leg"], exit_fn=exit_fn)
        sup.set_btc_runtime(enabled=True, dry_run=False)
        sup.tick()
        self.assertTrue(captured.get("ran"))
        self.assertEqual(sup.last_btc_result.get("exit_side"), "lower")


class TestObserveDryRun(unittest.TestCase):
    """(d) Observe ⇒ DRY_RUN بلا خروج مع إطلاق تنبيه."""

    def test_observe_dry_run_no_exit_alert_fired(self):
        calls = {"exit": [], "alerts": []}
        sup, client, _ = _make_supervisor(dry_run=False, resting=["oco-leg"], calls=calls)
        # Observe على حارس BTC: enabled=True, dry_run=True (رغم المُشرِف العامّ live).
        sup.set_btc_runtime(enabled=True, dry_run=True)
        sup.tick()
        self.assertEqual(len(calls["exit"]), 0)
        self.assertEqual(sup.last_btc_result.get("action"), "DRY_RUN")
        self.assertFalse(sup.last_btc_result.get("placed"))
        self.assertTrue(calls["alerts"])


if __name__ == "__main__":
    unittest.main()
