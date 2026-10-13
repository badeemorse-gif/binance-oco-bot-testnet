"""اختبارات نموذج حالة الحارس للعرض (G1.31 / chunk_1)."""
import unittest

from ocobot.domain.guardian_status import (
    GuardianMode,
    GuardianStatus,
    GuardianStatusStore,
    GuardianUiState,
    LastAction,
)


class GuardianStatusModelTests(unittest.TestCase):
    def test_default_status_is_off_disabled(self):
        s = GuardianStatus()
        self.assertEqual(s.mode, GuardianMode.OFF)
        self.assertEqual(s.state, GuardianUiState.DISABLED)
        self.assertIsNone(s.last_action)

    def test_enum_string_values(self):
        self.assertEqual(GuardianMode.OFF.value, "off")
        self.assertEqual(GuardianMode.OBSERVE.value, "observe")
        self.assertEqual(GuardianMode.LIVE.value, "live")
        self.assertEqual(GuardianUiState.SLEEPING.value, "sleeping")
        self.assertEqual(GuardianUiState.WATCHING.value, "watching")
        self.assertEqual(GuardianUiState.INTERVENED.value, "intervened")

    def test_store_set_and_get(self):
        store = GuardianStatusStore()
        new = GuardianStatus(
            mode=GuardianMode.LIVE, state=GuardianUiState.SLEEPING, updated_at="t1"
        )
        store.set(new)
        self.assertEqual(store.status.mode, GuardianMode.LIVE)
        self.assertEqual(store.status.state, GuardianUiState.SLEEPING)
        self.assertEqual(store.status.updated_at, "t1")

    def test_subscribe_gets_immediate_and_updates(self):
        store = GuardianStatusStore()
        seen = []
        store.subscribe(lambda s: seen.append(s.state))
        # إشعار فوري بالحالة الحالية (DISABLED).
        self.assertEqual(seen[-1], GuardianUiState.DISABLED)
        store.update(state=GuardianUiState.WATCHING, updated_at="t2")
        self.assertEqual(seen[-1], GuardianUiState.WATCHING)
        self.assertEqual(store.status.updated_at, "t2")

    def test_unsubscribe_stops_updates(self):
        store = GuardianStatusStore()
        seen = []
        off = store.subscribe(lambda s: seen.append(s.state))
        off()
        store.update(state=GuardianUiState.INTERVENED)
        # بعد إلغاء الاشتراك يبقى الإشعار الفوري الأول فقط.
        self.assertEqual(seen, [GuardianUiState.DISABLED])

    def test_intervened_captures_last_action(self):
        store = GuardianStatusStore()
        la = LastAction(
            ts="2026-10-10T00:00:00Z",
            action="placed_protective_stop",
            reason="naked_timeout",
            qty="1.5",
            price="100.00",
        )
        store.update(mode=GuardianMode.LIVE, state=GuardianUiState.INTERVENED, last_action=la)
        self.assertEqual(store.status.state, GuardianUiState.INTERVENED)
        self.assertEqual(store.status.last_action.qty, "1.5")
        self.assertEqual(store.status.last_action.price, "100.00")
        self.assertEqual(store.status.last_action.reason, "naked_timeout")

    def test_failing_listener_does_not_break_others(self):
        store = GuardianStatusStore()
        seen = []

        def bad(_s):
            raise RuntimeError("boom")

        store.subscribe(bad)
        store.subscribe(lambda s: seen.append(s.state))
        store.update(state=GuardianUiState.SLEEPING)
        self.assertEqual(seen[-1], GuardianUiState.SLEEPING)


if __name__ == "__main__":
    unittest.main()
