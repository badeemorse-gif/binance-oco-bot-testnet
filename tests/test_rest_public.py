import json
import unittest

from ocobot.config import AppConfig
from ocobot.core.keys import ApiCredentials
from ocobot.core.rest_client import Response, SignedRestClient


class FakeTransport:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def send(self, method, url, headers, body):
        self.calls.append({"method": method, "url": url, "headers": headers})
        return self._responses.pop(0)


def _resp(obj, status=200):
    return Response(status=status, headers={}, body=json.dumps(obj))


class TestPublicRequest(unittest.TestCase):
    def test_public_get_no_signature_no_apikey_header(self):
        transport = FakeTransport([_resp({"symbols": []})])
        client = SignedRestClient(
            AppConfig(keys_path="x"), ApiCredentials("K", "S"),
            transport=transport, now_ms=lambda: 1000,
        )
        client.public_request("GET", "/api/v3/exchangeInfo", [("symbol", "BTCUSDT")])
        call = transport.calls[0]
        self.assertIn("symbol=BTCUSDT", call["url"])
        self.assertNotIn("signature=", call["url"])  # unsigned
        self.assertEqual(call["headers"], {})         # no X-MBX-APIKEY


if __name__ == "__main__":
    unittest.main()
