"""Environment selection + base URLs.

قرار D12: التحويل بين Testnet وLive = تبديل base URL + المفتاح فقط، لا فرع منطق.
القيم مأخوذة من PROJECT_STATE.binance_reference.base_urls (المصدر التصميمي).
"""
from __future__ import annotations

from enum import Enum


class Environment(str, Enum):
    TESTNET = "testnet"
    LIVE = "live"

    @classmethod
    def parse(cls, value) -> "Environment":
        if isinstance(value, Environment):
            return value
        v = str(value).strip().lower()
        for member in cls:
            if member.value == v:
                return member
        raise ValueError(f"Unknown environment: {value!r} (use 'testnet' or 'live')")


# Documented in PROJECT_STATE.binance_reference.base_urls
_REST_BASE = {
    Environment.TESTNET: "https://testnet.binance.vision/api",
    Environment.LIVE: "https://api.binance.com",
}
_WS_BASE = {
    Environment.TESTNET: "wss://stream.testnet.binance.vision/ws",
    Environment.LIVE: "wss://stream.binance.com:9443/ws",
}


def rest_base_url(env) -> str:
    return _REST_BASE[Environment.parse(env)]


def ws_base_url(env) -> str:
    return _WS_BASE[Environment.parse(env)]


def join_url(base: str, path: str) -> str:
    """Join base + path defensively.

    Binance endpoint paths are documented as ``/api/v3/...``. The testnet base
    already ends with ``/api``; we drop the duplicate to avoid ``/api/api/...``.
    يجعل الدمج صحيحًا سواء انتهى الأساس بـ ``/api`` أم لا.
    """
    base = (base or "").rstrip("/")
    if not path.startswith("/"):
        path = "/" + path
    if base.endswith("/api") and path.startswith("/api/"):
        base = base[: -len("/api")]
    return base + path
