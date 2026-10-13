"""اختبارات الخروج اليدوي الفوري بأولوية عُليا (G1.47) — بمحاكاة عميل، بلا شبكة.

تغطّي فحوص العقد (WORKING_MEMORY / acceptance_checks):
  (أ) بوّابة التنفيذ الآمن ``manual_exit_safety_gate`` (قيد منع البيع المزدوج).
  (ب) ``run_manual_market_exit`` يمرّ عبر البوّابة ثم مسار الخروج المُختبَر
      ``execute_market_exit`` حصريًّا: وضع واحد فقط + منع البيع المزدوج (البوّابة
      + reconcile) + ``dry_run`` بلا أثر (لا Live).
  (ج) الأولوية البنيوية على الوسائل الأربع: بعد الخروج (بيع حمائي قائم أو رصيد حرّ
      صفر) يصبح الحارس ``evaluate`` ⇒ ``NOOP`` — نفس القيد يُعطّل بقية الوسائل.
  (د) §1.5 ثنائية اللغة لتسمية الزرّ.

كلها نقيّة offscreen: عميل مُحاكى يحقّق ``MarketExitClient`` (بلا socket/urllib)،
ولا نداءات شبكة فعلية إطلاقًا. ``dry_run`` الافتراضي يضمن عدم أي تنفيذ (لا Live قبل G1).
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest
from decimal import Decimal
from types import SimpleNamespace

from ocobot.ui.safe_execution import (
    manual_exit_safety_gate,
    MANUAL_EXIT_GATE_OK,
    MANUAL_EXIT_GATE_RESTING,
    MANUAL_EXIT_GATE_NO_FREE,
)
from ocobot.ui.manual_exit import run_manual_market_exit, build_manual_exit_fn
from ocobot.ui import i18n
from ocobot.domain.guardian import (
    GuardianSnapshot,
    GuardianConfig,
    GuardianAction,
    evaluate,
)


def _filters(tick="0.01", step="0.00001"):
    """فلاتر مُحاكاة (tick/step) بلا min_qty/min_notional — خطّة علوية صالحة."""
    return SimpleNamespace(
        symbol="BTCUSDT",
        tick_size=Decimal(tick),
        step_size=Decimal(step),
        min_qty=None,
        min_notional=None,
        gap_ticks=1,
    )


class FakeMarketExitClient:
    """عميل مُحاكى يحقّق عقد ``MarketExitClient`` — بلا أيّ شبكة.

    ``free`` الرصيد الحرّ المُعاد؛ ``resting`` قائمة أوامر البيع القائمة التي يراها
    reconcile داخل ``execute_market_exit`` (لاختبار منع البيع المزدوج).
    """

    def __init__(self, free="1.0", resting=()):
        self._free = Decimal(str(free))
        self._resting = list(resting)
        self.cancelled = []
        self.placed = []

    def get_open_sell_orders(self, symbol):
        return list(self._resting)

    def get_free_asset_qty(self, asset):
        return self._free

    def cancel_oco(self, symbol, order_list_id):
        self.cancelled.append(order_list_id)
        return {"ok": True, "orderListId": order_list_id}

    def place_stop_loss_limit(self, symbol, quantity, stop_price, limit_price, client_order_id):
        self.placed.append(("STOP_LOSS_LIMIT", quantity, client_order_id))
        return {"orderId": 11, "status": "NEW"}

    def place_limit_sell(self, symbol, quantity, price, client_order_id):
        self.placed.append(("LIMIT", quantity, price, client_order_id))
        return {"orderId": 12, "status": "NEW"}

    def place_market_sell(self, symbol, quantity, client_order_id):
        self.placed.append(("MARKET", quantity, client_order_id))
        return {"orderId": 13, "status": "NEW"}


class ManualExitGateTests(unittest.TestCase):
    """(أ) بوّابة التنفيذ الآمن — قيد منع البيع المزدوج البنيوي."""

    def test_resting_protective_sell_blocks(self):
        g = manual_exit_safety_gate(
            has_resting_protective_sell=True,
            free_base_qty=Decimal("0.5"),
            monitored_qty=Decimal("0.5"),
        )
        self.assertFalse(g["allowed"])
        self.assertEqual(g["reason"], MANUAL_EXIT_GATE_RESTING)
        self.assertEqual(g["protective_qty"], Decimal("0"))

    def test_no_free_qty_blocks(self):
        g = manual_exit_safety_gate(
            has_resting_protective_sell=False,
            free_base_qty=Decimal("0"),
            monitored_qty=Decimal("0.5"),
        )
        self.assertFalse(g["allowed"])
        self.assertEqual(g["reason"], MANUAL_EXIT_GATE_NO_FREE)

    def test_protective_qty_is_min_free_monitored(self):
        g1 = manual_exit_safety_gate(
            has_resting_protective_sell=False,
            free_base_qty=Decimal("0.3"),
            monitored_qty=Decimal("0.5"),
        )
        self.assertTrue(g1["allowed"])
        self.assertEqual(g1["reason"], MANUAL_EXIT_GATE_OK)
        self.assertEqual(g1["protective_qty"], Decimal("0.3"))

        g2 = manual_exit_safety_gate(
            has_resting_protective_sell=False,
            free_base_qty=Decimal("0.5"),
            monitored_qty=Decimal("0.3"),
        )
        self.assertEqual(g2["protective_qty"], Decimal("0.3"))


class RunManualMarketExitTests(unittest.TestCase):
    """(ب) الخروج اليدوي: البوّابة ثم مسار الخروج المُختبَر حصريًّا."""

    def test_placed_single_order_on_upper_exit(self):
        client = FakeMarketExitClient(free="1.0", resting=())
        res = run_manual_market_exit(
            client=client,
            symbol="BTCUSDT",
            base_asset="BTC",
            free_base_qty=Decimal("1.0"),
            monitored_qty=Decimal("0.5"),
            has_resting_protective_sell=False,
            reference_price=Decimal("70000"),
            filters=_filters(),
            exit_side="upper",
            order_list_id=31,
            dry_run=False,
        )
        self.assertEqual(res["action"], "PLACED")
        self.assertTrue(res["placed"])
        # وضع واحد فقط (لا بيع مزدوج) من النوع LIMIT بالكمية المُراقَبة.
        self.assertEqual(len(client.placed), 1)
        self.assertEqual(client.placed[0][0], "LIMIT")
        self.assertEqual(client.placed[0][1], Decimal("0.5"))
        # أُلغي OCO القائم (جزء من مسار market_exit المبدوء بالمستخدم).
        self.assertEqual(client.cancelled, [31])

    def test_gate_blocks_resting_before_any_execution(self):
        client = FakeMarketExitClient(free="1.0", resting=())
        res = run_manual_market_exit(
            client=client,
            symbol="BTCUSDT",
            base_asset="BTC",
            free_base_qty=Decimal("1.0"),
            monitored_qty=Decimal("0.5"),
            has_resting_protective_sell=True,
            reference_price=Decimal("70000"),
            filters=_filters(),
            order_list_id=31,
            dry_run=False,
        )
        self.assertEqual(res["action"], "ABORT_GATE")
        self.assertFalse(res["placed"])
        self.assertEqual(res["reason"], MANUAL_EXIT_GATE_RESTING)
        # لم يُستدعَ المنفّذ إطلاقًا: لا إلغاء ولا وضع.
        self.assertEqual(client.placed, [])
        self.assertEqual(client.cancelled, [])

    def test_gate_blocks_when_no_free_qty(self):
        client = FakeMarketExitClient(free="0", resting=())
        res = run_manual_market_exit(
            client=client,
            symbol="BTCUSDT",
            base_asset="BTC",
            free_base_qty=Decimal("0"),
            monitored_qty=Decimal("0.5"),
            has_resting_protective_sell=False,
            reference_price=Decimal("70000"),
            filters=_filters(),
            dry_run=False,
        )
        self.assertEqual(res["action"], "ABORT_GATE")
        self.assertEqual(res["reason"], MANUAL_EXIT_GATE_NO_FREE)
        self.assertEqual(client.placed, [])

    def test_double_sell_aborted_at_reconcile(self):
        # البوّابة تمرّ (لا بيع حمائي معروف مسبقًا) لكن reconcile داخل المنفّذ يجد
        # بيعًا حمائيًّا قائمًا بعد الإلغاء ⇒ ABORT_PROTECTED بلا وضع بيع ثانٍ.
        client = FakeMarketExitClient(free="1.0", resting=[{"orderId": 999}])
        res = run_manual_market_exit(
            client=client,
            symbol="BTCUSDT",
            base_asset="BTC",
            free_base_qty=Decimal("1.0"),
            monitored_qty=Decimal("0.5"),
            has_resting_protective_sell=False,
            reference_price=Decimal("70000"),
            filters=_filters(),
            order_list_id=31,
            dry_run=False,
        )
        self.assertEqual(res["action"], "ABORT_PROTECTED")
        self.assertFalse(res["placed"])
        self.assertEqual(client.placed, [])

    def test_eff_qty_clamped_to_live_free_in_executor(self):
        # البوّابة ترى رصيدًا كافيًا (0.5) لكن الرصيد الحيّ لدى العميل 0.3 ⇒ المنفّذ
        # يقصر الكمية على min(target, free) = 0.3 (قيد منع البيع المزدوج الكمّي).
        client = FakeMarketExitClient(free="0.3", resting=())
        res = run_manual_market_exit(
            client=client,
            symbol="BTCUSDT",
            base_asset="BTC",
            free_base_qty=Decimal("0.5"),
            monitored_qty=Decimal("0.5"),
            has_resting_protective_sell=False,
            reference_price=Decimal("70000"),
            filters=_filters(),
            exit_side="upper",
            dry_run=False,
        )
        self.assertEqual(res["action"], "PLACED")
        self.assertEqual(client.placed[0][1], Decimal("0.3"))

    def test_dry_run_default_has_no_side_effects_no_live(self):
        client = FakeMarketExitClient(free="1.0", resting=())
        res = run_manual_market_exit(
            client=client,
            symbol="BTCUSDT",
            base_asset="BTC",
            free_base_qty=Decimal("1.0"),
            monitored_qty=Decimal("0.5"),
            has_resting_protective_sell=False,
            reference_price=Decimal("70000"),
            filters=_filters(),
            order_list_id=31,
        )  # dry_run غير مُمرَّر ⇒ الافتراضي True
        self.assertEqual(res["action"], "DRY_RUN")
        self.assertFalse(res["placed"])
        self.assertEqual(client.placed, [])
        self.assertEqual(client.cancelled, [])


class BuildManualExitFnTests(unittest.TestCase):
    """محوّل الواجهة: callable أحادي يقرأ الحالة/المختار ثم ينفّذ (fail-safe)."""

    def test_fn_reads_providers_and_places(self):
        client = FakeMarketExitClient(free="1.0", resting=())
        state = SimpleNamespace(reference_price=Decimal("70000"), target_order_list_id=31, selected_oco=None)
        selected = SimpleNamespace(symbol="BTCUSDT", quantity=Decimal("0.5"), order_list_id=31, current_price=Decimal("70000"))
        fn = build_manual_exit_fn(
            exit_broker=client,
            state_provider=lambda: state,
            selected_provider=lambda: selected,
            filters_fn=lambda s: _filters(),
            base_asset_fn=lambda s: "BTC",
            exit_side="upper",
            dry_run=False,
        )
        res = fn()
        self.assertEqual(res["action"], "PLACED")
        self.assertEqual(len(client.placed), 1)

    def test_fn_no_selection_is_safe(self):
        client = FakeMarketExitClient()
        fn = build_manual_exit_fn(
            exit_broker=client,
            state_provider=lambda: SimpleNamespace(selected_oco=None),
            selected_provider=lambda: None,
            filters_fn=lambda s: _filters(),
            base_asset_fn=lambda s: "BTC",
        )
        res = fn()
        self.assertEqual(res["action"], "ABORT_NO_SELECTION")
        self.assertEqual(client.placed, [])


class ManualExitPriorityOverFourMeansTests(unittest.TestCase):
    """(ج) الأولوية البنيوية: بعد الخروج تصبح الوسائل الأربع idempotent (NOOP)."""

    def _snap(self, *, has_resting, free, monitored):
        return GuardianSnapshot(
            symbol="BTCUSDT",
            state="MONITORING_ACTIVE",
            in_flight=False,
            naked_seconds=0.0,
            has_resting_protective_sell=has_resting,
            free_base_qty=free,
            monitored_qty=monitored,
        )

    def test_guardian_noop_when_resting_sell_present(self):
        # بعد خروج يدوي بأمر LIMIT ⇒ يوجد بيع حمائي قائم ⇒ الحارس NOOP.
        d = evaluate(self._snap(has_resting=True, free=Decimal("0.5"), monitored=Decimal("0.5")), GuardianConfig())
        self.assertEqual(d.action, GuardianAction.NOOP)
        # نفس القيد في بوّابة الخروج اليدوي:
        self.assertFalse(
            manual_exit_safety_gate(
                has_resting_protective_sell=True,
                free_base_qty=Decimal("0.5"),
                monitored_qty=Decimal("0.5"),
            )["allowed"]
        )

    def test_guardian_noop_when_position_closed_free_zero(self):
        # بعد ملء الخروج ⇒ الرصيد الحرّ صفر ⇒ الحارس NOOP (لا سباق منفّذات).
        d = evaluate(self._snap(has_resting=False, free=Decimal("0"), monitored=Decimal("0.5")), GuardianConfig())
        self.assertEqual(d.action, GuardianAction.NOOP)
        self.assertFalse(
            manual_exit_safety_gate(
                has_resting_protective_sell=False,
                free_base_qty=Decimal("0"),
                monitored_qty=Decimal("0.5"),
            )["allowed"]
        )


class ManualExitBilingualTests(unittest.TestCase):
    """(د) §1.5 — تسمية الزرّ ثنائية اللغة."""

    def setUp(self):
        self.addCleanup(i18n.set_language, "ar")

    def test_button_label_bilingual(self):
        self.assertIn("تنفيذ الخروج الفوري", i18n.AR_TO_EN)
        self.assertEqual(i18n.AR_TO_EN["تنفيذ الخروج الفوري"], "Execute Immediate Exit")

        i18n.set_language("en")
        self.assertEqual(i18n.translate("تنفيذ الخروج الفوري"), "Execute Immediate Exit")
        # ثنائي الاتجاه: السلسلة الإنجليزية تبقى إنجليزية.
        self.assertEqual(i18n.translate("Execute Immediate Exit"), "Execute Immediate Exit")

        i18n.set_language("ar")
        self.assertEqual(i18n.translate("تنفيذ الخروج الفوري"), "تنفيذ الخروج الفوري")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
