"""ExchangeInfo service — قراءة الفلاتر ديناميكيًا + cache (D8، Deliverable 9).

symbol-agnostic: tickSize/stepSize/minQty/minNotional تُقرأ من
GET /api/v3/exchangeInfo?symbol= (غير موقّع) ولا تُكتب يدويًا (لا hardcode).
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Callable, Dict, Optional

from ocobot.core.errors import OcoBotError
from ocobot.domain.models import SymbolFilters, _dec

PATH_EXCHANGE_INFO = "/api/v3/exchangeInfo"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_symbol_filters(symbol_obj: dict) -> SymbolFilters:
    """يستخرج الفلاتر من كائن symbol في exchangeInfo."""
    filters = {f.get("filterType"): f for f in symbol_obj.get("filters", [])}

    price = filters.get("PRICE_FILTER", {})
    lot = filters.get("LOT_SIZE", {})
    # الاسم الحديث NOTIONAL؛ القديم MIN_NOTIONAL — ندعم كليهما
    notional = filters.get("NOTIONAL") or filters.get("MIN_NOTIONAL") or {}

    return SymbolFilters(
        symbol=str(symbol_obj.get("symbol", "")),
        tick_size=_dec(price.get("tickSize")),
        step_size=_dec(lot.get("stepSize")),
        min_qty=_dec(lot.get("minQty")),
        min_notional=_dec(notional.get("minNotional")),
        updated_at=_now_iso(),
    )


class ExchangeInfoService:
    def __init__(self, client, ttl_seconds: int = 3600, monotonic: Optional[Callable[[], float]] = None):
        self._client = client
        self._ttl = ttl_seconds
        self._monotonic = monotonic or time.monotonic
        self._cache: Dict[str, SymbolFilters] = {}
        self._fetched_at: Dict[str, float] = {}

    def _is_fresh(self, symbol: str) -> bool:
        ts = self._fetched_at.get(symbol)
        return ts is not None and (self._monotonic() - ts) < self._ttl

    def get_filters(self, symbol: str, force_refresh: bool = False) -> SymbolFilters:
        symbol = symbol.upper()
        if not force_refresh and symbol in self._cache and self._is_fresh(symbol):
            return self._cache[symbol]

        data = self._client.public_request(
            "GET", PATH_EXCHANGE_INFO, [("symbol", symbol)]
        )
        symbols = data.get("symbols") or []
        if not symbols:
            raise OcoBotError(f"exchangeInfo لم يُرجع رمزًا للعملة: {symbol}")
        filters = parse_symbol_filters(symbols[0])
        self._cache[symbol] = filters
        self._fetched_at[symbol] = self._monotonic()
        return filters

    def cached_symbols(self) -> list:
        return list(self._cache.keys())
