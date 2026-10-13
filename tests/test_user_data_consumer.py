"""اختبارات مستهلك User Data Stream (M4e/2 · T9b) — بلا شبكة.

يُحاكي نمط ``tests.test_market_feed``: يحقن ``connect_fn`` يعيد ``FakeSocket``
مُغذًّى بإطارات خادم TEXT مُعلَّبة (JSON events)، ويتحقّق من:
  1) حالة حيّة عبر executionModeReport مُعلَّب — يُستدعى on_order_event بحقوله (T9#2).
  2) الإغلاق الخارجي (listStatus ALL_DONE و executionReport نهائي) للـ orderListId
     المختار يوقف المراقبة بلا إعادة تموضع — لا تُستدعى FakeSafeExecutor.execute
     والحالة CLOSED (T9#3).
  3) حدث لـ orderListId مختلف لا يغلق (P3).
  4) التحليل عبر FakeSocket + إطارات مُعلَّبة بلا socket حقيقي.
  5) الاتصال يستخدم ws_base + '/' + listen_key.
"""
import json
import struct
import unittest

from ocobot.core.user_data_consumer import UserDataStreamConsumer, UserDataConsumerError
from ocobot.domain.monitoring import MonitoringEngine, MonitoringStateEnum
from tests._fakes_monitoring import FakeSafeExecutor, FakeSocket

WS_BASE = "wss://stream.testnet.binance.vision/ws"
LISTEN_KEY = "pqia91ma19a5s61cv6a81va65sdf19v8a65a1a5f19v8a65a1"
SELECTED = 31
OTHER = 99


def _server_text_frame(text: bytes) -> bytes:
    """يبني إطار خادم TEXT غير مُقنّع (نفس مُساعد test_market_feed)."""
    payload = text
    length = len(payload)
    frame = bytearray([0x81])  # FIN + text
    if length < 126:
        frame.append(length)
    elif length < 65536:
        frame.append(126)
        frame.extend(struct.pack("!H", length))
    else:
        frame.append(127)
        frame.extend(struct.pack("!Q", length))
    frame.extend(payload)
    return bytes(frame)


def _evt(obj) -> bytes:
    return _server_text_frame(json.dumps(obj).encode())


_HANDSHAKE = b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n\r\n"


def _execution_report(*, order_list_id, order_status, exec_type="TRADE",
                      order_id=555, symbol="BTCUSDT"):
    return {
        "e": "executionReport",
        "E": 1700000000000,
        "s": symbol,
        "i": order_id,
        "X": order_status,
        "x": exec_type,
        "g": order_list_id,
    }


def _list_status(*, order_list_id, list_status_type="ALL_DONE",
                 list_order_status="ALL_DONE"):
    return {
        "e": "listStatus",
        "g": order_list_id,
        "l": list_status_type,
        "L": list_order_status,
    }


