"""Typed errors for the OCOBot connectivity layer (M0)."""
from __future__ import annotations

from typing import Optional


class OcoBotError(Exception):
    """Base error for all OCOBot failures."""


class ConfigError(OcoBotError):
    """Invalid or inconsistent application configuration."""


class KeysError(OcoBotError):
    """Missing key file / missing or empty keys for the selected environment."""


class TransportError(OcoBotError):
    """Network/transport level failure (timeout, DNS, connection reset)."""


class BinanceApiError(OcoBotError):
    """A Binance REST error response (negative ``code`` + ``msg``).

    يحمل ``code`` كي تُعالَج الأخطاء الحرجة (مثل -1021/-1022) بدقّة.
    """

    def __init__(self, code: Optional[int], msg: str, http_status: Optional[int] = None):
        self.code = code
        self.msg = msg
        self.http_status = http_status
        super().__init__(f"Binance API error {code}: {msg} (HTTP {http_status})")
