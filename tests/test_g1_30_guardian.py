"""اختبارات G1.30 (chunk_1) — منطق شبكة أمان المركز الخالص (guardian.py).

وحدة خالصة بلا شبكة/أوامر/IO؛ تُختبر بتغذية لقطات ساكنة فقط. تغطّي بنود القرار:
  - بيع حمائي قائم ⇒ NOOP (منع البيع المزدوج) حتى مع عُري ضخم وكمية حرّة.
  - رصيد حرّ = 0 (مقفول) ⇒ NOOP.
  - كمية مُراقَبة = 0 (لا مركز) ⇒ NOOP (qty مقصورة عند 0).
  - FAILED_NEEDS_ATTENTION + عارٍ + كمية حرّة ⇒ INTERVENE بـ min(free, monitored).
  - in_flight صحّي (naked_seconds < threshold) ⇒ WAIT.
  - naked_seconds >= threshold ⇒ INTERVENE.
  - naked_seconds أسفل العتبة بقليل، لا in_flight ولا failed ⇒ WAIT ("below threshold").
  - protective_qty = min(free, monitored) في حالتَي التدخّل (free<monitored و monitored<free).
"""
import unittest
from decimal import Decimal

from ocobot.domain.guardian import (
    GuardianAction,
    GuardianConfig,
    GuardianDecision,
    GuardianSnapshot,
    evaluate,
)


def _snap(**overrides):
    """لقطة أساس «عارية مع كمية حرّة»؛ تُعدَّل بالكلمات المفتاحية حسب الحالة."""
    base = dict(
        symbol="ETHUSDT",
        state="MONITORING",
        in_flight=False,
        naked_seconds=10.0,
        has_resting_protective_sell=False,
        free_base_qty=Decimal("5"),
        monitored_qty=Decimal("5"),
    )
    base.update(overrides)
    return GuardianSnapshot(**base)


class TestGuardianDoubleSellGuard(unittest.TestCase):
    def test_resting_sell_present_always_noop(self):
        cfg = GuardianConfig()
        # حتى مع عُري ضخم وكمية حرّة وحالة فشل: البيع القائم يمنع التدخّل.
        snap = _snap(
            has_resting_protective_sell=True,
            naked_seconds=9999.0,
            state="FAILED_NEEDS_ATTENTION",
            free_base_qty=Decimal("3"),
            monitored_qty=Decimal("3"),
        )
        dec = evaluate(snap, cfg)
        self.assertIsInstance(dec, GuardianDecision)
        self.assertEqual(dec.action, GuardianAction.NOOP)
        self.assertEqual(dec.protective_qty, Decimal("0"))
        self.assertEqual(dec.reason, "protected: resting sell present")


class TestGuardianNoProtectableQty(unittest.TestCase):
    def test_free_balance_locked_zero_noop(self):
        cfg = GuardianConfig()
        snap = _snap(free_base_qty=Decimal("0"), monitored_qty=Decimal("5"))
        dec = evaluate(snap, cfg)
        self.assertEqual(dec.action, GuardianAction.NOOP)
        self.assertEqual(dec.protective_qty, Decimal("0"))
        self.assertEqual(
            dec.reason, "no free protectable qty (locked or no position)"
        )

    def test_no_position_monitored_zero_noop(self):
        cfg = GuardianConfig()
        # حيازات غير متعلقة فقط: الرصيد الحرّ موجود لكن المُراقَب صفر ⇒ qty=0.
        snap = _snap(free_base_qty=Decimal("5"), monitored_qty=Decimal("0"))
        dec = evaluate(snap, cfg)
        self.assertEqual(dec.action, GuardianAction.NOOP)
        self.assertEqual(dec.protective_qty, Decimal("0"))
        self.assertEqual(
            dec.reason, "no free protectable qty (locked or no position)"
        )


