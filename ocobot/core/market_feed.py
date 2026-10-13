"""Live price feed (M3 / T4) — REST + pure-stdlib WebSocket (RFC6455).

D14: السعر الحيّ حقيقي دائمًا — لا preview وهمي/ثابت.

مكوّنات:
  - PriceSource: بروتوكول get_price(symbol) -> Decimal.
  - RestPriceSource: GET /api/v3/ticker/price?symbol= (عام غير موقّع).
  - دوال RFC6455 خالصة (قابلة للاختبار بلا socket): بناء الـ handshake،
    ترميز إطار عميل مُقنّع (masked)، وفكّ إطارات الخادم (FIN/opcodes/lengths).
  - MarketWebSocketSource: عميل stdlib خفيف (socket+ssl) يشترك في
    "<symbol>@bookTicker" ويُخرج أفضل BID (سعر البيع/الخروج الصالح). الـ socket
    قابل للحقن لاختبار إطارات مُعلَّبة بلا شبكة.
  - PriceFeedController: يفضّل WS؛ عند فشله يسقط إلى REST مع تنبيه ثم يحاول
    إعادة الاتصال. منطق القرار خالص/قابل للحقن (يُختبر بمصادر وهمية بلا شبكة).
"""
from __future__ import annotations

import base64
import json
import os
import socket
import ssl
import struct
from decimal import Decimal
from typing import Callable, Iterator, List, Optional, Tuple
from urllib.parse import urlparse

from ocobot.core.errors import OcoBotError

PATH_TICKER_PRICE = "/api/v3/ticker/price"

# تنبيه سقوط REST (يجب أن يطابق نص التصميم)
ALERT_REST_FALLBACK = "سعر REST مؤقت"

# RFC6455 magic GUID (للتوثيق/التحقق فقط؛ العميل لا يتحقق من الـ accept هنا)
WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

OPCODE_TEXT = 0x1
OPCODE_BINARY = 0x2
OPCODE_CLOSE = 0x8
OPCODE_PING = 0x9
OPCODE_PONG = 0xA


class MarketFeedError(OcoBotError):
    """فشل مصدر السعر (WS/REST)."""


class PriceSource:
    """بروتوكول مصدر السعر (ABC خفيف)."""

    def get_price(self, symbol: str) -> Decimal:
        raise NotImplementedError


class RestPriceSource(PriceSource):
    """سعر لحظي عبر REST العام (غير موقّع)."""

    def __init__(self, client):
        self._client = client

    def get_price(self, symbol: str) -> Decimal:
        data = self._client.public_request(
            "GET", PATH_TICKER_PRICE, [("symbol", symbol)]
        )
        try:
            return Decimal(str(data["price"]))
        except (KeyError, TypeError) as exc:
            raise MarketFeedError(f"ردّ REST غير صالح للسعر: {data!r}") from exc


# ============================ RFC6455 pure helpers ============================

def build_ws_handshake_request(host: str, path: str, key: str) -> bytes:
    """يبني طلب handshake HTTP/1.1 لترقية الاتصال إلى WebSocket."""
    if not path:
        path = "/"
    lines = [
        f"GET {path} HTTP/1.1",
        f"Host: {host}",
        "Upgrade: websocket",
        "Connection: Upgrade",
        f"Sec-WebSocket-Key: {key}",
        "Sec-WebSocket-Version: 13",
        "",
        "",
    ]
    return "\r\n".join(lines).encode("ascii")


def make_ws_key() -> str:
    """مفتاح Sec-WebSocket-Key: 16 بايت عشوائية بترميز base64."""
    return base64.b64encode(os.urandom(16)).decode("ascii")


def encode_client_frame(payload_bytes: bytes, opcode: int = OPCODE_TEXT) -> bytes:
    """يرمّز إطار عميل واحد (FIN=1، MASK=1 إلزامي للعميل، مفتاح قناع 4 بايت)."""
    if isinstance(payload_bytes, str):
        payload_bytes = payload_bytes.encode("utf-8")
    length = len(payload_bytes)

    first = 0x80 | (opcode & 0x0F)  # FIN=1 + opcode
    frame = bytearray()
    frame.append(first)

    if length < 126:
        frame.append(0x80 | length)  # MASK=1 + len
    elif length < 65536:
        frame.append(0x80 | 126)
        frame.extend(struct.pack("!H", length))
    else:
        frame.append(0x80 | 127)
        frame.extend(struct.pack("!Q", length))

    mask_key = os.urandom(4)
    frame.extend(mask_key)
    masked = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload_bytes))
    frame.extend(masked)
    return bytes(frame)


