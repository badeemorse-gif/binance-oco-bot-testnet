import unittest
from decimal import Decimal

from ocobot.domain.exchange_info import ExchangeInfoService, parse_symbol_filters

SYMBOL_OBJ = {
    "symbol": "BTCUSDT",
    "filters": [
        {"filterType": "PRICE_FILTER", "tickSize": "0.01000000"},
        {"filterType": "LOT_SIZE", "stepSize": "0.00001000", "minQty": "0.00001000"},
        {"filterType": "NOTIONAL", "minNotional": "10.00000000"},
    ],
}


class FakeClient:
    def __init__(self, symbol_obj):
        self._symbol_obj = symbol_obj
        self.public_calls = 0

    def public_request(self, method, path, params=None):
        self.public_calls += 1
        return {"symbols": [self._symbol_obj]}


class TestExchangeInfo(unittest.TestCase):
    def test_parse_filters(self):
        f = parse_symbol_filters(SYMBOL_OBJ)
        self.assertEqual(f.tick_size, Decimal("0.01"))
        self.assertEqual(f.step_size, Decimal("0.00001"))
        self.assertEqual(f.min_qty, Decimal("0.00001"))
        self.assertEqual(f.min_notional, Decimal("10"))

    def test_get_filters_and_cache(self):
        client = FakeClient(SYMBOL_OBJ)
        svc = ExchangeInfoService(client, ttl_seconds=3600, monotonic=lambda: 100.0)
        a = svc.get_filters("btcusdt")  # case-insensitive
        b = svc.get_filters("BTCUSDT")
        self.assertEqual(client.public_calls, 1)  # served from cache
        self.assertIs(a, b)
        self.assertEqual(a.symbol, "BTCUSDT")

    def test_min_notional_legacy_key(self):
        obj = {
            "symbol": "ETHUSDT",
            "filters": [{"filterType": "MIN_NOTIONAL", "minNotional": "5"}],
        }
        self.assertEqual(parse_symbol_filters(obj).min_notional, Decimal("5"))


if __name__ == "__main__":
    unittest.main()
