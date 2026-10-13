import unittest

from ocobot.config import RECV_WINDOW_MAX, AppConfig
from ocobot.core.environment import Environment


class TestConfig(unittest.TestCase):
    def test_defaults_testnet(self):
        cfg = AppConfig()
        self.assertEqual(cfg.env, Environment.TESTNET)
        self.assertEqual(cfg.rest_base(), "https://testnet.binance.vision/api")

    def test_recv_window_clamped(self):
        self.assertEqual(AppConfig(recv_window=999999).recv_window, RECV_WINDOW_MAX)
        self.assertEqual(AppConfig(recv_window=0).recv_window, 1)

    def test_for_env_switches_base_and_key_source_only(self):
        cfg = AppConfig(keys_path="X", recv_window=7000)
        live = cfg.for_env("live")
        self.assertEqual(live.env, Environment.LIVE)
        self.assertEqual(live.rest_base(), "https://api.binance.com")
        # نفس المفاتيح/الإعداد — التبديل يغيّر البيئة (base URL + مصدر المفتاح) فقط
        self.assertEqual(live.keys_path, "X")
        self.assertEqual(live.recv_window, 7000)


if __name__ == "__main__":
    unittest.main()
