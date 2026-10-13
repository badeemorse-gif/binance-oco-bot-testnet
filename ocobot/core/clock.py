"""Server-time synchronisation + clock offset (D18).

يعالج/يمنع -1021: offset = serverTime - localTime، ويُضاف لكل timestamp.
مصدر الوقت يُحقَن (time_fetcher) لتفادي الاعتماد الدائري مع REST client.
"""
from __future__ import annotations

import time
from typing import Callable, Optional


def _default_now_ms() -> int:
    return int(time.time() * 1000)


class ServerClock:
    def __init__(
        self,
        time_fetcher: Callable[[], int],
        now_ms: Optional[Callable[[], int]] = None,
    ):
        self._fetch = time_fetcher
        self._now_ms = now_ms or _default_now_ms
        self._offset_ms = 0
        self._synced = False
        self._last_sync_ms: Optional[int] = None

    @property
    def synced(self) -> bool:
        return self._synced

    @property
    def offset_ms(self) -> int:
        return self._offset_ms

    @property
    def last_sync_ms(self) -> Optional[int]:
        return self._last_sync_ms

    def sync(self) -> int:
        """Fetch serverTime and recompute the offset. Returns the new offset."""
        server_ms = int(self._fetch())
        local_ms = self._now_ms()
        self._offset_ms = server_ms - local_ms
        self._synced = True
        self._last_sync_ms = local_ms
        return self._offset_ms

    def timestamp(self) -> int:
        """Local now (ms) adjusted by the server offset."""
        return self._now_ms() + self._offset_ms
