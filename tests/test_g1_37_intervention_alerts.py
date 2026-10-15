"""G1.37 — tests for emit-only intervention Telegram alerts (no network, no Qt).

Follows the style of test_g1_25_alerts.py / test_g1_36_reposition_fields.py:
simple fake Notifier with ``enqueue`` collecting messages, and a fake store with
``enabled_provider()``. Covers message builders, format_event routing, the emit
adapters, and the emit-only wiring at both intervention points.
"""
import unittest
from decimal import Decimal
from types import SimpleNamespace

from ocobot.alerts.formatting import (
    build_guardian_message,
    build_market_exit_message,
    format_event,
)
from ocobot.alerts.bridge import (
    guardian_record,
    market_exit_record,
    make_guardian_notifier,
    make_market_exit_notifier,
)
from ocobot.domain.guardian_exec import place_protective_stop
from ocobot.domain.models import SymbolFilters
from ocobot.domain.bracket import BracketConfig
from ocobot.ui.bracket_wiring import BracketExitWiring
from ocobot.core.market_exit_broker import MarketExitBroker


# ---------------------------------------------------------------------------
# fakes (mirroring the existing alerts tests)
# ---------------------------------------------------------------------------
class _FakeNotifier:
    def __init__(self):
        self.texts = []

    def enqueue(self, text, **kwargs):
        self.texts.append(text)
        return True


class _RaisingNotifier:
    def __init__(self):
        self.texts = []

    def enqueue(self, text, **kwargs):
        raise RuntimeError("enqueue boom")


class _FakeStore:
    def __init__(self, enabled=True):
        self._enabled = enabled

    def enabled_provider(self):
        return self._enabled


# ---- guardian fakes (ProtectiveStopClient contract) -----------------------
class _FakeGuardianClient:
    def __init__(self, open_orders=None, free="0"):
        self._open_orders = list(open_orders or [])
        self._free = Decimal(str(free))
        self.place_calls = []

    def get_open_sell_orders(self, symbol):
        return list(self._open_orders)

    def get_free_asset_qty(self, asset):
        return self._free

    def place_stop_loss_limit(self, symbol, quantity, stop_price,
                              limit_price, client_order_id):
        self.place_calls.append({
            "symbol": symbol, "quantity": quantity, "stop_price": stop_price,
            "limit_price": limit_price, "client_order_id": client_order_id,
        })
        return {"orderId": 4242, "status": "NEW", "clientOrderId": client_order_id}


def _gfilters(symbol="ETHUSDT"):
    return SimpleNamespace(
        symbol=symbol, tick_size=Decimal("0.01"), step_size=Decimal("0.001"),
        min_qty=Decimal("0.001"), min_notional=Decimal("10"),
    )


def _placed_guardian_result():
    """Produce a real PLACED guardian result (dry_run=False) via a fake client."""
    client = _FakeGuardianClient(open_orders=[], free="5")
    return place_protective_stop(
        client, "ETHUSDT", "ETH",
        reference_price=Decimal("100"), qty=Decimal("5"),
        emergency_sl_pct=Decimal("1"), filters=_gfilters(),
        client_order_id="grd-xyz-1", dry_run=False,
    )


# ---- bracket wiring fakes (as in test_g1_32b_wiring.py) -------------------
class _FakeRest:
    def __init__(self, free="100", open_orders=None, order_response=None):
        self._free = str(free)
        self._open = open_orders if open_orders is not None else []
        self._order_response = order_response or {"orderId": 7777, "status": "NEW"}
        self.calls = []

    def get_open_orders(self, symbol=None):
        self.calls.append(("open_orders", symbol))
        return list(self._open)

    def get_account(self):
        return {"balances": [{"asset": "LSK", "free": self._free, "locked": "0"}]}

    def signed_request(self, method, path, params=None):
        self.calls.append((method, path, dict(params or [])))
        if method == "POST":
            return dict(self._order_response)
        return {"ok": True, "method": method, "path": path}


def _xfilters(symbol):
    return SymbolFilters(symbol=symbol, tick_size=Decimal("0.0001"),
                         step_size=Decimal("0.01"), min_qty=Decimal("0.1"),
                         min_notional=Decimal("5"))


def _wiring(rest, *, notifier=None, enabled=True, lower="1.0", upper="2.0",
            price="2.0", dry_run=False, selected=True):
    sel = SimpleNamespace(symbol="LSKUSDT", order_list_id=136428,
                          quantity=Decimal("50")) if selected else None
    return BracketExitWiring(
        broker=MarketExitBroker(rest),
        config_getter=lambda: BracketConfig.from_inputs(enabled, lower, upper),
        price_getter=lambda: price,
        selected_getter=lambda: sel,
        filters_fn=_xfilters,
        base_asset_fn=lambda s: "LSK",
        dry_run_getter=lambda: dry_run,
        notifier=notifier,
    )


