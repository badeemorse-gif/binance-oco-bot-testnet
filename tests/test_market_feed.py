"""اختبارات مصدر السعر الحيّ (M3 / T4) — REST + RFC6455 + Controller. بلا شبكة."""
import json
import struct
import unittest
from decimal import Decimal

from ocobot.core.market_feed import (
    ALERT_REST_FALLBACK,
    MarketFeedError,
    MarketWebSocketSource,
    PriceFeedController,
    RestPriceSource,
    build_ws_handshake_request,
    decode_frames,
    encode_client_frame,
)
from tests._fakes_monitoring import FakePriceSource, FakeSocket


class FakeRestClient:
    def __init__(self, price="123.45"):
        self._price = price
        self.calls = []

    def public_request(self, method, path, params=None):
        self.calls.append((method, path, dict(params or [])))
        return {"symbol": dict(params or []).get("symbol", ""), "price": self._price}


def _server_text_frame(text: bytes) -> bytes:
    """يبني إطار خادم نصّي غير مُقنّع (للاختبار)."""
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


class TestRestPriceSource(unittest.TestCase):
    def test_parses_price_to_decimal(self):
        client = FakeRestClient(price="77401.34000000")
        src = RestPriceSource(client)
        price = src.get_price("BTCUSDT")
        self.assertEqual(price, Decimal("77401.34000000"))
        self.assertEqual(client.calls[0][1], "/api/v3/ticker/price")
        self.assertEqual(client.calls[0][2]["symbol"], "BTCUSDT")

    def test_invalid_response_raises(self):
        class Bad:
            def public_request(self, *a, **k):
                return {"noprice": 1}
        with self.assertRaises(MarketFeedError):
            RestPriceSource(Bad()).get_price("BTCUSDT")


class TestFrameRoundTrip(unittest.TestCase):
    def test_encode_then_decode_yields_same_payload_masked(self):
        payload = b'{"method":"SUBSCRIBE"}'
        frame = encode_client_frame(payload)
        # البايت الثاني يجب أن يحمل بت القناع (0x80)
        self.assertTrue(frame[1] & 0x80)
        frames, rest = decode_frames(frame)
        self.assertEqual(rest, b"")
        self.assertEqual(len(frames), 1)
        opcode, decoded = frames[0]
        self.assertEqual(opcode, 0x1)
        self.assertEqual(decoded, payload)

    def test_decode_handles_16bit_length(self):
        payload = b"x" * 200   # > 125 => 16-bit length
        frame = _server_text_frame(payload)
        self.assertEqual(frame[1] & 0x7F, 126)
        frames, rest = decode_frames(frame)
        self.assertEqual(rest, b"")
        self.assertEqual(frames[0][1], payload)

    def test_decode_partial_buffer_keeps_remainder(self):
        payload = b"hello"
        frame = _server_text_frame(payload)
        frames, rest = decode_frames(frame[:3])  # إطار غير مكتمل
        self.assertEqual(frames, [])
        self.assertEqual(rest, frame[:3])

    def test_decode_ping_and_close_opcodes(self):
        ping = bytes([0x89, 0x00])          # ping, no payload
        close = bytes([0x88, 0x00])         # close, no payload
        frames, rest = decode_frames(ping + close)
        self.assertEqual(rest, b"")
        self.assertEqual([f[0] for f in frames], [0x9, 0x8])

    def test_handshake_request_shape(self):
        req = build_ws_handshake_request("example.com", "/ws/btcusdt@bookTicker", "abc==")
        text = req.decode("ascii")
        self.assertIn("GET /ws/btcusdt@bookTicker HTTP/1.1", text)
        self.assertIn("Host: example.com", text)
        self.assertIn("Upgrade: websocket", text)
        self.assertIn("Sec-WebSocket-Key: abc==", text)
        self.assertIn("Sec-WebSocket-Version: 13", text)
        self.assertTrue(text.endswith("\r\n\r\n"))


class TestMarketWebSocketSource(unittest.TestCase):
    def _connect_fn_factory(self, sock):
        def _connect(host, port):
            return sock
        return _connect

    def test_yields_bid_from_canned_book_ticker(self):
        handshake = b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n\r\n"
        book = json.dumps({"u": 1, "s": "BTCUSDT", "b": "77400.10", "a": "77400.50"}).encode()
        chunks = [handshake, _server_text_frame(book)]
        sock = FakeSocket(chunks)
        ws = MarketWebSocketSource(
            "wss://stream.testnet.binance.vision/ws", "BTCUSDT",
            connect_fn=self._connect_fn_factory(sock),
        )
        ws.connect()
        bid = ws.get_price("BTCUSDT")
        self.assertEqual(bid, Decimal("77400.10"))  # أفضل bid = سعر الخروج

    def test_disconnect_raises_market_feed_error(self):
        handshake = b"HTTP/1.1 101 Switching Protocols\r\n\r\n"
        sock = FakeSocket([handshake])  # لا مزيد من البيانات => recv يعيد b""
        ws = MarketWebSocketSource(
            "wss://stream.testnet.binance.vision/ws", "BTCUSDT",
            connect_fn=self._connect_fn_factory(sock),
        )
        ws.connect()
        with self.assertRaises(MarketFeedError):
            ws.get_price("BTCUSDT")


class TestPriceFeedController(unittest.TestCase):
    def test_prefers_ws(self):
        ws = FakePriceSource(prices=["100"])
        rest = FakePriceSource(prices=["200"])
        ctrl = PriceFeedController(ws, rest, "BTCUSDT")
        self.assertEqual(ctrl.get_price(), Decimal("100"))
        self.assertEqual(ctrl.mode, "WS")
        self.assertIsNone(ctrl.alert)

    def test_falls_back_to_rest_with_alert(self):
        ws = FakePriceSource(raise_error=True)
        rest = FakePriceSource(prices=["200"])
        ctrl = PriceFeedController(ws, rest, "BTCUSDT")
        price = ctrl.get_price()
        self.assertEqual(price, Decimal("200"))
        self.assertEqual(ctrl.mode, "REST")
        self.assertEqual(ctrl.alert, ALERT_REST_FALLBACK)
        self.assertEqual(ALERT_REST_FALLBACK, "سعر REST مؤقت")

    def test_reconnect_transition_back_to_ws(self):
        # ws يفشل أولًا ثم "يتعافى" (لا يرمي بعدها)
        class RecoveringWS:
            def __init__(self):
                self.fail = True
                self.connected = 0
            def connect(self):
                self.connected += 1
                self.fail = False
            def get_price(self, symbol=""):
                if self.fail:
                    raise MarketFeedError("down")
                return Decimal("111")
        ws = RecoveringWS()
        rest = FakePriceSource(prices=["200"])
        ctrl = PriceFeedController(ws, rest, "BTCUSDT")
        # أول نداء يسقط إلى REST
        self.assertEqual(ctrl.get_price(), Decimal("200"))
        self.assertEqual(ctrl.mode, "REST")
        # إعادة الاتصال تنجح وتعيد الوضع إلى WS
        self.assertTrue(ctrl.try_reconnect_ws())
        self.assertEqual(ctrl.mode, "WS")
        self.assertIsNone(ctrl.alert)
        self.assertEqual(ctrl.get_price(), Decimal("111"))


if __name__ == "__main__":
    unittest.main()
