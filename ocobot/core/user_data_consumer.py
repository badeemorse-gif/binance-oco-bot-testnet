"""مستهلك User Data Stream (M4e/2 · T9b؛ إعادة اتصال آمنة · T9c) — WS بـ stdlib + تحليل الأحداث.

يعيد استخدام دوال RFC6455 الخالصة ونمط ``connect_fn`` المحقون من
``MarketWebSocketSource`` (``ocobot.core.market_feed``) — لا شبكة أثناء الاختبار.

الوظيفة:
  - يتّصل بـ ``ws_base + '/' + listen_key`` (وليس ``@bookTicker``) عبر listenKey
    مُدار عبر ``ListenKeyManager`` (أو ``listen_key`` نصّي مباشر).
  - يقرأ إطارات الخادم، يفكّها، ويحلّل كل رسالة TEXT كـ JSON ويوزّعها حسب ``e``:
      * ``executionReport``: يحدّث حالة الأمر لحظيًا عبر ``on_order_event`` (فحص
        T9 رقم 2)؛ وإن كان ``g`` == القائمة المختارة و ``X`` حالة نهائية =>
        إغلاق خارجي.
      * ``listStatus``: إن كان ``g`` == القائمة المختارة و ``ALL_DONE`` ضمن
        {``l``, ``L``} => إغلاق خارجي.
      * تُتجاهَل الأحداث ذات ``orderListId`` مختلف عن المختار (P3).
  - عند الإغلاق الخارجي: يستدعي مسار إيقاف المراقبة (``on_external_close``) ثم
    يتوقّف ويعود — لا إعادة تموضع أبدًا (فحص T9 رقم 3).

إعادة الاتصال (T9c): عند انقطاع/إغلاق WS وإن بقيت محاولات (``max_reconnects``)
يُعاد الاتصال بنفس listenKey عبر ``connect_fn`` مع استمرارية keepalive دون فقد
حالة المراقبة (الحالة تعيش في ``MonitoringEngine``، لا يمسّها المستهلك)؛ وإذا
نفدت المحاولات أو تعذّر الحصول على وصلة يُرفع الاستثناء كما في السابق
(الافتراضي ``max_reconnects=0`` = لا إعادة اتصال، سلوك T9b كما هو). stdlib فقط؛
لا يُسجَّل listenKey/مفتاح API أبدًا (يُعاد استخدام ``mask_key`` عند الحاجة للتسجيل).
"""
from __future__ import annotations

import json
import logging
from decimal import Decimal, InvalidOperation
from typing import Callable, Optional
from urllib.parse import urlparse

from ocobot.core.errors import OcoBotError
from ocobot.core.market_feed import (
    OPCODE_CLOSE,
    OPCODE_PING,
    OPCODE_PONG,
    OPCODE_TEXT,
    build_ws_handshake_request,
    decode_frames,
    encode_client_frame,
    make_ws_key,
)
from ocobot.core.redaction import mask_key

logger = logging.getLogger(__name__)

# حالات الأمر النهائية على مستوى executionReport (X = orderStatus).
_TERMINAL_ORDER_STATUSES = {"FILLED", "CANCELED", "EXPIRED", "REJECTED"}
# قيمة إتمام قائمة OCO على مستوى listStatus (l = listStatusType, L = listOrderStatus).
_ALL_DONE = "ALL_DONE"


class UserDataConsumerError(OcoBotError):
    """خطأ في مستهلك User Data Stream (اتصال/مصافحة/انقطاع)."""