# ---------------------------------------------------------------------------
# (1) message builders — full and sparse records
# ---------------------------------------------------------------------------
class TestGuardianBuilder(unittest.TestCase):
    def test_full_record_contains_all_fields(self):
        record = {
            "event": "guardian_intervention",
            "ts": "2026-10-11T21:00:00Z",
            "details": {
                "symbol": "ETHUSDT",
                "reason": "naked beyond threshold",
                "action": "PLACED",
                "eff_qty": "5",
                "reference_price": "100",
                "emergency_sl_pct": "1",
                "naked_seconds": "6",
                "client_order_id": "grd-xyz-1",
                "plan": {
                    "quantity": "5", "stop_trigger": "99", "stop_price": "99",
                    "limit_price": "98.9",
                },
                "response": {"orderId": 4242, "clientOrderId": "grd-xyz-1"},
            },
        }
        msg = build_guardian_message(record)
        self.assertIn("🛡️", msg)
        self.assertIn("ETHUSDT", msg)        # symbol
        self.assertIn("naked", msg)          # reason
        self.assertIn("5", msg)              # quantity
        self.assertIn("99", msg)             # stop trigger price
        self.assertIn("98", msg)             # stop limit price
        self.assertIn("grd", msg)            # client order id
        self.assertIn("4242", msg)           # order id from response
        self.assertIn("2026", msg)           # time

    def test_sparse_record_is_nonempty_and_safe(self):
        msg = build_guardian_message({"event": "guardian_intervention",
                                      "details": {"symbol": "BTCUSDT"}})
        self.assertTrue(msg)
        self.assertIn("🛡️", msg)
        self.assertIn("BTCUSDT", msg)

    def test_empty_record_never_raises(self):
        self.assertTrue(build_guardian_message({}))
        self.assertTrue(build_guardian_message(None))


class TestMarketExitBuilder(unittest.TestCase):
    def test_full_record_contains_all_fields(self):
        record = {
            "event": "market_exit",
            "ts": "2026-10-11T22:30:00Z",
            "details": {
                "symbol": "LSKUSDT",
                "exit_side": "upper",
                "action": "PLACED",
                "eff_qty": "50",
                "reference_price": "2",
                "client_order_id": "bexit-upper-1",
                "plan": {
                    "quantity": "50", "type": "LIMIT", "stop_price": "1.9",
                    "limit_price": "1.95", "price": "1.998", "price_floor": "1.84",
                },
                "response": {"orderId": 7777},
            },
        }
        msg = build_market_exit_message(record)
        self.assertIn("🧷", msg)             # G1.57: الرأس المميّز الموحّد
        self.assertIn("LSKUSDT", msg)        # symbol
        self.assertIn("upper", msg)          # exit side
        self.assertIn("Entry:", msg)         # G1.57: حقل Entry القياسي
        self.assertIn("Exit price:", msg)    # G1.57: حقل Exit price القياسي
        self.assertIn("PnL%:", msg)          # G1.57: حقل PnL% القياسي
        self.assertIn("50", msg)             # quantity
        self.assertIn("LIMIT", msg)          # order type
        self.assertIn("1", msg)              # some price digit
        self.assertIn("bexit", msg)          # client order id
        self.assertIn("7777", msg)           # order id from response
        self.assertIn("2026", msg)           # time

    def test_sparse_record_is_nonempty_and_safe(self):
        msg = build_market_exit_message({"event": "market_exit",
                                         "details": {"symbol": "LSKUSDT"}})
        self.assertTrue(msg)
        self.assertIn("🧷", msg)
        self.assertIn("LSKUSDT", msg)

    def test_empty_record_never_raises(self):
        self.assertTrue(build_market_exit_message({}))
        self.assertTrue(build_market_exit_message(None))


# ---------------------------------------------------------------------------
# (2) format_event routing
# ---------------------------------------------------------------------------
class TestFormatEventRouting(unittest.TestCase):
    def test_routes_guardian(self):
        msg = format_event({"event": "guardian_intervention",
                            "details": {"symbol": "ETHUSDT"}})
        self.assertIsNotNone(msg)
        self.assertIn("🛡️", msg)

    def test_routes_market_exit(self):
        msg = format_event({"event": "market_exit",
                            "details": {"symbol": "LSKUSDT"}})
        self.assertIsNotNone(msg)
        self.assertIn("🧷", msg)

    def test_unknown_event_returns_none(self):
        self.assertIsNone(format_event({"event": "something_else"}))