class TestUserDataConsumer(unittest.TestCase):
    def _connect_fn_factory(self, sock):
        def _connect(host, port):
            return sock
        return _connect

    def _make(self, chunks, *, on_order_event=None, on_external_close=None,
              listen_key=LISTEN_KEY, listen_key_manager=None,
              selected=SELECTED, capture_sock=None):
        sock = FakeSocket([_HANDSHAKE] + list(chunks))
        if capture_sock is not None:
            capture_sock.append(sock)
        return UserDataStreamConsumer(
            WS_BASE,
            listen_key=listen_key,
            listen_key_manager=listen_key_manager,
            selected_order_list_id=selected,
            on_order_event=on_order_event,
            on_external_close=on_external_close,
            connect_fn=self._connect_fn_factory(sock),
        )

    # (1) T9#2 — حالة الأمر تنعكس لحظيًا عبر executionReport
    def test_execution_report_updates_status_live(self):
        events = []
        # حدث حيّ غير نهائي (لا يُغلق) ثم انقطاع.
        chunks = [_evt(_execution_report(order_list_id=SELECTED,
                                         order_status="NEW", exec_type="NEW"))]
        consumer = self._make(chunks, on_order_event=events.append)
        with self.assertRaises(Exception):
            consumer.consume()  # ينتهي المخزون => انقطاع
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["e"], "executionReport")
        self.assertEqual(events[0]["X"], "NEW")
        self.assertEqual(events[0]["i"], 555)
        self.assertEqual(consumer.latest_order_status, "NEW")

    # (2) T9#3 — إغلاق خارجي (executionReport نهائي + listStatus ALL_DONE) يوقف المراقبة بلا إعادة تموضع
    def test_external_close_stops_monitoring_no_reposition(self):
        executor = FakeSafeExecutor()
        engine = MonitoringEngine(executor)
        engine.state.state = MonitoringStateEnum.MONITORING_ACTIVE
        engine.state.enabled = True

        chunks = [
            _evt(_execution_report(order_list_id=SELECTED, order_status="FILLED")),
            _evt(_list_status(order_list_id=SELECTED)),
        ]
        consumer = self._make(
            chunks, on_external_close=engine.notify_external_close
        )
        result = consumer.consume()  # يعود بسبب الإغلاق الخارجي، لا استثناء

        self.assertEqual(result, "external_close")
        self.assertEqual(engine.state.state, MonitoringStateEnum.CLOSED)
        self.assertFalse(engine.state.enabled)
        # لا إعادة تموضع إطلاقًا.
        self.assertEqual(executor.calls, [])

    # (2b) listStatus وحده (ALL_DONE) يكفي للإغلاق
    def test_list_status_all_done_alone_closes(self):
        executor = FakeSafeExecutor()
        engine = MonitoringEngine(executor)
        engine.state.state = MonitoringStateEnum.MONITORING_ACTIVE
        engine.state.enabled = True
        chunks = [_evt(_list_status(order_list_id=SELECTED,
                                    list_status_type="EXEC_STARTED",
                                    list_order_status="ALL_DONE"))]
        consumer = self._make(chunks, on_external_close=engine.notify_external_close)
        self.assertEqual(consumer.consume(), "external_close")
        self.assertEqual(engine.state.state, MonitoringStateEnum.CLOSED)
        self.assertEqual(executor.calls, [])

    # (3) P3 — حدث لقائمة مختلفة لا يُغلق
    def test_other_order_list_id_does_not_close(self):
        executor = FakeSafeExecutor()
        engine = MonitoringEngine(executor)
        engine.state.state = MonitoringStateEnum.MONITORING_ACTIVE
        engine.state.enabled = True
        closes = []

        def _on_close(reason):
            closes.append(reason)
            engine.notify_external_close(reason)

        chunks = [
            _evt(_execution_report(order_list_id=OTHER, order_status="FILLED")),
            _evt(_list_status(order_list_id=OTHER)),
        ]
        consumer = self._make(chunks, on_external_close=_on_close)
        with self.assertRaises(Exception):
            consumer.consume()  # لا إغلاق => ينتهي المخزون => انقطاع
        self.assertEqual(closes, [])
        self.assertEqual(engine.state.state, MonitoringStateEnum.MONITORING_ACTIVE)
        self.assertTrue(engine.state.enabled)
        self.assertEqual(executor.calls, [])

    # (4) بلا شبكة — التحليل يتم عبر FakeSocket فقط
    def test_parses_via_fake_socket_no_network(self):
        seen = []
        chunks = [_evt(_execution_report(order_list_id=SELECTED,
                                         order_status="PARTIALLY_FILLED",
                                         exec_type="TRADE"))]
        consumer = self._make(chunks, on_order_event=seen.append)
        with self.assertRaises(Exception):
            consumer.consume()
        self.assertEqual(seen[0]["X"], "PARTIALLY_FILLED")

    # (5) الاتصال يستخدم ws_base + '/' + listen_key
    def test_connect_uses_ws_base_slash_listen_key(self):
        captured = []
        chunks = [_evt(_execution_report(order_list_id=SELECTED, order_status="NEW"))]
        consumer = self._make(chunks, capture_sock=captured)
        consumer.connect()
        sock = captured[0]
        # أول ما أُرسِل هو طلب المصافحة، ويحوي المسار /ws/<listenKey>.
        handshake = sock.sent[0].decode("ascii")
        self.assertIn("GET /ws/" + LISTEN_KEY + " HTTP/1.1", handshake)

    # (6) دعم ListenKeyManager: يُقرأ listen_key ويُستدعى maybe_keepalive
    def test_listen_key_manager_keepalive_called(self):
        class FakeLKM:
            def __init__(self, key):
                self.listen_key = key
                self.keepalive_calls = 0

            def maybe_keepalive(self, now_ms=None):
                self.keepalive_calls += 1
                return False

        lkm = FakeLKM(LISTEN_KEY)
        chunks = [_evt(_list_status(order_list_id=SELECTED))]
        closed = []
        consumer = self._make(
            chunks, listen_key=None, listen_key_manager=lkm,
            on_external_close=closed.append,
        )
        self.assertEqual(consumer.consume(), "external_close")
        self.assertGreaterEqual(lkm.keepalive_calls, 1)
        self.assertEqual(len(closed), 1)