class UserDataStreamConsumer:
    """عميل WS خفيف (stdlib) يستهلك User Data Stream ويحلّل أحداثه.

    يُمرَّر ``listen_key`` نصّيًا مباشرة، أو ``ListenKeyManager`` (يُقرأ منه
    ``listen_key`` ويُستدعى ``maybe_keepalive`` كل دورة). ``connect_fn`` محقون
    (socket-like) لاختبار إطارات مُعلَّبة بلا شبكة — نفس نمط
    ``MarketWebSocketSource``.
    """

    def __init__(
        self,
        ws_base: str,
        *,
        listen_key: Optional[str] = None,
        listen_key_manager=None,
        selected_order_list_id: int,
        on_order_event: Optional[Callable[[dict], None]] = None,
        on_external_close: Optional[Callable[[str], None]] = None,
        connect_fn: Optional[Callable] = None,
        max_reconnects: int = 0,
        sleep_fn: Optional[Callable[[float], None]] = None,
        reconnect_backoff: float = 0.0,
    ):
        if listen_key is None and listen_key_manager is None:
            raise UserDataConsumerError(
                "يلزم listen_key أو listen_key_manager لمستهلك User Data Stream."
            )
        self._ws_base = ws_base
        self._listen_key = listen_key
        self._lkm = listen_key_manager
        self.selected_order_list_id = int(selected_order_list_id)
        self._on_order_event = on_order_event
        self._on_external_close = on_external_close
        self._connect_fn = connect_fn or self._default_connect
        # إعادة الاتصال (T9c): محدودة وقابلة للحقن (بلا نوم حقيقي في الاختبار).
        self._max_reconnects = int(max_reconnects)
        self._sleep_fn = sleep_fn or (lambda _s: None)
        self._reconnect_backoff = float(reconnect_backoff)
        self._reconnects_used = 0
        self._sock = None
        self._buffer = b""
        self._closed_externally = False
        # آخر حالة أمر معروفة (لحظيًا) — لا سعر وهمي.
        self.latest_order_status: Optional[str] = None

    # --- listenKey ---
    def _resolve_listen_key(self) -> str:
        if self._lkm is not None:
            key = self._lkm.listen_key
        else:
            key = self._listen_key
        if not key:
            raise UserDataConsumerError("لا يوجد listenKey متاح للاتصال.")
        return key

    # --- connection ---
    def _default_connect(self, host: str, port: int):
        import socket
        import ssl

        raw = socket.create_connection((host, port), timeout=10.0)
        ctx = ssl.create_default_context()
        return ctx.wrap_socket(raw, server_hostname=host)

    def connect(self) -> None:
        listen_key = self._resolve_listen_key()
        parsed = urlparse(self._ws_base)
        host = parsed.hostname or ""
        port = parsed.port or (443 if parsed.scheme in ("wss", "https") else 80)
        base_path = parsed.path or "/ws"
        # المسار = ws_base + '/' + listenKey (وليس bookTicker).
        path = base_path.rstrip("/") + "/" + listen_key
        try:
            self._sock = self._connect_fn(host, port)
            if self._sock is None:
                raise UserDataConsumerError(
                    "connect_fn لم يُعِد وصلة (لا مزيد من السوكِتات)."
                )
            key = make_ws_key()
            self._sock.sendall(build_ws_handshake_request(host, path, key))
            self._read_handshake_response()
        except Exception as exc:  # noqa: BLE001
            # لا نكشف listenKey في الخطأ (D8/P).
            raise UserDataConsumerError(f"فشل اتصال User Data WebSocket: {exc}") from exc

    def _read_handshake_response(self) -> None:
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise UserDataConsumerError("انقطاع أثناء handshake.")
            data += chunk
        head, _, rest = data.partition(b"\r\n\r\n")
        if b"101" not in head.split(b"\r\n", 1)[0]:
            raise UserDataConsumerError(f"handshake فاشل: {head[:80]!r}")
        self._buffer += rest

    # --- reading / dispatch ---
    def _handle_execution_report(self, event: dict) -> None:
        status = event.get("X")
        if status is not None:
            self.latest_order_status = status
        if self._on_order_event is not None:
            self._on_order_event(event)
        # P3: نتعامل فقط مع القائمة المختارة.
        if event.get("g") != self.selected_order_list_id:
            return
        if status in _TERMINAL_ORDER_STATUSES:
            self._trigger_external_close(
                f"executionReport terminal X={status} orderListId={self.selected_order_list_id}"
            )

    def _handle_list_status(self, event: dict) -> None:
        if self._on_order_event is not None:
            self._on_order_event(event)
        # P3: نتعامل فقط مع القائمة المختارة.
        if event.get("g") != self.selected_order_list_id:
            return
        if _ALL_DONE in {event.get("l"), event.get("L")}:
            self._trigger_external_close(
                f"listStatus ALL_DONE orderListId={self.selected_order_list_id}"
            )

    def _dispatch(self, payload: bytes) -> None:
        try:
            event = json.loads(payload.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return
        if not isinstance(event, dict):
            return
        etype = event.get("e")
        if etype == "executionReport":
            self._handle_execution_report(event)
        elif etype == "listStatus":
            self._handle_list_status(event)
        # أنواع أخرى تُتجاهَل بأمان.

    def _trigger_external_close(self, reason: str) -> None:
        """يوقف المراقبة عبر on_external_close ثم يعلّم التوقّف — لا إعادة تموضع."""
        if self._closed_externally:
            return
        self._closed_externally = True
        if self._on_external_close is not None:
            self._on_external_close(reason)

    def _pump_once(self) -> None:
        """يقرأ دفعة، يفكّ الإطارات، ويوزّع رسائل TEXT."""
        if self._sock is None:
            raise UserDataConsumerError("WebSocket غير متّصل.")
        chunk = self._sock.recv(4096)
        if not chunk:
            raise UserDataConsumerError("انقطاع WebSocket.")
        self._buffer += chunk
        frames, self._buffer = decode_frames(self._buffer)
        for opcode, payload in frames:
            if opcode == OPCODE_CLOSE:
                raise UserDataConsumerError("أُغلقت الوصلة من الخادم.")
            if opcode == OPCODE_PING:
                try:
                    self._sock.sendall(encode_client_frame(payload, OPCODE_PONG))
                except Exception:  # noqa: BLE001
                    pass
                continue
            if opcode == OPCODE_TEXT:
                self._dispatch(payload)

    def _reconnect(self) -> None:
        """يعيد الاتصال بنفس listenKey عبر connect_fn دون فقد حالة المراقبة (T9c).

        يُغلق الوصلة الحالية ويصفّر المخزن المؤقّت ثم يتّصل من جديد. لا يمسّ
        ``_closed_externally`` ولا حالة المحرّك (تعيش في MonitoringEngine).
        """
        self.close()
        self._buffer = b""
        if self._reconnect_backoff:
            self._sleep_fn(self._reconnect_backoff)
        self.connect()

    def consume(self) -> str:
        """يستهلك حتى الإغلاق الخارجي أو نفاد محاولات إعادة الاتصال؛ يعيد سبب التوقّف.

        عند انقطاع/إغلاق WS: إن بقيت محاولات (``max_reconnects``) يُعاد الاتصال
        بنفس listenKey مع استمرارية keepalive دون فقد حالة المراقبة (T9c)؛ وإلا
        يُرفع الاستثناء كما في السابق (الافتراضي ``max_reconnects=0``).
        """
        if self._sock is None:
            self.connect()
        try:
            while not self._closed_externally:
                try:
                    # keepalive عند الحاجة إن أُعطي مدير listenKey.
                    if self._lkm is not None:
                        try:
                            self._lkm.maybe_keepalive()
                        except Exception:  # noqa: BLE001
                            pass
                    self._pump_once()
                except UserDataConsumerError:
                    if self._closed_externally:
                        break
                    if self._reconnects_used < self._max_reconnects:
                        self._reconnects_used += 1
                        self._reconnect()
                        continue
                    raise
        finally:
            self.close()
        return "external_close"

    # alias بأسلوب المشروع
    run = consume

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:  # noqa: BLE001
                pass
            self._sock = None