# ---------------------------------------------------------------------------
# (3) record builders (bridge helpers)
# ---------------------------------------------------------------------------
class TestRecordBuilders(unittest.TestCase):
    def test_guardian_record_shape(self):
        result = _placed_guardian_result()
        rec = guardian_record(symbol="ETHUSDT", reason="naked beyond threshold",
                              result=result, reference_price=Decimal("100"),
                              emergency_sl_pct=Decimal("1"), naked_seconds=6.0)
        self.assertEqual(rec["event"], "guardian_intervention")
        d = rec["details"]
        self.assertEqual(d["symbol"], "ETHUSDT")
        self.assertEqual(d["action"], "PLACED")
        self.assertEqual(d["client_order_id"], "grd-xyz-1")
        self.assertEqual(d["plan"]["type"], "STOP_LOSS_LIMIT")
        self.assertEqual(d["response"]["orderId"], 4242)

    def test_market_exit_record_shape(self):
        result = {
            "action": "PLACED", "symbol": "LSKUSDT", "exit_side": "upper",
            "eff_qty": Decimal("50"), "client_order_id": "bexit-upper-1",
            "plan": {"type": "LIMIT", "quantity": Decimal("50"),
                     "price": Decimal("1.998"), "reference_price": Decimal("2")},
            "response": {"orderId": 7777},
        }
        rec = market_exit_record(result)
        self.assertEqual(rec["event"], "market_exit")
        d = rec["details"]
        self.assertEqual(d["symbol"], "LSKUSDT")
        self.assertEqual(d["exit_side"], "upper")
        self.assertEqual(d["type"], "LIMIT")
        self.assertEqual(d["response"]["orderId"], 7777)

    def test_builders_never_raise_on_garbage(self):
        self.assertEqual(guardian_record(symbol="X", reason=None, result=None)["event"],
                         "guardian_intervention")
        self.assertEqual(market_exit_record(None)["event"], "market_exit")


# ---------------------------------------------------------------------------
# (4) emit adapters — enabled, disabled, raising
# ---------------------------------------------------------------------------
class TestGuardianNotifier(unittest.TestCase):
    def test_placed_enqueues_once(self):
        notifier, store = _FakeNotifier(), _FakeStore(enabled=True)
        emit = make_guardian_notifier(notifier=notifier, store=store)
        result = _placed_guardian_result()
        emit({"symbol": "ETHUSDT", "reason": "naked beyond threshold",
              "result": result, "reference_price": Decimal("100"),
              "emergency_sl_pct": Decimal("1"), "naked_seconds": 6.0})
        self.assertEqual(len(notifier.texts), 1)
        self.assertIn("🛡️", notifier.texts[0])
        self.assertIn("ETHUSDT", notifier.texts[0])
        self.assertIn("4242", notifier.texts[0])

    def test_disabled_store_does_not_enqueue(self):
        notifier, store = _FakeNotifier(), _FakeStore(enabled=False)
        emit = make_guardian_notifier(notifier=notifier, store=store)
        emit({"symbol": "ETHUSDT", "reason": "r", "result": _placed_guardian_result()})
        self.assertEqual(len(notifier.texts), 0)

    def test_raising_enqueue_is_swallowed(self):
        emit = make_guardian_notifier(notifier=_RaisingNotifier(),
                                      store=_FakeStore(enabled=True))
        # must not propagate
        emit({"symbol": "ETHUSDT", "reason": "r", "result": _placed_guardian_result()})


class TestMarketExitNotifier(unittest.TestCase):
    def _result(self):
        return {
            "action": "PLACED", "symbol": "LSKUSDT", "exit_side": "upper",
            "eff_qty": Decimal("50"), "client_order_id": "bexit-upper-1",
            "plan": {"type": "LIMIT", "quantity": Decimal("50"),
                     "price": Decimal("1.998")},
            "response": {"orderId": 7777},
        }

    def test_placed_enqueues_once(self):
        notifier, store = _FakeNotifier(), _FakeStore(enabled=True)
        emit = make_market_exit_notifier(notifier=notifier, store=store)
        emit(self._result())
        self.assertEqual(len(notifier.texts), 1)
        self.assertIn("🧷", notifier.texts[0])
        self.assertIn("LSKUSDT", notifier.texts[0])
        self.assertIn("7777", notifier.texts[0])

    def test_disabled_store_does_not_enqueue(self):
        notifier, store = _FakeNotifier(), _FakeStore(enabled=False)
        emit = make_market_exit_notifier(notifier=notifier, store=store)
        emit(self._result())
        self.assertEqual(len(notifier.texts), 0)

    def test_raising_enqueue_is_swallowed(self):
        emit = make_market_exit_notifier(notifier=_RaisingNotifier(),
                                         store=_FakeStore(enabled=True))
        emit(self._result())