def decode_frames(buffer: bytes) -> Tuple[List[Tuple[int, bytes]], bytes]:
    """يفكّ ما أمكن من إطارات كاملة من ``buffer``.

    يُرجع (list_of_(opcode, payload), remaining_buffer). يدعم:
      - FIN bit، opcodes 0x1/0x2/0x8/0x9/0xA
      - أطوال 7-bit / 16-bit / 64-bit
      - إطارات خادم غير مُقنّعة (وأيضًا المُقنّعة احتياطًا)
    الإطارات غير المكتملة تبقى في remaining_buffer.
    """
    frames: List[Tuple[int, bytes]] = []
    data = bytes(buffer)
    i = 0
    n = len(data)

    while True:
        if n - i < 2:
            break
        b0 = data[i]
        b1 = data[i + 1]
        opcode = b0 & 0x0F
        masked = (b1 & 0x80) != 0
        length = b1 & 0x7F
        header = i + 2

        if length == 126:
            if n - header < 2:
                break
            length = struct.unpack("!H", data[header:header + 2])[0]
            header += 2
        elif length == 127:
            if n - header < 8:
                break
            length = struct.unpack("!Q", data[header:header + 8])[0]
            header += 8

        mask_key = b""
        if masked:
            if n - header < 4:
                break
            mask_key = data[header:header + 4]
            header += 4

        if n - header < length:
            break  # الحمولة غير مكتملة بعد

        payload = data[header:header + length]
        if masked:
            payload = bytes(b ^ mask_key[j % 4] for j, b in enumerate(payload))

        frames.append((opcode, payload))
        i = header + length

    return frames, data[i:]


# ============================ WebSocket source ==============================

