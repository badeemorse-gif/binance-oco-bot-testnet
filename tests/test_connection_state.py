import unittest

from ocobot.core.connection_state import ConnectionState, ConnectionStatus
from ocobot.core.environment import Environment


class TestConnectionState(unittest.TestCase):
    def test_display_and_dict_have_no_secret(self):
        st = ConnectionState(
            status=ConnectionStatus.CONNECTED,
            environment=Environment.TESTNET,
            rest_base="https://testnet.binance.vision/api",
            key_hint="tke\u2026789",
            clock_offset_ms=-12,
            message="ok",
            detail={"canTrade": True},
        )
        self.assertTrue(st.is_connected())

        d = st.to_dict()
        self.assertEqual(d["status"], "CONNECTED")
        self.assertNotIn("api_secret", d)

        text = st.to_display()
        self.assertIn("testnet", text)
        self.assertIn("CONNECTED", text)
        self.assertIn("secret redacted", text)

    def test_default_disconnected(self):
        self.assertFalse(ConnectionState().is_connected())


if __name__ == "__main__":
    unittest.main()
