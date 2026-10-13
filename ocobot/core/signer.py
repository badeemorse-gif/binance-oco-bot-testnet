"""HMAC SHA256 signing (D13 / Deliverable 4.6).

- نوقّع بايتات query string نفسها المُرسَلة (يمنع -1022).
- الترتيب ثابت: نستقبل قائمة أزواج مرتبة، و timestamp/recvWindow تُضمَّن قبل التوقيع.
"""
from __future__ import annotations

import hashlib
import hmac
from typing import Iterable, Tuple, Union
from urllib.parse import urlencode

Params = Union[Iterable[Tuple[str, object]], dict]


def build_query(params: Params) -> str:
    """Deterministic query string (insertion order preserved for list input)."""
    items = list(params.items()) if isinstance(params, dict) else list(params)
    # str() على القيم لضمان تطابق البايتات الموقّعة مع المُرسَلة
    normalised = [(str(k), str(v)) for k, v in items]
    return urlencode(normalised, doseq=False)


def sign(query_string: str, secret: str) -> str:
    return hmac.new(
        secret.encode("utf-8"), query_string.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def signed_query(params: Params, secret: str) -> str:
    qs = build_query(params)
    signature = sign(qs, secret)
    return f"{qs}&signature={signature}"
