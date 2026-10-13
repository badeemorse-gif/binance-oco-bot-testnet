import unittest
from ocobot.domain.open_orders_reader import read_all_open_sell_orders

class _FakeRest:
    def __init__(self, orders): self._orders = orders
    def get_open_orders(self, symbol=None): return self._orders

def _mk(**kw):
    base = {"symbol": "LSKUSDT", "side": "SELL", "orderListId": -1,
            "price": "0", "stopPrice": "0", "origQty": "1",
            "executedQty": "0", "status": "NEW", "time": 1}
    base.update(kw); return base

class TestReadAllOpenSellOrders(unittest.TestCase):
    def setUp(self):
        self.orders = [
            _mk(orderId=1, type="LIMIT", price="10"),
            _mk(orderId=2, type="STOP_LOSS_LIMIT", stopPrice="8", trailingDelta=150),
            _mk(orderId=3, type="TAKE_PROFIT_LIMIT", price="12", stopPrice="12"),
            _mk(orderId=4, type="LIMIT_MAKER", price="13", orderListId=555),
            _mk(orderId=5, type="STOP_LOSS_LIMIT", stopPrice="7", orderListId=555),
            _mk(orderId=6, type="LIMIT", price="99", side="BUY"),  # يُستبعد
        ]
        self.rows = read_all_open_sell_orders(_FakeRest(self.orders))

    def test_buy_excluded(self):
        self.assertTrue(all(r.side == "SELL" for r in self.rows))
        self.assertNotIn(6, [r.orderId for r in self.rows if r.orderId is not None])

    def test_row_count(self):  # 3 مستقلة + 1 OCO = 4
        self.assertEqual(len(self.rows), 4)

    def test_standalone_badges(self):
        by_id = {r.orderId: r for r in self.rows if r.orderId is not None}
        self.assertEqual(by_id[1].badge, "LIMIT")
        self.assertIn("TRAILING", by_id[2].badge)
        self.assertEqual(by_id[3].badge, "TAKE_PROFIT_LIMIT")

    def test_oco_collapsed(self):
        oco = [r for r in self.rows if r.is_oco]
        self.assertEqual(len(oco), 1)
        self.assertEqual(oco[0].oco_group_id, 555)
        self.assertEqual(oco[0].badge, "OCO")

if __name__ == "__main__":
    unittest.main()
