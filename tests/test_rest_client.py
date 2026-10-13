import json
import unittest

from ocobot.config import AppConfig
from ocobot.core.keys import ApiCredentials
from ocobot.core.rest_client import Response, SignedRestClient
from ocobot.core.errors import BinanceApiError


class FakeTransport:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []
        self.last_request = None  # for compatibility with Opus template

    def send(self, method, url, headers, body):
        call = {"method": method, "url": url, "headers": headers, "body": body}
        self.calls.append(call)
        # Opus template expects transport.last_request with method/path/query
        # Build simple object
        class Req:
            def __init__(self, method, url):
                self.method = method
                self.url = url
                # extract path and query
                from urllib.parse import urlparse
                parsed = urlparse(url)
                self.path = parsed.path
                self.query = parsed.query

        self.last_request = Req(method, url)
        return self._responses.pop(0)


def _resp(obj, status=200, headers=None):
    return Response(status=status, headers=headers or {}, body=json.dumps(obj))


class TestG113RestClient(unittest.TestCase):
    def setUp(self):
        self.cfg = AppConfig(keys_path="x", recv_window=5000)
        self.creds = ApiCredentials(api_key="KEY", api_secret="SECRET")

    def _client(self, responses):
        transport = FakeTransport(responses)
        client = SignedRestClient(
            self.cfg, self.creds, transport=transport, now_ms=lambda: 1000
        )
        return client, transport

    def test_get_open_orders_signed_get(self):
        client, transport = self._client([
            _resp({"serverTime": 5000}),
            _resp([]),
        ])
        result = client.get_open_orders()
        self.assertEqual(result, [])
        req = transport.calls[1]
        self.assertEqual(req["method"], "GET")
        self.assertIn("/api/v3/openOrders", req["url"])
        self.assertIn("signature=", req["url"])
        self.assertIn("timestamp=", req["url"])

    def test_get_open_orders_with_symbol(self):
        client, transport = self._client([
            _resp({"serverTime": 5000}),
            _resp([]),
        ])
        client.get_open_orders(symbol="LSKUSDT")
        url = transport.calls[1]["url"]
        self.assertIn("symbol=LSKUSDT", url)

    def test_cancel_order_by_orderId(self):
        client, transport = self._client([
            _resp({"serverTime": 5000}),
            _resp({}),
        ])
        client.cancel_order(symbol="LSKUSDT", orderId=123)
        req = transport.calls[1]
        self.assertEqual(req["method"], "DELETE")
        self.assertIn("/api/v3/order", req["url"])
        self.assertIn("orderId=123", req["url"])
        self.assertIn("signature=", req["url"])
        self.assertIn("symbol=LSKUSDT", req["url"])

    def test_cancel_order_by_clientId(self):
        client, transport = self._client([
            _resp({"serverTime": 5000}),
            _resp({}),
        ])
        client.cancel_order(symbol="LSKUSDT", origClientOrderId="abc")
        url = transport.calls[1]["url"]
        self.assertIn("origClientOrderId=abc", url)

    def test_cancel_order_requires_exactly_one_id(self):
        client, _ = self._client([
            _resp({"serverTime": 5000}),
            _resp({}),
        ])
        with self.assertRaises(ValueError):
            client.cancel_order(symbol="LSKUSDT")  # لا شيء
        with self.assertRaises(ValueError):
            client.cancel_order(symbol="LSKUSDT", orderId=1, origClientOrderId="x")  # الاثنان


if __name__ == "__main__":
    unittest.main()