class TestGuardianIntervene(unittest.TestCase):
    def test_failed_needs_attention_intervenes(self):
        cfg = GuardianConfig()
        # ناكِد قليلًا (أسفل العتبة) لكنه فاشل ⇒ تدخّل فوري بصرف النظر عن العتبة.
        snap = _snap(
            state="FAILED_NEEDS_ATTENTION",
            naked_seconds=0.5,
            free_base_qty=Decimal("4"),
            monitored_qty=Decimal("7"),
        )
        dec = evaluate(snap, cfg)
        self.assertEqual(dec.action, GuardianAction.INTERVENE)
        self.assertEqual(dec.protective_qty, Decimal("4"))  # min(4, 7)
        self.assertEqual(dec.reason, "failed_needs_attention")

    def test_naked_beyond_threshold_intervenes(self):
        cfg = GuardianConfig(threshold_seconds=4.0)
        snap = _snap(naked_seconds=4.0, in_flight=False)
        dec = evaluate(snap, cfg)
        self.assertEqual(dec.action, GuardianAction.INTERVENE)
        self.assertEqual(dec.protective_qty, Decimal("5"))
        self.assertEqual(dec.reason, "naked beyond threshold")

    def test_in_flight_but_beyond_threshold_intervenes(self):
        # حتى لو كان in_flight، تجاوز العتبة يفرض التدخّل.
        cfg = GuardianConfig(threshold_seconds=4.0)
        snap = _snap(naked_seconds=10.0, in_flight=True)
        dec = evaluate(snap, cfg)
        self.assertEqual(dec.action, GuardianAction.INTERVENE)
        self.assertEqual(dec.reason, "naked beyond threshold")

    def test_protective_qty_free_less_than_monitored(self):
        cfg = GuardianConfig(threshold_seconds=4.0)
        snap = _snap(
            naked_seconds=100.0,
            free_base_qty=Decimal("2.5"),
            monitored_qty=Decimal("9"),
        )
        dec = evaluate(snap, cfg)
        self.assertEqual(dec.action, GuardianAction.INTERVENE)
        self.assertEqual(dec.protective_qty, Decimal("2.5"))  # min(2.5, 9)

    def test_protective_qty_monitored_less_than_free(self):
        cfg = GuardianConfig(threshold_seconds=4.0)
        snap = _snap(
            naked_seconds=100.0,
            free_base_qty=Decimal("9"),
            monitored_qty=Decimal("1.25"),
        )
        dec = evaluate(snap, cfg)
        self.assertEqual(dec.action, GuardianAction.INTERVENE)
        self.assertEqual(dec.protective_qty, Decimal("1.25"))  # min(9, 1.25)


class TestGuardianWait(unittest.TestCase):
    def test_in_flight_healthy_waits(self):
        cfg = GuardianConfig(threshold_seconds=4.0)
        snap = _snap(in_flight=True, naked_seconds=1.5)
        dec = evaluate(snap, cfg)
        self.assertEqual(dec.action, GuardianAction.WAIT)
        self.assertEqual(dec.protective_qty, Decimal("0"))
        self.assertEqual(dec.reason, "healthy reposition in progress")

    def test_below_threshold_not_in_flight_waits(self):
        cfg = GuardianConfig(threshold_seconds=4.0)
        # أسفل العتبة بقليل، ليس in_flight، وليس فاشلًا ⇒ WAIT "below threshold".
        snap = _snap(in_flight=False, naked_seconds=3.999, state="MONITORING")
        dec = evaluate(snap, cfg)
        self.assertEqual(dec.action, GuardianAction.WAIT)
        self.assertEqual(dec.protective_qty, Decimal("0"))
        self.assertEqual(dec.reason, "below threshold")


class TestGuardianConfigDefaults(unittest.TestCase):
    def test_defaults(self):
        cfg = GuardianConfig()
        self.assertEqual(cfg.threshold_seconds, 4.0)
        self.assertEqual(cfg.emergency_sl_pct, Decimal("1.0"))


if __name__ == "__main__":
    unittest.main()
