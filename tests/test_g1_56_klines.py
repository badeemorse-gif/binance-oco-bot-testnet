"""اختبارات G1.56 · c5 — خدمة جلب الشموع + cache (klines.py)."""
import unittest

from ocobot.core.errors import OcoBotError
from ocobot.domain import klines as kl
from ocobot.domain.volatility import Candle


def _kline_row(o, h, l, c, v):
    return [1700000000000, str(o), str(h), str(l), str(c), str(v),
            1700000599999, "0", 5, "0", "0", "0"]


class FakeClient:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def public_request(self, method, path, params=None):
        self.calls.append((method, path, dict(params or [])))
        return list(self.rows)


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class GetCandlesTests(unittest.TestCase):
    def setUp(self):
        self.rows = [_kline_row(100, 110, 95, 105, 12),
                     _kline_row(105, 112, 100, 108, 20)]
        self.client = FakeClient(self.rows)
        self.clock = FakeClock()
        self.svc = kl.KlinesService(self.client, ttl_seconds=300,
                                    monotonic=self.clock)

    def test_parses_to_candles(self):
        cs = self.svc.get_candles("btcusdt", "1h", 2)
        self.assertEqual(len(cs), 2)
        self.assertEqual(cs[0], Candle(100.0, 110.0, 95.0, 105.0, 12.0))
        # السيمبول يُرفع إلى uppercase في الطلب
        self.assertEqual(self.client.calls[0][2]["symbol"], "BTCUSDT")
        self.assertEqual(self.client.calls[0][2]["interval"], "1h")

    def test_cache_hit_no_second_call(self):
        self.svc.get_candles("BTCUSDT", "1h", 2)
        self.svc.get_candles("BTCUSDT", "1h", 2)
        self.assertEqual(len(self.client.calls), 1)

    def test_cache_expiry_refetch(self):
        self.svc.get_candles("BTCUSDT", "1h", 2)
        self.clock.t += 301  # تجاوز TTL
        self.svc.get_candles("BTCUSDT", "1h", 2)
        self.assertEqual(len(self.client.calls), 2)

    def test_force_refresh(self):
        self.svc.get_candles("BTCUSDT", "1h", 2)
        self.svc.get_candles("BTCUSDT", "1h", 2, force_refresh=True)
        self.assertEqual(len(self.client.calls), 2)

    def test_distinct_keys(self):
        self.svc.get_candles("BTCUSDT", "1h", 2)
        self.svc.get_candles("BTCUSDT", "4h", 2)
        self.assertEqual(len(self.client.calls), 2)
        self.assertEqual(len(self.svc.cached_keys()), 2)

    def test_invalidate(self):
        self.svc.get_candles("BTCUSDT", "1h", 2)
        self.svc.invalidate("BTCUSDT")
        self.assertEqual(self.svc.cached_keys(), [])

    def test_validation_errors(self):
        with self.assertRaises(OcoBotError):
            self.svc.get_candles("", "1h", 2)
        with self.assertRaises(OcoBotError):
            self.svc.get_candles("BTCUSDT", "7m", 2)
        with self.assertRaises(OcoBotError):
            self.svc.get_candles("BTCUSDT", "1h", 0)
        with self.assertRaises(OcoBotError):
            self.svc.get_candles("BTCUSDT", "1h", 5000)

    def test_non_list_response_raises(self):
        bad = kl.KlinesService(FakeClient(self.rows), monotonic=self.clock)
        bad._client.rows = {"not": "a list"}
        # FakeClient returns list(self.rows); dict(...) -> list of keys, so force a mapping
        class BadClient:
            def public_request(self, *a, **k):
                return {"msg": "err"}
        svc = kl.KlinesService(BadClient(), monotonic=self.clock)
        with self.assertRaises(OcoBotError):
            svc.get_candles("BTCUSDT", "1h", 2)


class FetcherTests(unittest.TestCase):
    def test_build_fetcher_zero_arg(self):
        rows = [_kline_row(100, 110, 95, 105, 12)]
        svc = kl.KlinesService(FakeClient(rows), monotonic=FakeClock())
        fetch = kl.build_klines_fetcher(svc, "BTCUSDT", "1h", 1)
        cs = fetch()
        self.assertEqual(len(cs), 1)
        self.assertIsInstance(cs[0], Candle)


if __name__ == "__main__":
    unittest.main()
