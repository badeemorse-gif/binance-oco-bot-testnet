import json
import unittest

from ocobot.config import AppConfig
from ocobot.core.connection_state import ConnectionStatus
from ocobot.core.keys import ApiCredentials
from ocobot.core.preflight import run_preflight
from ocobot.core.rest_client import Response


class FakeTransport:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def send(self, method, url, headers, body):
        self.calls.append(url)
        return self._responses.pop(0)


def _resp(obj, status=200):
    return Response(status=status, headers={}, body=json.dumps(obj))


class TestPreflight(unittest.TestCase):
    def setUp(self):
        self.cfg = AppConfig(keys_path="x")
        self.creds = ApiCredentials(api_key="KEY12345678", api_secret="SECRETVALUE")

    def test_success_connected(self):
        transport = FakeTransport(
            [
                _resp({"serverTime": 5000}),
                _resp(
                    {
                        "canTrade": True,
                        "accountType": "SPOT",
                        "permissions": ["SPOT"],
                        "balances": [{"asset": "BTC", "free": "1.0"}],
                    }
                ),
            ]
        )
        st = run_preflight(
            self.cfg, transport=transport, now_ms=lambda: 1000, credentials=self.creds
        )
        self.assertEqual(st.status, ConnectionStatus.CONNECTED)
        self.assertEqual(st.clock_offset_ms, 4000)
        self.assertEqual(st.detail.get("canTrade"), True)
        # لا أرصدة ولا أسرار في الحالة المرئية
        self.assertNotIn("balances", st.detail)
        self.assertNotIn("SECRETVALUE", st.to_display())
        self.assertNotIn("KEY12345678", st.to_display())

    def test_bad_signature_error(self):
        transport = FakeTransport(
            [_resp({"serverTime": 5000}), _resp({"code": -1022, "msg": "bad"}, status=400)]
        )
        st = run_preflight(
            self.cfg, transport=transport, now_ms=lambda: 1000, credentials=self.creds
        )
        self.assertEqual(st.status, ConnectionStatus.ERROR)
        self.assertIn("-1022", st.message)

    def test_missing_keys_file_error(self):
        st = run_preflight(
            AppConfig(keys_path="D:/nope/key.txt"),
            transport=FakeTransport([]),
            now_ms=lambda: 1000,
        )
        self.assertEqual(st.status, ConnectionStatus.ERROR)


if __name__ == "__main__":
    unittest.main()