class MarketWebSocketSource(PriceSource):
    """عميل WS خفيف (stdlib) يشترك في bookTicker ويُخرج أفضل BID.

    ``connect_fn`` قابل للحقن (يُرجع socket-like) لاختبار إطارات مُعلَّبة بلا شبكة.
    """

    def __init__(self, ws_base: str, symbol: str, connect_fn: Optional[Callable] = None):
        self._ws_base = ws_base
        self.symbol = symbol
        self._connect_fn = connect_fn or self._default_connect
        self._sock = None
        self._buffer = b""
        self._last_bid: Optional[Decimal] = None

    # --- connection ---
    def _default_connect(self, host: str, port: int):
        raw = socket.create_connection((host, port), timeout=10.0)
        ctx = ssl.create_default_context()
        return ctx.wrap_socket(raw, server_hostname=host)

    def connect(self) -> None:
        parsed = urlparse(self._ws_base)
        host = parsed.hostname or ""
        port = parsed.port or (443 if parsed.scheme in ("wss", "https") else 80)
        base_path = parsed.path or "/ws"
        stream = f"{self.symbol.lower()}@bookTicker"
        path = base_path.rstrip("/") + "/" + stream
        try:
            self._sock = self._connect_fn(host, port)
            key = make_ws_key()
            self._sock.sendall(build_ws_handshake_request(host, path, key))
            # اقرأ ردّ الـ handshake حتى نهاية الترويسات
            self._read_handshake_response()
        except Exception as exc:  # noqa: BLE001 — نغلّفها بخطأ مُصنّف
            raise MarketFeedError(f"تعذّر فتح WebSocket: {exc}") from exc

    def _read_handshake_response(self) -> None:
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise MarketFeedError("انقطع الاتصال أثناء الـ handshake.")
            data += chunk
        head, _, rest = data.partition(b"\r\n\r\n")
        if b"101" not in head.split(b"\r\n", 1)[0]:
            raise MarketFeedError(f"handshake مرفوض: {head[:80]!r}")
        self._buffer += rest  # قد تصل إطارات مبكّرة ملحقة

    # --- reading ---
    def _extract_bid(self, payload: bytes) -> Optional[Decimal]:
        try:
            obj = json.loads(payload.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None
        # bookTicker: {"b": bidPrice, "a": askPrice, ...} (قد يكون داخل "data")
        data = obj.get("data", obj) if isinstance(obj, dict) else {}
        bid = data.get("b") if isinstance(data, dict) else None
        if bid is None:
            return None
        try:
            return Decimal(str(bid))
        except Exception:  # noqa: BLE001
            return None

    def _pump_once(self) -> Optional[Decimal]:
        """يقرأ دفعة ويفكّ إطاراتها؛ يُرجع أحدث bid أو None."""
        if self._sock is None:
            raise MarketFeedError("WebSocket غير متّصل.")
        chunk = self._sock.recv(4096)
        if not chunk:
            raise MarketFeedError("انقطع اتصال WebSocket.")
        self._buffer += chunk
        frames, self._buffer = decode_frames(self._buffer)
        latest: Optional[Decimal] = None
        for opcode, payload in frames:
            if opcode == OPCODE_CLOSE:
                raise MarketFeedError("استلمنا إطار إغلاق من الخادم.")
            if opcode == OPCODE_PING:
                # ردّ pong (مُقنّع كإطار عميل)
                try:
                    self._sock.sendall(encode_client_frame(payload, OPCODE_PONG))
                except Exception:  # noqa: BLE001
                    pass
                continue
            if opcode in (OPCODE_TEXT, OPCODE_BINARY):
                bid = self._extract_bid(payload)
                if bid is not None:
                    latest = bid
        if latest is not None:
            self._last_bid = latest
        return latest

    def prices(self) -> Iterator[Decimal]:
        """مولِّد يُخرج أفضل BID كلما وصل تحديث جديد."""
        while True:
            bid = self._pump_once()
            if bid is not None:
                yield bid

    def get_price(self, symbol: str = "") -> Decimal:
        """أحدث BID متاح (يضخّ دفعة إن لزم)."""
        bid = self._pump_once()
        if bid is not None:
            return bid
        if self._last_bid is not None:
            return self._last_bid
        raise MarketFeedError("لا يوجد سعر BID متاح بعد.")

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:  # noqa: BLE001
                pass
            self._sock = None


# ============================ Controller ====================================

class PriceFeedController:
    """يفضّل WS؛ عند فشله يسقط إلى REST (تنبيه) ثم يحاول إعادة اتصال WS.

    منطق القرار خالص/قابل للحقن: يُمرَّر ``ws_source`` و``rest_source`` جاهزين،
    فيُختبر بمصادر وهمية بلا أي شبكة حقيقية.
    """

    def __init__(self, ws_source: Optional[PriceSource], rest_source: PriceSource,
                 symbol: str):
        self._ws = ws_source
        self._rest = rest_source
        self.symbol = symbol
        self.mode = "WS" if ws_source is not None else "REST"
        self.alert: Optional[str] = None

    def get_price(self) -> Decimal:
        """يعيد أحدث سعر مفضّلًا WS، ويسقط إلى REST عند فشل WS."""
        self.alert = None
        if self._ws is not None:
            try:
                price = self._ws.get_price(self.symbol)
                self.mode = "WS"
                return price
            except MarketFeedError:
                # سقوط إلى REST مع تنبيه واضح
                self.mode = "REST"
                self.alert = ALERT_REST_FALLBACK
        price = self._rest.get_price(self.symbol)
        if self._ws is None:
            self.mode = "REST"
        return price

    def try_reconnect_ws(self) -> bool:
        """محاولة إعادة اتصال WS بعد سقوط REST؛ يُرجع True عند النجاح."""
        if self._ws is None:
            return False
        connect = getattr(self._ws, "connect", None)
        try:
            if callable(connect):
                connect()
            # جسّ سعر واحد للتأكد من عودة القناة
            self._ws.get_price(self.symbol)
        except MarketFeedError:
            self.mode = "REST"
            self.alert = ALERT_REST_FALLBACK
            return False
        self.mode = "WS"
        self.alert = None
        return True
