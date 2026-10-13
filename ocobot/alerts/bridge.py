"""ocobot.alerts.bridge — read-only audit→alerts bridge (G1.25 / step_6).

Connect the already-built alert pieces (``Notifier`` + ``format_event``) to the
EXISTING append-only audit log, strictly READ-ONLY and with ZERO synchronous
network on the hot path.

Design invariants
-----------------
* This module NEVER touches ``MonitoringEngine``, ``SafeExecutor``, pricing or
  the audit writer. It only *reads* the audit JSONL file via the pure
  read-model parser (``ocobot.domain.completed_trades.parse_audit_jsonl``).
* ``poll_once()`` is fully synchronous and cheap (one disk read + non-blocking
  ``Notifier.enqueue``). The actual HTTP happens inside the Notifier worker
  thread, never here.
* It swallows ALL exceptions: a missing/corrupt file or a single bad record can
  never raise or stop processing of the remaining records. Worst case for
  alerts is a delayed/dropped message — the hot path is unaffected.

Pure stdlib + imports from ``ocobot.alerts.formatting`` and
``ocobot.domain.completed_trades``. NO Qt, NO network.
"""
from __future__ import annotations

import logging
import os

from ocobot.alerts.formatting import format_event
from ocobot.domain.completed_trades import parse_audit_jsonl

logger = logging.getLogger("ocobot.alerts.bridge")

# Events that produce an alert message. Mirrors ``format_event`` routing.
_ALERT_EVENTS = frozenset({"monitor_start", "repositioned"})


def default_audit_path() -> str:
    """Resolve the audit log path with the SAME rule as the writer/CLI.

    ``env OCOBOT_AUDIT_LOG`` else ``cwd/ocobot_audit.jsonl``.
    """
    env = os.environ.get("OCOBOT_AUDIT_LOG")
    if env:
        return env
    return os.path.join(os.getcwd(), "ocobot_audit.jsonl")


