import unittest
from decimal import Decimal

from ocobot.domain.oco_reader import OcoReader
from tests._fakes import FakeClient


class TestOcoReader(unittest.TestCase):
    def test_list_open_ocos_maps_three_prices(self):
        ocos = OcoReader(FakeClient()).list_open_ocos()
        self.assertEqual(len(ocos), 1)
        o = ocos[0]
        self.assertEqual(o.order_list_id, 31)
        self.assertEqual(o.symbol, "BTCUSDT")
        self.assertEqual(o.status, "EXECUTING")
        self.assertEqual(o.quantity, Decimal("0.5"))
        # 3 أسعار (D1): TP / trigger / limit
        self.assertEqual(o.tp_price, Decimal("70000.00"))
        self.assertEqual(o.stop_trigger, Decimal("58500.00"))
        self.assertEqual(o.stop_limit, Decimal("58000.00"))
        self.assertEqual(o.leg_ids, [11, 12])

    def test_row_has_required_columns(self):
        row = OcoReader(FakeClient()).list_open_ocos()[0].to_row()
        for key in ("orderListId", "symbol", "status", "qty", "saleTp",
                    "stopTrigger", "limitAfterTrigger"):
            self.assertIn(key, row)

    def test_get_oco_by_id(self):
        o = OcoReader(FakeClient()).get_oco(31)
        self.assertEqual(o.order_list_id, 31)
        self.assertEqual(o.stop_trigger, Decimal("58500.00"))


if __name__ == "__main__":
    unittest.main()
