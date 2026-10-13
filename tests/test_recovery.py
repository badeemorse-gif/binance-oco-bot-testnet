import unittest
from decimal import Decimal

from ocobot.domain.monitoring import MonitoringState, MonitoringStateEnum, MonitoringEngine
from ocobot.domain.recovery import recover, RecoveryDecision, _reconstruct_state, _is_open
from ocobot.core.state_store import MonitoringCheckpoint
from ocobot.core.errors import OcoBotError

from tests._fakes_monitoring import FakeSelectedOCO, FakeSafeExecutor


class _FakeStore:
    def __init__(self, persisted): self._p = persisted; self.saved = []
    def load(self, *, strict=False): return self._p
    def save(self, ps): self.saved.append(ps); return ps

class _FakePersisted:
    def __init__(self, cp): self.monitoring = cp; self.selected_oco=None; self.logs=None; self.schema_version=1; self.saved_at=None

class _FakeOco:
    def __init__(self, order_list_id, status): self.order_list_id=order_list_id; self.status=status

class _FakeReader:
    def __init__(self, oco=None, exc=None): self._oco=oco; self._exc=exc; self.calls=[]
    def get_oco(self, order_list_id):
        self.calls.append(order_list_id)
        if self._exc is not None: raise self._exc
        return self._oco

def _make_state(order_list_id="123", enabled=True, state=MonitoringStateEnum.MONITORING_ACTIVE):
    s = MonitoringState()
    s.enabled = enabled; s.state = state; s.symbol = "BTCUSDT"
    s.target_order_list_id = order_list_id
    s.reference_price = Decimal("50000.00"); s.trigger_pct = Decimal("1.5")
    s.tp_pct = Decimal("2.0"); s.sl_pct = Decimal("1.0")
    s.latched = True; s.in_flight = False
    s.tolerance_pct = Decimal("0.1"); s.guard_pct = Decimal("0.5")
    s.last_price = Decimal("49950.00"); s.cursor = 7
    return s

def _persisted_for(state): return _FakePersisted(MonitoringCheckpoint.from_state(state))


def _assert_state_equiv(tc, actual, expected):
    if actual == expected:
        tc.assertEqual(actual, expected)
        return
    tc.assertEqual(str(actual.reference_price), str(expected.reference_price))
    tc.assertEqual(actual.state, expected.state)
    tc.assertEqual(actual.target_order_list_id, expected.target_order_list_id)
    tc.assertEqual(actual.cursor, expected.cursor)
    tc.assertEqual(actual.latched, expected.latched)
    tc.assertEqual(actual.in_flight, expected.in_flight)


class RecoveryTests(unittest.TestCase):

    def test_resume_from_saved_state(self):
        s = _make_state("123")
        store = _FakeStore(_persisted_for(s))
        reader = _FakeReader(_FakeOco("123", "EXECUTING"))
        res = recover(store, reader)
        self.assertIs(res.decision, RecoveryDecision.RESUME)
        self.assertEqual(reader.calls, ["123"])
        self.assertEqual(store.saved, [])
        reconstructed = _reconstruct_state(MonitoringCheckpoint.from_state(s))
        _assert_state_equiv(self, reconstructed, s)
        _assert_state_equiv(self, res.state, s)

    def test_halt_when_oco_closed_externally(self):
        store = _FakeStore(_persisted_for(_make_state("123")))
        reader = _FakeReader(_FakeOco("123", "ALL_DONE"))
        res = recover(store, reader)
        self.assertIs(res.decision, RecoveryDecision.HALT_EXTERNALLY_CLOSED)
        self.assertIsInstance(res.alert, str)
        self.assertTrue(res.alert.strip())
        self.assertEqual(store.saved, [])
        self.assertEqual(reader.calls, ["123"])

        reader2 = _FakeReader(exc=OcoBotError("not found"))
        res2 = recover(_FakeStore(_persisted_for(_make_state("123"))), reader2)
        self.assertIs(res2.decision, RecoveryDecision.HALT_EXTERNALLY_CLOSED)
        self.assertTrue(res2.alert and res2.alert.strip())
        self.assertEqual(reader2.calls, ["123"])

    def test_no_blind_write_match_first(self):
        store = _FakeStore(_persisted_for(_make_state("123")))
        reader = _FakeReader(_FakeOco("999", "EXECUTING"))
        res = recover(store, reader)
        self.assertIs(res.decision, RecoveryDecision.HALT_EXTERNALLY_CLOSED)
        self.assertEqual(reader.calls, ["123"])
        self.assertEqual(store.saved, [])

    def test_nothing_to_resume(self):
        store = _FakeStore(None)
        reader = _FakeReader(_FakeOco("123", "EXECUTING"))
        res = recover(store, reader)
        self.assertIs(res.decision, RecoveryDecision.NOTHING_TO_RESUME)
        self.assertEqual(reader.calls, [])

        s = _make_state("123", enabled=False)
        r = _FakeReader(_FakeOco("123", "EXECUTING"))
        res = recover(_FakeStore(_persisted_for(s)), r)
        self.assertIs(res.decision, RecoveryDecision.NOTHING_TO_RESUME)
        self.assertEqual(r.calls, [])

        s2 = _make_state("", enabled=True)
        r2 = _FakeReader()
        res = recover(_FakeStore(_persisted_for(s2)), r2)
        self.assertIs(res.decision, RecoveryDecision.NOTHING_TO_RESUME)
        self.assertEqual(r2.calls, [])

    def test_checkpoint_saved_on_each_transition(self):
        recorded = []
        sink = lambda st: recorded.append(st.state)
        ex = FakeSafeExecutor()
        engine = MonitoringEngine(ex, checkpoint_sink=sink)

        len_before = len(recorded)
        engine.start(FakeSelectedOCO(), trigger_pct="1", tp_pct="4", sl_pct="2",
                     reference_price="100")
        self.assertGreater(len(recorded), len_before)

        n = len(recorded)
        engine.pause()
        self.assertEqual(len(recorded), n + 1)
        self.assertEqual(recorded[-1], engine.state.state)

        n = len(recorded)
        engine.resume()
        self.assertEqual(len(recorded), n + 1)
        self.assertEqual(recorded[-1], engine.state.state)

        n = len(recorded)
        engine.kill_switch()
        self.assertEqual(len(recorded), n + 1)
        self.assertEqual(recorded[-1], engine.state.state)

        self.assertEqual(recorded[-1], engine.state.state)

    def test_no_secrets_in_checkpoint(self):
        d = MonitoringCheckpoint.from_state(_make_state()).to_dict()
        banned = ('secret', 'api_key', 'apikey', 'signature', 'token', 'password')
        keys = []

        def _flatten(obj):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    keys.append(str(k))
                    _flatten(v)
            elif isinstance(obj, (list, tuple)):
                for v in obj:
                    _flatten(v)

        _flatten(d)
        for k in keys:
            lk = k.lower()
            for b in banned:
                self.assertNotIn(b, lk)


if __name__ == "__main__":
    unittest.main()
