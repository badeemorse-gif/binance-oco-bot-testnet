import unittest

from ocobot.core.environment import Environment, join_url, rest_base_url, ws_base_url


class TestEnvironment(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(Environment.parse("TESTNET"), Environment.TESTNET)
        self.assertEqual(Environment.parse("live"), Environment.LIVE)
        with self.assertRaises(ValueError):
            Environment.parse("mainnet")

    def test_base_urls(self):
        self.assertEqual(
            rest_base_url(Environment.TESTNET), "https://testnet.binance.vision/api"
        )
        self.assertEqual(rest_base_url(Environment.LIVE), "https://api.binance.com")
        self.assertTrue(ws_base_url(Environment.TESTNET).startswith("wss://"))

    def test_join_url_no_double_api(self):
        self.assertEqual(
            join_url("https://testnet.binance.vision/api", "/api/v3/time"),
            "https://testnet.binance.vision/api/v3/time",
        )
        self.assertEqual(
            join_url("https://api.binance.com", "/api/v3/time"),
            "https://api.binance.com/api/v3/time",
        )


if __name__ == "__main__":
    unittest.main()
