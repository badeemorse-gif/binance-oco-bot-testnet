import unittest
from decimal import Decimal

from ocobot import views
from ocobot.domain.models import OcoOrder, SelectedOCO, SymbolFilters
from ocobot.domain.selection import build_dashboard


def _oco():
    return OcoOrder(
        order_list_id=31, symbol="BTCUSDT", status="EXECUTING",
        quantity=Decimal("0.5"), tp_price=Decimal("70000"),
        stop_trigger=Decimal("58500"), stop_limit=Decimal("58000"),
        leg_ids=[11, 12],
    )


class TestViews(unittest.TestCase):
    def test_orders_table_columns_and_values(self):
        out = views.render_orders_table([_oco()])
        for header in ("Order List ID", "Symbol", "Status", "Qty", "Sale/TP",
                       "Stop Trigger", "Limit After Trigger"):
            self.assertIn(header, out)
        self.assertIn("31", out)
        self.assertIn("BTCUSDT", out)
        self.assertIn("70000", out)
        self.assertIn("58500", out)

    def test_orders_table_empty(self):
        self.assertIn("لا توجد أوامر OCO مفتوحة", views.render_orders_table([]))

    def test_selected_view_locked_qty_and_filters(self):
        sel = SelectedOCO(
            order_list_id=31, symbol="BTCUSDT", quantity=Decimal("0.5"),
            tp=Decimal("70000"), stop_trigger=Decimal("58500"),
            stop_limit=Decimal("58000"), leg_ids=[11, 12], status="EXECUTING",
            filters=SymbolFilters(
                symbol="BTCUSDT", tick_size=Decimal("0.01"),
                step_size=Decimal("0.0001"), min_qty=Decimal("0.001"),
                min_notional=Decimal("10"),
            ),
        )
        out = views.render_selected_oco(sel)
        self.assertIn("\U0001f512", out)      # قفل الكمية
        self.assertIn("Read-only", out)
        self.assertIn("tickSize", out)
        self.assertIn("0.01", out)
        self.assertIn("Current Price", out)

    def test_dashboard_no_selection_message(self):
        out = views.render_dashboard(
            build_dashboard(None, environment="testnet", connection="OK"),
            has_selection=False,
        )
        self.assertIn("لم يُختَر أمر", out)
        self.assertIn("IDLE", out)


if __name__ == "__main__":
    unittest.main()