class AlertsAuditBridge:
    """Tails the audit JSONL and enqueues alerts for NEW monitor events.

    Parameters (keyword-only)
    -------------------------
    notifier:
        A ``Notifier``-like object exposing ``enqueue(text)`` (non-blocking,
        never raises).
    store:
        An ``AlertsStore``-like object exposing ``enabled_provider() -> bool``.
    audit_path:
        Explicit audit file path. When ``None`` it is resolved via
        :func:`default_audit_path` (the writer's rule).
    parse_fn:
        Parser ``(path) -> list[dict]`` for the JSONL file. Defaults to the
        domain read-model parser.
    start_at_end:
        When ``True`` (default) the processed-cursor is initialized to the
        CURRENT number of records so pre-existing/historical events are NOT
        re-sent on startup — alerts fire only for NEW events going forward.
    """

    def __init__(self, *, notifier, store, audit_path=None,
                 parse_fn=parse_audit_jsonl, start_at_end=True):
        self._notifier = notifier
        self._store = store
        self._audit_path = audit_path if audit_path else default_audit_path()
        self._parse_fn = parse_fn
        # G1.36: سياق آخر monitor_start (symbol/reference_price/tp_pct/sl_pct/trigger_pct/
        #        trade_uid/session_no) يُدمَج في سجلّات repositioned التالية لتعبئة خاناتها
        #        (محتوى الرسالة فقط — لا مساس بالتدقيق ولا hot_path المختوم).
        self._session_ctx = {}

        # Cursor = number of records already processed. Advancing it past the
        # historical tail (start_at_end) means only subsequently-appended
        # records are ever formatted + enqueued.
        self._cursor = 0
        if start_at_end:
            self._cursor = self._safe_count()

    # -- introspection ----------------------------------------------------
    @property
    def audit_path(self) -> str:
        return self._audit_path

    @property
    def cursor(self) -> int:
        return self._cursor

    # -- internal helpers -------------------------------------------------
    def _safe_read(self):
        """Read records defensively. Missing/corrupt file => empty list."""
        try:
            records = self._parse_fn(self._audit_path)
        except Exception:
            # parse_fn is itself tolerant, but we double-guard so a bad path or
            # unexpected failure can never raise into the UI timer.
            return []
        if not isinstance(records, list):
            return []
        return records

    def _safe_count(self) -> int:
        return len(self._safe_read())

    def _enrich(self, record):
        """G1.36: يدمج سياق آخر monitor_start في details سجلّ repositioned (own-wins).

        لا يعدّل السجلّ الأصلي؛ يُرجع نسخة مُثراة لرسائل repositioned فقط. أي حدث آخر
        يُعاد كما هو. محتوى الرسالة فقط — لا مساس بالتدقيق ولا hot_path المختوم.
        """
        try:
            if not isinstance(record, dict):
                return record
            if record.get("event") != "repositioned" or not self._session_ctx:
                return record
            own = record.get("details")
            own = own if isinstance(own, dict) else {}
            merged = dict(self._session_ctx)
            merged.update(own)  # قيم repositioned تفوز عند التعارض
            enriched = dict(record)
            enriched["details"] = merged
            return enriched
        except Exception:
            return record

    # -- the single poll entrypoint --------------------------------------
    def poll_once(self) -> int:
        """Process any NEW audit records; return the number of messages enqueued.

        Fully synchronous and cheap (disk read + non-blocking enqueue). Never
        raises. Handles truncation/rotation (count < cursor => reset cursor to
        current count). Each record is processed in its own try/except so one
        bad record cannot stop the rest.
        """
        try:
            records = self._safe_read()
            total = len(records)

            # Truncation / rotation: the file shrank — restart from its new end.
            if total < self._cursor:
                self._cursor = total

            if total <= self._cursor:
                # Nothing new. Keep the cursor at the current total.
                self._cursor = total
                return 0

            enqueued = 0
            for record in records[self._cursor:total]:
                try:
                    event = record.get("event") if isinstance(record, dict) else None
                    if event not in _ALERT_EVENTS:
                        continue
                    # G1.36: احفظ سياق آخر monitor_start لإثراء رسائل repositioned التالية.
                    if event == "monitor_start":
                        det = record.get("details")
                        self._session_ctx = dict(det) if isinstance(det, dict) else {}
                    # Short-circuit when alerts are disabled on disk right now.
                    try:
                        if self._store.enabled_provider() is False:
                            continue
                    except Exception:
                        # A failing provider must not stop processing; treat as
                        # "cannot confirm enabled" => skip this record safely.
                        continue
                    text = format_event(self._enrich(record))
                    if not text:
                        continue
                    ok = self._notifier.enqueue(text)
                    if ok is not False:
                        enqueued += 1
                except Exception:
                    # Swallow per-record: a single bad record can't affect
                    # anything else or the hot path.
                    try:
                        logger.warning("alerts bridge swallowed a bad record")
                    except Exception:
                        pass
                    continue

            # Advance the cursor to the new total regardless of per-record
            # outcomes so each record is considered exactly once.
            self._cursor = total
            return enqueued
        except Exception:
            # Absolute last-resort: poll_once must NEVER raise.
            try:
                logger.warning("alerts bridge poll_once swallowed an exception")
            except Exception:
                pass
            return 0


# ---------------------------------------------------------------------------
# G1.37 — emit-only intervention alert adapters (NOT audit-driven)
# ---------------------------------------------------------------------------
# The Position Guardian and the Price Exit Bracket emit a rich Telegram alert
# ONLY when they actually intervene (result["action"] == "PLACED"). These are
# NOT written to the audit log, so they are intentionally NOT part of
# ``_ALERT_EVENTS`` and never go through ``AlertsAuditBridge``. Instead the
# intervention points call the notifier callables produced below.
#
# Every function here is defensive (``.get`` everywhere) and NEVER raises — a
# failed/disabled alert must never affect trade execution.


def _dget(mapping, key, default=None):
    """Safe ``.get`` tolerating a non-dict input."""
    if isinstance(mapping, dict):
        return mapping.get(key, default)
    return default


def _response_order_id(response):
    """Pull an order id from a brokerage response dict (id/orderId/clientOrderId)."""
    if not isinstance(response, dict):
        return None
    for key in ("id", "orderId", "clientOrderId"):
        val = response.get(key)
        if val is not None:
            return val
    return None


