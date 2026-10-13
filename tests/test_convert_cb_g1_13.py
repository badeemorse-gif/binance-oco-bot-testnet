import unittest
from decimal import Decimal

from ocobot.app_wiring import make_convert_cb, build_convert_executor
from ocobot.domain.models import OpenSellOrder
from ocobot.domain.convert import ConvertExecutor
from ocobot.domain.reposition import ExecutionState
from tests._fakes_monitoring import make_result


def _standalone():
    return OpenSellOrder(
        symbol="LSKUSDT", orderId=123, orderListId=-1, order_type="LIMIT",
        side="SELL", price="100", stopPrice="0", trailingDelta="",
        origQty="1", executedQty="0", status="NEW", time=1,
        is_oco=False, oco_group_id=None, badge="LIMIT",
    )


class FakeConvertExecutor:
    def __init__(self):
        self.calls = []
        self.result = make_result(ExecutionState.SUCCESS, new_order_list_id=99)

    def convert(self, source, tp_pct, sl_pct, reference_price, dry_run=False):
        self.calls.append({
            "source": source, "tp_pct": tp_pct, "sl_pct": sl_pct,
            "reference_price": reference_price, "dry_run": dry_run,
        })
        return self.result


class FakePriceProvider:
    def __init__(self, price):
        self.price = price
        self.symbols = []

    def set_symbol(self, symbol):
        self.symbols.append(symbol)

    def get_price(self):
        return self.price


class ConvertCbG113Tests(unittest.TestCase):
    def test_fetches_live_price_when_no_reference(self):
        fx = FakeConvertExecutor()
        fp = FakePriceProvider(Decimal("100"))
        cb = make_convert_cb(fx, fp)
        r = cb(_standalone(), Decimal("4"), Decimal("2"))
        self.assertEqual(fp.symbols, ["LSKUSDT"])
        self.assertEqual(len(fx.calls), 1)
        self.assertEqual(fx.calls[0]["reference_price"], Decimal("100"))
        self.assertIs(r, fx.result)

    def test_uses_provided_reference_price(self):
        fx = FakeConvertExecutor()
        fp = FakePriceProvider(None)
        cb = make_convert_cb(fx, fp)
        cb(_standalone(), Decimal("4"), Decimal("2"), reference_price=Decimal("123"))
        self.assertEqual(fp.symbols, [])
        self.assertEqual(fx.calls[0]["reference_price"], Decimal("123"))

    def test_raises_when_live_price_none(self):
        fx = FakeConvertExecutor()
        fp = FakePriceProvider(None)
        cb = make_convert_cb(fx, fp)
        with self.assertRaises(ValueError):
            cb(_standalone(), Decimal("4"), Decimal("2"))
        self.assertEqual(fx.calls, [])

    def test_passes_dry_run_through(self):
        fx = FakeConvertExecutor()
        fp = FakePriceProvider(Decimal("100"))
        cb = make_convert_cb(fx, fp)
        cb(_standalone(), Decimal("4"), Decimal("2"), reference_price=Decimal("100"), dry_run=True)
        self.assertIs(fx.calls[0]["dry_run"], True)

    def test_build_convert_executor_returns_convert_executor(self):
        ex = build_convert_executor(object())
        self.assertIsInstance(ex, ConvertExecutor)


if __name__ == "__main__":
    unittest.main()
