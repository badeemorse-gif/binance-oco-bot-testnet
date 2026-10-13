"""Telegram Bot API sending channel (official HTTP API only).

Standard-library only. No new third-party dependencies.

Design notes:
  * NO network call happens at import time or in ``__init__``.
  * The network layer is an *injectable transport* callable so offline tests
    can mock it without touching the real network.
  * The bot token is stored privately and is NEVER logged; ``__repr__`` /
    ``__str__`` show a masked placeholder only.
  * This module is Qt-free and synchronous; the ``Notifier`` worker drives it
    off any hot path.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request

API_BASE = "https://api.telegram.org"


class TelegramError(Exception):
    """Raised when the Telegram API returns an ``ok: false`` envelope.

    Carries the optional ``description`` and ``error_code`` returned by the
    Telegram API. Never carries the bot token.
    """

    def __init__(self, description=None, *, error_code=None):
        self.description = description
        self.error_code = error_code
        super().__init__(description if description is not None else "Telegram API error")


def _default_transport(method_url, params, timeout):
    """Default stdlib transport: HTTP POST form-urlencoded, parse JSON.

    callable(method_url: str, params: dict, timeout: float) -> dict
    Returns the parsed Telegram JSON envelope. Network / transport exceptions
    are allowed to propagate (the Notifier swallows them).
    """
    data = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(
        method_url,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    return json.loads(raw.decode("utf-8"))


class TelegramClient:
    """Thin synchronous wrapper over the Telegram Bot API.

    Parameters
    ----------
    token:
        The bot token from @BotFather. Stored privately and never logged.
    timeout:
        Per-request timeout in seconds (short, keyword-only).
    transport:
        Optional injectable callable
        ``(method_url: str, params: dict, timeout: float) -> dict`` returning
        the parsed Telegram JSON envelope. Defaults to a stdlib urllib POST.
    """

    def __init__(self, token, *, timeout=10.0, transport=None):
        self._token = token
        self._timeout = timeout
        self._transport = transport if transport is not None else _default_transport

    # -- safety: never reveal the token -----------------------------------
    def __repr__(self):
        return "TelegramClient(token=\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022)"

    __str__ = __repr__

    # -- internals --------------------------------------------------------
    def _url(self, method):
        """Build the method URL. Never logged."""
        return "%s/bot%s/%s" % (API_BASE, self._token, method)

    def _call(self, method, params):
        """Invoke the transport and unwrap the Telegram envelope.

        Returns ``resp['result']`` when ``ok`` is True; otherwise raises
        ``TelegramError`` built from the envelope. Transport/network
        exceptions are NOT caught here and propagate to the caller
        (the Notifier swallows them).
        """
        resp = self._transport(self._url(method), params, self._timeout)
        if isinstance(resp, dict) and resp.get("ok") is True:
            return resp.get("result")
        description = None
        error_code = None
        if isinstance(resp, dict):
            description = resp.get("description")
            error_code = resp.get("error_code")
        raise TelegramError(description, error_code=error_code)

    # -- public API -------------------------------------------------------
    def get_me(self):
        """Validate the token format + liveness. Returns the bot user dict."""
        return self._call("getMe", {})

    def send_message(self, chat_id, text, *, parse_mode=None,
                     disable_web_page_preview=True):
        """Send a text message to ``chat_id``.

        ``parse_mode`` is included only when truthy. Escaping of ``text`` for
        MarkdownV2 is NOT done here — the caller/formatter handles that in a
        later step. Returns the message result on success; raises
        ``TelegramError`` on an API failure.
        """
        params = {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": disable_web_page_preview,
        }
        if parse_mode:
            params["parse_mode"] = parse_mode
        return self._call("sendMessage", params)

    def get_updates(self, *, offset=None, timeout=0, limit=None):
        """Return a list of update dicts (used by the UI to capture a chat_id).

        Helper to capture a recipient chat_id after the user presses Start.
        """
        params = {"timeout": timeout}
        if offset is not None:
            params["offset"] = offset
        if limit is not None:
            params["limit"] = limit
        result = self._call("getUpdates", params)
        return result if result is not None else []
