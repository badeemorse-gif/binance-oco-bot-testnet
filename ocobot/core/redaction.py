"""Redaction helpers — enforce D8: keys/secrets/signatures are NEVER logged.

قاعدة أمان: "لا تُسجَّل المفاتيح في أي log إطلاقًا (redaction إلزامي)".
"""
from __future__ import annotations

import logging
import re

_SIGNATURE_RE = re.compile(r"(signature=)[0-9A-Fa-f]+")
_APIKEY_HEADER_RE = re.compile(r"(X-MBX-APIKEY['\"]?\s*[:=]\s*['\"]?)[A-Za-z0-9]+")


def redact_signature(text: str) -> str:
    """Replace any HMAC signature / API-key header value in a string with '***'."""
    if not text:
        return text
    text = _SIGNATURE_RE.sub(r"\1***", text)
    text = _APIKEY_HEADER_RE.sub(r"\1***", text)
    return text


def mask_secret(_secret: str) -> str:
    """A secret is NEVER shown — always fully masked."""
    return "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022"


def mask_key(api_key: str) -> str:
    """Human-friendly, low-risk hint for an API key (not the full value)."""
    if not api_key:
        return "(none)"
    if len(api_key) <= 8:
        return "\u2022\u2022\u2022\u2022"
    return f"{api_key[:3]}\u2026{api_key[-3:]}"


class RedactingFilter(logging.Filter):
    """A logging filter that scrubs signatures/api-keys from every record."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003 (logging API)
        try:
            record.msg = redact_signature(record.getMessage())
            record.args = ()
        except Exception:
            pass
        return True
