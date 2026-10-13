"""Test doubles for M3 monitoring/market_feed tests (no network)."""
from __future__ import annotations

from decimal import Decimal

from ocobot.core.market_feed import MarketFeedError, PriceSource
from ocobot.domain.models import SymbolFilters
from ocobot.domain.reposition import (
    ExecutionResult,
    ExecutionState,
    ExecutionStep,
    RepositionDraft,
)


class FakeSelectedOCO:
    """Lightweight SelectedOCO stand-in for MonitoringEngine.start()."""

    def __init__(self, order_list_id=31, symbol="BTCUSDT"):
        self.order_list_id = order_list_id
        self.symbol = symbol


def _steps():
    return [ExecutionStep("confirm", "confirm", "done")]


def make_draft(reference_price, *, symbol="BTCUSDT"):
    """RepositionDraft خفيف يحمل reference_price (السعر الحيّ الذي استعمله التحويل).

    يُستعمل في اختبارات G1.13 لمحاكاة ما ترجعه convert.py على ExecutionResult.draft
    دون أي شبكة؛ يكفي أن يحمل reference_price لأن مسار البدء يقرأه فقط.
    """
    ref = Decimal(str(reference_price))
    return RepositionDraft(
        symbol=symbol,
        quantity=Decimal("1"),
        tp_price=ref,
        stop_trigger=ref,
        stop_limit=ref,
        reference_price=ref,
        tp_pct=Decimal("4"),
        sl_pct=Decimal("2"),
        filters=SymbolFilters(symbol=symbol, tick_size=Decimal("0.01")),
    )


def make_result(state, *, new_order_list_id=None, cancelled_order_list_id=None,
                reason="", messages=None, draft=None):
    return ExecutionResult(
        state=state,
        steps=_steps(),
        draft=draft,
        new_order_list_id=new_order_list_id,
        cancelled_order_list_id=cancelled_order_list_id,
        reason=reason,
        messages=messages or [],
    )


class FakeSafeExecutor:
    """Records execute() calls and returns scripted ExecutionResults.

    ``results`` is a list consumed in order; when exhausted the last one repeats.
    A single ``result`` may be given instead. ``new_ids`` (optional) supplies a
    per-call sequence of new_order_list_id values for SUCCESS results.
    """

    def __init__(self, result=None, results=None, new_ids=None):
        if results is None:
            results = [result] if result is not None else [
                make_result(ExecutionState.SUCCESS, new_order_list_id=99,
                            cancelled_order_list_id=31)
            ]
        self._results = list(results)
        self._new_ids = list(new_ids) if new_ids else None
        self.calls = []          # list of kwargs dicts passed to execute()
        self.cancel_calls = []   # never populated by engine (engine never cancels directly)
        self.create_calls = []

    def execute(self, *, order_list_id, tp_pct, sl_pct, reference_price, dry_run=False):
        idx = len(self.calls)
        self.calls.append({
            "order_list_id": order_list_id,
            "tp_pct": tp_pct,
            "sl_pct": sl_pct,
            "reference_price": reference_price,
            "dry_run": dry_run,
        })
        if idx < len(self._results):
            res = self._results[idx]
        else:
            res = self._results[-1]
        # لو طُلبت معرّفات جديدة متسلسلة، اطبعها على نتيجة النجاح
        if self._new_ids and res.state == ExecutionState.SUCCESS and idx < len(self._new_ids):
            res.new_order_list_id = self._new_ids[idx]
        return res


class FakePriceSource(PriceSource):
    """Yields scripted prices; can be set to raise MarketFeedError."""

    def __init__(self, prices=None, raise_error=False):
        self._prices = [Decimal(str(p)) for p in (prices or [])]
        self._idx = 0
        self.raise_error = raise_error

    def get_price(self, symbol=""):
        if self.raise_error:
            raise MarketFeedError("WS down")
        if not self._prices:
            raise MarketFeedError("no price")
        p = self._prices[min(self._idx, len(self._prices) - 1)]
        self._idx += 1
        return p


class FakeSocket:
    """Feeds canned server frames byte-batches; records what was sent."""

    def __init__(self, recv_chunks):
        self._chunks = list(recv_chunks)
        self.sent = []

    def sendall(self, data):
        self.sent.append(data)

    def recv(self, _n):
        if self._chunks:
            return self._chunks.pop(0)
        return b""

    def close(self):
        pass