# ---------------------------------------------------------------------------
# (5) place_protective_stop emit-only kwarg
# ---------------------------------------------------------------------------
class TestPlaceProtectiveStopNotifier(unittest.TestCase):
    def _call(self, *, dry_run, notifier, open_orders=None, free="5"):
        client = _FakeGuardianClient(open_orders=open_orders or [], free=free)
        return place_protective_stop(
            client, "ETHUSDT", "ETH",
            reference_price=Decimal("100"), qty=Decimal("5"),
            emergency_sl_pct=Decimal("1"), filters=_gfilters(),
            client_order_id="grd-1", dry_run=dry_run, notifier=notifier,
        )

    def test_notifier_invoked_once_on_placed(self):
        calls = []
        r = self._call(dry_run=False, notifier=lambda res: calls.append(res))
        self.assertEqual(r["action"], "PLACED")
        self.assertEqual(len(calls), 1)
        self.assertIs(calls[0], r)

    def test_notifier_not_invoked_on_dry_run(self):
        calls = []
        r = self._call(dry_run=True, notifier=lambda res: calls.append(res))
        self.assertEqual(r["action"], "DRY_RUN")
        self.assertEqual(len(calls), 0)

    def test_notifier_not_invoked_on_abort(self):
        calls = []
        # resting protective sell present ⇒ ABORT_PROTECTED (no emit)
        r = self._call(dry_run=False, notifier=lambda res: calls.append(res),
                       open_orders=[{"orderId": 1}])
        self.assertEqual(r["action"], "ABORT_PROTECTED")
        self.assertEqual(len(calls), 0)

    def test_raising_notifier_only_sets_notify_error(self):
        def boom(_res):
            raise RuntimeError("notify boom")
        r = self._call(dry_run=False, notifier=boom)
        self.assertEqual(r["action"], "PLACED")
        self.assertTrue(r["placed"])
        self.assertIn("notify_error", r)
        self.assertIn("notify boom", r["notify_error"])


# ---------------------------------------------------------------------------
# (6) BracketExitWiring passes notifier through
# ---------------------------------------------------------------------------
class TestBracketWiringNotifier(unittest.TestCase):
    def test_placed_exit_enqueues_message(self):
        notifier, store = _FakeNotifier(), _FakeStore(enabled=True)
        emit = make_market_exit_notifier(notifier=notifier, store=store)
        rest = _FakeRest()
        w = _wiring(rest, notifier=emit, price="2.0", dry_run=False)
        self.assertEqual(w.tick()["action"], "ARMED")   # G1.49: أول اختراق مُسلَّح
        r = w.tick()
        self.assertEqual(r["action"], "EXIT_TRIGGERED")
        self.assertEqual(r["result"]["action"], "PLACED")
        self.assertEqual(len(notifier.texts), 1)
        self.assertIn("🧷", notifier.texts[0])
        self.assertIn("LSKUSDT", notifier.texts[0])

    def test_no_emit_on_non_placed_outcome(self):
        notifier, store = _FakeNotifier(), _FakeStore(enabled=True)
        emit = make_market_exit_notifier(notifier=notifier, store=store)
        rest = _FakeRest()
        # dry_run ⇒ DRY_RUN (not PLACED) ⇒ execute_market_exit does not call notifier
        w = _wiring(rest, notifier=emit, price="2.0", dry_run=True)
        self.assertEqual(w.tick()["action"], "ARMED")   # G1.49: أول اختراق مُسلَّح
        r = w.tick()
        self.assertEqual(r["result"]["action"], "DRY_RUN")
        self.assertEqual(len(notifier.texts), 0)

    def test_within_bracket_no_emit(self):
        notifier, store = _FakeNotifier(), _FakeStore(enabled=True)
        emit = make_market_exit_notifier(notifier=notifier, store=store)
        rest = _FakeRest()
        w = _wiring(rest, notifier=emit, price="1.5", dry_run=False)
        r = w.tick()
        self.assertEqual(r["action"], "WITHIN_BRACKET")
        self.assertEqual(len(notifier.texts), 0)


if __name__ == "__main__":
    unittest.main()
