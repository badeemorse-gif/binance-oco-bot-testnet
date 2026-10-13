import unittest
from decimal import Decimal

from ocobot.domain.exchange_info import ExchangeInfoService
from ocobot.domain.oco_reader import OcoReader
from ocobot.domain.selection import Selector, build_dashboard
from tests._fakes import FakeClient


def _selector(client):
    return Selector(OcoReader(client), ExchangeInfoService(client, monotonic=lambda: 1.0))


class TestSelection(unittest.TestCase):
    def test_select_establishes_live_context(self):
        selector = _selector(FakeClient())
        sel = selector.select(31)
        self.assertEqual(sel.order_list_id, 31)
        self.assertEqual(sel.symbol, "BTCUSDT")
        self.assertEqual(sel.quantity, Decimal("0.5"))
        self.assertTrue(sel.quantity_locked)  # Read-only (D7)
        self.assertIsNotNone(sel.filters)     # Filters من exchangeInfo (D8)
        self.assertEqual(sel.filters.tick_size, Decimal("0.01"))
        self.assertIsNone(sel.current_price)  # D14: لا سعر حيّ وهمي
        self.assertIs(selector.selected, sel)

    def test_dashboard_before_selection_all_placeholders(self):
        snap = build_dashboard(None, environment="testnet", connection="OK")
        self.assertEqual(snap.selected_oco, "—")
        self.assertEqual(snap.symbol, "—")
        self.assertEqual(snap.current_price, "—")
        self.assertEqual(snap.monitoring_state, "IDLE")
        self.assertEqual(snap.environment, "testnet")

    def test_dashboard_after_selection(self):
        selector = _selector(FakeClient())
        sel = selector.select(31)
        snap = build_dashboard(sel, environment="testnet", connection="OK")
        self.assertEqual(snap.selected_oco, "31")
        self.assertEqual(snap.symbol, "BTCUSDT")
        self.assertEqual(snap.current_tp, "70000")
        self.assertEqual(snap.current_price, "—")  # still no live price in M1


if __name__ == "__main__":
    unittest.main()
