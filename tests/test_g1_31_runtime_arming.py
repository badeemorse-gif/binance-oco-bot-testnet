# -*- coding: utf-8 -*-
"""G1.31 / chunk_5a: تسليح الحارس وقت التشغيل من الواجهة (بلا متغيّر بيئة OCOBOT_GUARDIAN).

يُعيد إنتاج العطل الذي أبلغ به المستخدم أثناء المراقبة الديناميكية: اختيار «مراقبة»
في المُبدِّل لم يكن يفعل شيئًا لأن المُشرِف كان None (لم يُضبط OCOBOT_GUARDIAN عند الإقلاع).
بعد الإصلاح: مسار إضافي يبني مُشرِفًا خاملًا للمحوّل فيصبح المُبدِّل قادرًا على التسليح/الإطفاء
وقت التشغيل، مع بقاء OFF كبحًا صلبًا (لا tick ولا تدخّل).
"""
import os
import unittest

from ocobot.domain.guardian import GuardianAction
from ocobot.domain.guardian_status import (
    GuardianMode,
    GuardianStatusStore,
    GuardianUiState,
)
from ocobot.ui.guardian_wiring import GuardianStatusAdapter


class _FakeDecision:
    def __init__(self, action):
        self.action = action
        self.reason = ""
        self.protective_qty = None


class _FakeSupervisor:
    """مُشرِف وهمي يسجّل عدد الاستدعاءات ويحاكي dry_run/_armed/last_result."""

    def __init__(self):
        self.ticks = 0
        self.dry_run = True
        self._armed = False
        self.last_decision = None
        self.last_result = {}

    def tick(self):
        self.ticks += 1
        return _FakeDecision(GuardianAction.WAIT)


class RuntimeArmingBuilderTests(unittest.TestCase):
    """الباني الإضافي يُنتج مُشرِفًا حتى بلا OCOBOT_GUARDIAN، دون تغيير سلوك المختوم."""

    def setUp(self):
        self._old = os.environ.pop("OCOBOT_GUARDIAN", None)

    def tearDown(self):
        if self._old is not None:
            os.environ["OCOBOT_GUARDIAN"] = self._old

    def test_sealed_builder_returns_none_when_env_off(self):
        from ocobot.ui.guardian_arm import build_guardian_supervisor
        self.assertIsNone(build_guardian_supervisor(lambda: None))

    def test_ui_builder_returns_inert_supervisor_when_env_off(self):
        # يفشل قبل الإصلاح (الدالة غير موجودة) ويخضرّ بعده.
        from ocobot.ui.guardian_arm import build_guardian_supervisor_for_ui
        sup = build_guardian_supervisor_for_ui(lambda: None)
        self.assertIsNotNone(sup)
        self.assertTrue(hasattr(sup, "tick"))
        self.assertIs(getattr(sup, "dry_run", None), True)


class RuntimeArmingAdapterTests(unittest.TestCase):
    """المحوّل مع مُشرِف حاضر: OFF كبح صلب؛ Observe/Live يُسلّحان وقت التشغيل."""

    def _mk(self, mode, sup):
        box = {"m": mode}
        store = GuardianStatusStore()
        adapter = GuardianStatusAdapter(
            supervisor=sup, store=store, mode_getter=lambda: box["m"]
        )
        return adapter, store, box

    def test_off_is_hard_stop_no_tick(self):
        sup = _FakeSupervisor()
        adapter, store, _ = self._mk(GuardianMode.OFF, sup)
        adapter.tick()
        self.assertEqual(sup.ticks, 0)
        self.assertIs(store.status.state, GuardianUiState.DISABLED)
        self.assertIs(store.status.mode, GuardianMode.OFF)

    def test_observe_arms_at_runtime_from_off(self):
        sup = _FakeSupervisor()
        adapter, store, box = self._mk(GuardianMode.OFF, sup)
        adapter.tick()                      # OFF: لا شيء
        self.assertEqual(sup.ticks, 0)
        box["m"] = GuardianMode.OBSERVE     # المستخدم يختار «مراقبة» وقت التشغيل
        adapter.tick()
        self.assertEqual(sup.ticks, 1)
        self.assertTrue(sup.dry_run)
        self.assertIs(store.status.mode, GuardianMode.OBSERVE)
        self.assertIsNot(store.status.state, GuardianUiState.DISABLED)

    def test_live_sets_dry_run_false(self):
        sup = _FakeSupervisor()
        adapter, store, _ = self._mk(GuardianMode.LIVE, sup)
        adapter.tick()
        self.assertEqual(sup.ticks, 1)
        self.assertFalse(sup.dry_run)

    def test_back_to_off_stops_again(self):
        sup = _FakeSupervisor()
        adapter, store, box = self._mk(GuardianMode.OBSERVE, sup)
        adapter.tick()
        self.assertEqual(sup.ticks, 1)
        box["m"] = GuardianMode.OFF
        adapter.tick()
        self.assertEqual(sup.ticks, 1)      # لم يُستدعَ مجددًا — كبح صلب
        self.assertIs(store.status.state, GuardianUiState.DISABLED)


if __name__ == "__main__":
    unittest.main()