def guardian_record(*, symbol, reason, result, reference_price=None,
                    emergency_sl_pct=None, naked_seconds=None, ts=None):
    """Build a ``guardian_intervention`` record from a PLACED guardian result.

    Defensive (``.get`` everywhere). Never raises.
    """
    try:
        plan = _dget(result, "plan", {}) or {}
        quantity = _dget(result, "eff_qty")
        if quantity is None:
            quantity = _dget(plan, "quantity")
        details = {
            "symbol": symbol,
            "reason": reason,
            "action": _dget(result, "action"),
            "eff_qty": _dget(result, "eff_qty"),
            "plan": plan,
            "quantity": quantity,
            "stop_trigger": _dget(plan, "stop_trigger"),
            "stop_price": _dget(plan, "stop_price"),
            "limit_price": _dget(plan, "limit_price"),
            "reference_price": reference_price,
            "emergency_sl_pct": emergency_sl_pct,
            "naked_seconds": naked_seconds,
            "client_order_id": _dget(result, "client_order_id"),
            "response": _dget(result, "response"),
        }
        record = {"event": "guardian_intervention", "details": details}
        if ts is not None:
            record["ts"] = ts
        return record
    except Exception:
        return {"event": "guardian_intervention", "details": {"symbol": symbol}}


def market_exit_record(result, *, reference_price=None, ts=None):
    """Build a ``market_exit`` record from a PLACED exit-bracket result.

    Defensive (``.get`` everywhere). Never raises.
    """
    try:
        plan = _dget(result, "plan", {}) or {}
        quantity = _dget(result, "eff_qty")
        if quantity is None:
            quantity = _dget(plan, "quantity")
        details = {
            "symbol": _dget(result, "symbol"),
            "exit_side": _dget(result, "exit_side"),
            "action": _dget(result, "action"),
            "eff_qty": _dget(result, "eff_qty"),
            "plan": plan,
            "quantity": quantity,
            "type": _dget(plan, "type"),
            "stop_price": _dget(plan, "stop_price"),
            "limit_price": _dget(plan, "limit_price"),
            "price": _dget(plan, "price"),
            "price_floor": _dget(plan, "price_floor"),
            "reference_price": reference_price
            if reference_price is not None
            else (_dget(result, "reference_price")
                  if _dget(result, "reference_price") is not None
                  else _dget(plan, "reference_price")),
            "client_order_id": _dget(result, "client_order_id"),
            "response": _dget(result, "response"),
        }
        record = {"event": "market_exit", "details": details}
        if ts is not None:
            record["ts"] = ts
        return record
    except Exception:
        return {"event": "market_exit", "details": {}}


def _store_enabled(store) -> bool:
    """Return True unless the store explicitly reports disabled. Never raises."""
    if store is None:
        return True
    try:
        return store.enabled_provider() is not False
    except Exception:
        # Cannot confirm enabled — be conservative and do not enqueue.
        return False


def make_guardian_notifier(*, notifier, store=None):
    """Return an ``emit(payload_dict)`` callable for guardian interventions.

    ``payload_dict`` carries symbol/reason/result/reference_price/
    emergency_sl_pct/naked_seconds/ts. Respects ``store.enabled_provider()``,
    builds the message via ``format_event(guardian_record(**payload))`` and
    enqueues it on the notifier. Swallows ALL exceptions.
    """

    def emit(payload):
        try:
            if not _store_enabled(store):
                return
            payload = payload if isinstance(payload, dict) else {}
            text = format_event(guardian_record(**payload))
            if text:
                notifier.enqueue(text)
        except Exception:
            try:
                logger.warning("guardian notifier swallowed an exception")
            except Exception:
                pass

    return emit


def make_market_exit_notifier(*, notifier, store=None):
    """Return an ``emit(result)`` callable for exit-bracket interventions.

    Matches the ``notifier(result)`` signature ``execute_market_exit`` expects.
    Respects ``store.enabled_provider()``, builds the message via
    ``format_event(market_exit_record(result))`` and enqueues it. Swallows ALL
    exceptions.
    """

    def emit(result):
        try:
            if not _store_enabled(store):
                return
            text = format_event(market_exit_record(result))
            if text:
                notifier.enqueue(text)
        except Exception:
            try:
                logger.warning("market exit notifier swallowed an exception")
            except Exception:
                pass

    return emit


__all__ = [
    "AlertsAuditBridge",
    "default_audit_path",
    "guardian_record",
    "market_exit_record",
    "make_guardian_notifier",
    "make_market_exit_notifier",
]
