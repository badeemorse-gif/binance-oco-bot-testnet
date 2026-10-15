"""خدمة جلب الشموع (klines) + cache (G1.56 · c5).

على نمط ExchangeInfoService: الشبكة تمرّ عبر عميل مُحقَّن (``public_request``
غير موقّع، GET /api/v3/klines) — لا شبكة في طبقة الواجهة. الواجهة تستدعي هذه
الخدمة عبر الـرَنَر (AsyncRunner.submit) فيبقى الـIO خارج خيط Qt.

النتائج تُحوَّل إلى ``volatility.Candle`` (as_candles يفهم صفوف klines مباشرةً)
وتُخزَّن في cache بمهلة TTL لتفادي الطلبات المتكرّرة.
"""
from __future__ import annotations

import time
from typing import Callable, Dict, List, Optional, Tuple

from ocobot.core.errors import OcoBotError
from ocobot.domain.volatility import Candle, as_candles

PATH_KLINES = "/api/v3/klines"

# فريمات هرمية مقترحة (HTF سياق / MTF حجم / LTF ضوضاء) — عرض/معايرة فقط.
HTF_INTERVALS = ("1d", "4h")
MTF_INTERVALS = ("1h", "15m")
LTF_INTERVALS = ("5m", "1m")

_VALID_INTERVALS = {
    "1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h",
    "1d", "3d", "1w", "1M",
}


class KlinesService:
    def __init__(self, client, ttl_seconds: int = 300,
                 monotonic: Optional[Callable[[], float]] = None):
        self._client = client
        self._ttl = ttl_seconds
        self._monotonic = monotonic or time.monotonic
        self._cache: Dict[Tuple[str, str, int], List[Candle]] = {}
        self._fetched_at: Dict[Tuple[str, str, int], float] = {}

    def _is_fresh(self, key) -> bool:
        ts = self._fetched_at.get(key)
        return ts is not None and (self._monotonic() - ts) < self._ttl

    def get_candles(self, symbol: str, interval: str = "1h", limit: int = 200,
                    force_refresh: bool = False) -> List[Candle]:
        """يجلب شموع العملة (مع cache). يرفع OcoBotError على مُدخل غير صالح."""
        if not symbol:
            raise OcoBotError("رمز العملة مطلوب لجلب الشموع")
        if interval not in _VALID_INTERVALS:
            raise OcoBotError(f"فاصل زمني غير مدعوم: {interval}")
        if limit <= 0 or limit > 1000:
            raise OcoBotError("limit يجب أن يكون في (0, 1000]")
        key = (symbol.upper(), interval, int(limit))
        if not force_refresh and key in self._cache and self._is_fresh(key):
            return self._cache[key]

        data = self._client.public_request("GET", PATH_KLINES, [
            ("symbol", key[0]), ("interval", interval), ("limit", str(limit)),
        ])
        if not isinstance(data, list):
            raise OcoBotError("ردّ klines غير متوقّع (ليس قائمة)")
        candles = as_candles(data)
        self._cache[key] = candles
        self._fetched_at[key] = self._monotonic()
        return candles

    def cached_keys(self) -> list:
        return list(self._cache.keys())

    def invalidate(self, symbol: Optional[str] = None) -> None:
        if symbol is None:
            self._cache.clear()
            self._fetched_at.clear()
            return
        sym = symbol.upper()
        for k in [k for k in self._cache if k[0] == sym]:
            self._cache.pop(k, None)
            self._fetched_at.pop(k, None)


def build_klines_fetcher(service: KlinesService, symbol: str,
                         interval: str = "1h", limit: int = 200) -> Callable[[], List[Candle]]:
    """يُعيد callable بلا وسائط (تُسلَّم إلى AsyncRunner.submit) تجلب الشموع.

    لا تلمس الواجهة الشبكة: اللوحة تستدعي runner.submit(fetcher, on_result=...).
    """
    def _fetch() -> List[Candle]:
        return service.get_candles(symbol, interval, limit)
    return _fetch