class TestUserDataConsumerReconnect(unittest.TestCase):
    """إعادة اتصال آمنة بعد انقطاع WS بلا فقد حالة (T9c)."""

    def _multi_connect_fn(self, socks):
        seq = list(socks)

        def _connect(host, port):
            if seq:
                return seq.pop(0)
            return None

        return _connect

    def _consumer(self, socks, *, max_reconnects, on_order_event=None,
                  on_external_close=None, selected=SELECTED):
        return UserDataStreamConsumer(
            WS_BASE,
            listen_key=LISTEN_KEY,
            selected_order_list_id=selected,
            on_order_event=on_order_event,
            on_external_close=on_external_close,
            connect_fn=self._multi_connect_fn(socks),
            max_reconnects=max_reconnects,
            sleep_fn=lambda _s: None,
        )

    # (A) T9#4 — انقطاع ثم socket جديد عبر connect_fn: يُستأنف الاستهلاك ويُغلق خارجيًا
    def test_reconnect_resumes_on_new_socket_and_closes(self):
        events = []
        sock1 = FakeSocket([
            _HANDSHAKE,
            _evt(_execution_report(order_list_id=SELECTED,
                                   order_status="NEW", exec_type="NEW")),
        ])  # ثم b'' => انقطاع
        sock2 = FakeSocket([
            _HANDSHAKE,
            _evt(_list_status(order_list_id=SELECTED)),
        ])  # ALL_DONE => إغلاق خارجي
        consumer = self._consumer(
            [sock1, sock2], max_reconnects=1, on_order_event=events.append,
        )
        result = consumer.consume()
        self.assertEqual(result, "external_close")
        self.assertEqual(events[0]["e"], "executionReport")
        self.assertEqual(events[0]["X"], "NEW")
        self.assertEqual(events[-1]["e"], "listStatus")
        self.assertEqual(consumer._reconnects_used, 1)

    # (B) لا إعادة تهيئة تفقد MonitoringState — إعادة الاتصال لا تمسّ حالة المحرّك
    def test_reconnect_preserves_monitoring_state_no_reposition(self):
        executor = FakeSafeExecutor()
        engine = MonitoringEngine(executor)
        engine.state.state = MonitoringStateEnum.MONITORING_ACTIVE
        engine.state.enabled = True
        engine.state.cursor = 7  # قيمة حارسة
        state_obj = engine.state

        sock1 = FakeSocket([
            _HANDSHAKE,
            _evt(_execution_report(order_list_id=SELECTED, order_status="NEW")),
        ])
        sock2 = FakeSocket([
            _HANDSHAKE,
            _evt(_execution_report(order_list_id=SELECTED,
                                   order_status="PARTIALLY_FILLED")),
        ])
        consumer = self._consumer(
            [sock1, sock2], max_reconnects=1,
            on_external_close=engine.notify_external_close,
        )
        with self.assertRaises(Exception):
            consumer.consume()  # الانقطاع الثاني ينفد بعده الرصيد => يُرفع
        self.assertIs(engine.state, state_obj)
        self.assertEqual(engine.state.cursor, 7)
        self.assertEqual(engine.state.state, MonitoringStateEnum.MONITORING_ACTIVE)
        self.assertTrue(engine.state.enabled)
        self.assertEqual(executor.calls, [])
        self.assertEqual(consumer._reconnects_used, 1)

    # (C-i) الافتراضي max_reconnects=0: انقطاع => يُرفع كما في T9b (توافق خلفي)
    def test_default_no_reconnect_raises_on_disconnect(self):
        sock = FakeSocket([
            _HANDSHAKE,
            _evt(_execution_report(order_list_id=SELECTED, order_status="NEW")),
        ])
        consumer = self._consumer([sock], max_reconnects=0)
        with self.assertRaises(UserDataConsumerError):
            consumer.consume()
        self.assertEqual(consumer._reconnects_used, 0)

    # (C-ii) connect_fn ينفد (يعيد None) عند إعادة الاتصال => سقوط إلى UserDataConsumerError
    def test_reconnect_exhausted_connect_fn_none_falls_back(self):
        sock1 = FakeSocket([
            _HANDSHAKE,
            _evt(_execution_report(order_list_id=SELECTED, order_status="NEW")),
        ])
        consumer = self._consumer([sock1], max_reconnects=1)  # لا sock2 => None
        with self.assertRaises(UserDataConsumerError):
            consumer.consume()
        self.assertEqual(consumer._reconnects_used, 1)


if __name__ == "__main__":
    unittest.main()
