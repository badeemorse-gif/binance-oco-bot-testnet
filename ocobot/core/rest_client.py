"""Signed REST client (Connectivity Layer — REST only, M0 scope).

النطاق: GET /api/v3/time (غير موقّع) + طلبات موقّعة (HMAC) مع
timestamp/recvWindow/clock-offset، ومعالجة:
  - -1021: إعادة مزامنة serverTime + إعادة توقيع/محاولة واحدة فقط (D18).
  - -1022: رفع خطأ توقيع بلا إعادة (يعالجه preflight / حالة الاتصال).
لا WS ولا endpoints أوامر هنا (خارج نطاق T1). لا إعادة محاولة عمياء للكتابة (D9).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Optional
from urllib import request as _urlrequest
from urllib.error import HTTPError, URLError

from ocobot.core.clock import ServerClock
from ocobot.core.environment import join_url
from ocobot.core.errors import BinanceApiError, TransportError
from ocobot.core.redaction import redact_signature
from ocobot.core.signer import build_query, signed_query

log = logging.getLogger("ocobot.rest")

PATH_TIME = "/api/v3/time"
PATH_ACCOUNT = "/api/v3/account"


@dataclass
class Response:
    status: int
    headers: dict
    body: str


class UrllibTransport:
    """stdlib transport (لا اعتمادات خارجية)."""

    def __init__(self, timeout: float = 10.0):
        self.timeout = timeout

    def send(self, method: str, url: str, headers: dict, body: Optional[bytes]) -> Response:
        req = _urlrequest.Request(url=url, data=body, method=method)
        for key, value in (headers or {}).items():
            req.add_header(key, value)
        try:
            with _urlrequest.urlopen(req, timeout=self.timeout) as resp:
                text = resp.read().decode("utf-8", errors="replace")
                return Response(resp.status, dict(resp.headers.items()), text)
        except HTTPError as exc:  # 4xx/5xx: نقرأ الجسم لاستخراج code/msg
            text = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            headers_out = dict(exc.headers.items()) if exc.headers else {}
            return Response(exc.code, headers_out, text)
        except (URLError, TimeoutError) as exc:
            raise TransportError(f"تعذّر الوصول إلى Binance: {exc}") from exc


class SignedRestClient:
    def __init__(self, config, credentials, transport=None, clock=None, now_ms=None):
        self.config = config
        self.credentials = credentials
        self._transport = transport or UrllibTransport(timeout=config.request_timeout)
        self._clock = clock or ServerClock(time_fetcher=self.fetch_server_time, now_ms=now_ms)
        self.last_used_weight: Optional[str] = None

    @property
    def clock(self) -> ServerClock:
        return self._clock

    # ---- unsigned ----
    def fetch_server_time(self) -> int:
        resp = self._transport.send(
            "GET", join_url(self.config.rest_base(), PATH_TIME), {}, None
        )
        data = self._parse_body(resp)
        self._raise_for_binance_error(resp, data)
        return int(data["serverTime"])

    def sync_time(self) -> int:
        return self._clock.sync()

    def public_request(self, method: str, path: str, params=None) -> dict:
        """طلب عام غير موقّع (مثل exchangeInfo). لا مفتاح ولا توقيع."""
        qs = build_query(list(params)) if params else ""
        url = join_url(self.config.rest_base(), path) + (f"?{qs}" if qs else "")
        resp = self._transport.send(method, url, {}, None)
        self._capture_weight(resp.headers)
        data = self._parse_body(resp)
        self._raise_for_binance_error(resp, data)
        return data

    # ---- signed ----
    def signed_request(self, method: str, path: str, params=None) -> dict:
        if not self._clock.synced:
            self._clock.sync()
        return self._do_signed(method, path, list(params or []), allow_resync=True)

    def get_account(self) -> dict:
        """نداء موقّع خفيف للتحقق من المفتاح/التوقيع (preflight)."""
        return self.signed_request("GET", PATH_ACCOUNT)

    def get_open_orders(self, symbol: Optional[str] = None):
        """GET /api/v3/openOrders (SIGNED). يعيد كل الأوامر المفتوحة.
        orderListId == -1 ⇒ أمر مستقل ؛ > 0 ⇒ ساق OCO."""
        params = []
        if symbol is not None:
            params.append(("symbol", symbol))
        return self.signed_request("GET", "/api/v3/openOrders", params)

    def cancel_order(self, symbol: str, orderId: Optional[int] = None, origClientOrderId: Optional[str] = None):
        """DELETE /api/v3/order (SIGNED). لإلغاء أمر مستقل (غير-OCO).
        يتطلّب symbol وواحدًا فقط من orderId | origClientOrderId."""
        if (orderId is None) == (origClientOrderId is None):
            raise ValueError("cancel_order requires exactly one of orderId or origClientOrderId")
        params = [("symbol", symbol)]
        if orderId is not None:
            params.append(("orderId", orderId))
        else:
            params.append(("origClientOrderId", origClientOrderId))
        return self.signed_request("DELETE", "/api/v3/order", params)

    # ---- key-only (unsigned) ----
    def keyed_request(self, method: str, path: str, params=None) -> dict:
        """طلب بمصادقة مفتاح فقط (X-MBX-APIKEY) بلا توقيع HMAC (D20).

        listenKey (/api/v3/userDataStream) يستخدم مصادقة مفتاح فقط: يُرسَل
        رأس X-MBX-APIKEY وحده، دون توقيع signature ودون timestamp. يعيد استخدام
        نفس سباكة النقل ومعالجة الأخطاء المستعملة في public_request/signed_request.
        """
        qs = build_query(list(params)) if params else ""
        url = join_url(self.config.rest_base(), path) + (f"?{qs}" if qs else "")
        headers = {"X-MBX-APIKEY": self.credentials.api_key}
        log.debug("keyed %s %s", method, redact_signature(url))

        resp = self._transport.send(method, url, headers, None)
        self._capture_weight(resp.headers)
        data = self._parse_body(resp)
        self._raise_for_binance_error(resp, data)
        return data

    # ---- internals ----
    def _do_signed(self, method, path, base_params, allow_resync):
        params = list(base_params)
        params.append(("recvWindow", self.config.recv_window))
        params.append(("timestamp", self._clock.timestamp()))  # local + offset (D18)
        qs = signed_query(params, self.credentials.api_secret)
        url = join_url(self.config.rest_base(), path) + "?" + qs
        headers = {"X-MBX-APIKEY": self.credentials.api_key}
        log.debug("signed %s %s", method, redact_signature(url))

        resp = self._transport.send(method, url, headers, None)
        self._capture_weight(resp.headers)
        data = self._parse_body(resp)

        # -1021: مزامنة + محاولة واحدة فقط (لا تكرار كتابة أعمى — D18/D9)
        if isinstance(data, dict) and data.get("code") == -1021 and allow_resync:
            log.warning("received -1021 (timestamp); resyncing clock and retrying once")
            self._clock.sync()
            return self._do_signed(method, path, base_params, allow_resync=False)

        self._raise_for_binance_error(resp, data)
        return data

    def _capture_weight(self, headers: dict):
        if not headers:
            return
        for key, value in headers.items():
            if key.lower().startswith("x-mbx-used-weight"):
                self.last_used_weight = value

    @staticmethod
    def _parse_body(resp: "Response"):
        if not resp.body:
            return {}
        try:
            return json.loads(resp.body)
        except ValueError:
            return {"_raw": resp.body}

    @staticmethod
    def _raise_for_binance_error(resp: "Response", data):
        if isinstance(data, dict) and isinstance(data.get("code"), int) and data["code"] < 0:
            raise BinanceApiError(data.get("code"), str(data.get("msg", "")), resp.status)
        if resp.status >= 400:
            msg = data.get("msg") if isinstance(data, dict) else resp.body
            code = data.get("code") if isinstance(data, dict) else None
            raise BinanceApiError(code, str(msg or f"HTTP {resp.status}"), resp.status)


def build_signed_client(config, credentials) -> "SignedRestClient":
    """مصنع بسيط لبناء SignedRestClient من إعدادات + بيانات اعتماد صريحة.

    يوحّد نقطة إنشاء العميل دون تكرار منطق البناء، ودون أي تغيير في السلوك:
    مطابق لـ ``SignedRestClient(config, credentials)``. لا لمس لمنطق التوقيع.
    """
    return SignedRestClient(config, credentials)
