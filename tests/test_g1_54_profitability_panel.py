# -*- coding: utf-8 -*-
"""G1.54 chunk_1 — اختبارات مكوّن لوحة الربحية (عرض فقط) + دواله الخالصة.

يغطّي الدوال الخالصة بلا QApplication (التنسيق/الترتيب/السلسلة التراكمية/التوزيع/
الهندسة/اللون)، ثم بناء الودجت تحت ``QT_QPA_PLATFORM=offscreen`` والتحقّق من
ترتيب البطاقات (leaderboard)، إشارة ``modeSelected``، حالة الفراغ، وعدم انهيار
retranslate — كلّه عرض فقط بلا شبكة.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest
from decimal import Decimal
from types import SimpleNamespace

from ocobot.domain.profitability import ModeProfitability
from ocobot.ui._qt import QApplication
from ocobot.ui.theme import PALETTE
from ocobot.ui import profitability_panel as pp
from ocobot.ui.profitability_panel import ProfitabilityPanel


def _app():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _ms(mode, exp, net, win="50", avg="1", n=2, slip=None):
    return ModeProfitability(
        mode=mode, n=n, win_rate=Decimal(win), avg_return_pct=Decimal(avg),
        net_usd=Decimal(net), expectancy=(None if exp is None else Decimal(exp)),
        avg_slippage_pct=(None if slip is None else Decimal(slip)))


def _trade(pct, usd, mode="MONITORING", status="closed"):
    return SimpleNamespace(
        trade_key="k-%s-%s" % (mode, pct), exit_source=mode, status=status,
        profit_pct=(None if pct is None else Decimal(pct)),
        profit_usd=(None if usd is None else Decimal(usd)))


class PureHelperTests(unittest.TestCase):
    def test_fmt_pct(self):
        self.assertEqual(pp.fmt_pct(Decimal("5")), "+5.00%")
        self.assertEqual(pp.fmt_pct(Decimal("-3")), "-3.00%")
        self.assertEqual(pp.fmt_pct(Decimal("0")), "0.00%")
        self.assertEqual(pp.fmt_pct(None), "—")

    def test_fmt_usd(self):
        self.assertEqual(pp.fmt_usd(Decimal("20")), "+20.00 $")
        self.assertEqual(pp.fmt_usd(Decimal("-10")), "-10.00 $")
        self.assertEqual(pp.fmt_usd(None), "—")

    def test_win_rate_fraction_clamped(self):
        self.assertEqual(pp.win_rate_fraction(Decimal("50")), 0.5)
        self.assertEqual(pp.win_rate_fraction(Decimal("150")), 1.0)
        self.assertEqual(pp.win_rate_fraction(Decimal("-5")), 0.0)
        self.assertEqual(pp.win_rate_fraction(None), 0.0)

    def test_order_modes_by_expectancy_none_last(self):
        stats = {
            "MONITORING": _ms("MONITORING", "5", "20"),
            "MANUAL_EXIT": _ms("MANUAL_EXIT", "50", "100"),
            "BTC_FOLLOW": _ms("BTC_FOLLOW", "25", "50"),
            "POSITION_SAFETY_NET": _ms("POSITION_SAFETY_NET", None, "0"),
        }
        self.assertEqual(
            pp.order_modes_by_expectancy(stats),
            ["MANUAL_EXIT", "BTC_FOLLOW", "MONITORING", "POSITION_SAFETY_NET"])

    def test_cumulative_pnl_chronological(self):
        # الأحدث أولًا من الـdomain: [+10, -4, +2] ⇒ زمنيًّا [+2, -4, +10].
        trades = [_trade("1", "10"), _trade("1", "-4"), _trade("1", "2")]
        self.assertEqual(pp.cumulative_pnl(trades),
                         [Decimal("2"), Decimal("-2"), Decimal("8")])

    def test_cumulative_pnl_skips_live_and_missing(self):
        trades = [_trade("1", "5"), _trade("1", None), _trade("9", "9", status="live")]
        self.assertEqual(pp.cumulative_pnl(trades), [Decimal("5")])

    def test_win_loss_counts(self):
        trades = [_trade("2", "1"), _trade("-1", "-1"), _trade("4", "4"),
                  _trade("0", "0"), _trade(None, None)]
        self.assertEqual(pp.win_loss_counts(trades), (2, 1, 1))

    def test_win_loss_counts_by_mode(self):
        trades = [_trade("2", "1", mode="MANUAL_EXIT"),
                  _trade("-1", "-1", mode="MONITORING")]
        self.assertEqual(pp.win_loss_counts(trades, mode="MANUAL_EXIT"), (1, 0, 0))

    def test_polyline_points(self):
        pts = pp.polyline_points([Decimal("0"), Decimal("10")], 100, 50, pad=8.0)
        self.assertEqual(len(pts), 2)
        self.assertAlmostEqual(pts[0][0], 8.0)
        self.assertAlmostEqual(pts[0][1], 42.0)
        self.assertAlmostEqual(pts[1][0], 92.0)
        self.assertAlmostEqual(pts[1][1], 8.0)
        self.assertEqual(pp.polyline_points([], 100, 50), [])

    def test_color_for(self):
        self.assertEqual(pp.color_for(Decimal("1")), PALETTE.get("GREEN", "#19c58b"))
        self.assertEqual(pp.color_for(Decimal("-1")), PALETTE.get("RED", "#ff4b68"))
        self.assertEqual(pp.color_for(Decimal("0")), PALETTE.get("MUTED", "#6f8ba2"))
        self.assertEqual(pp.color_for(None), PALETTE.get("MUTED", "#6f8ba2"))


class ProfitabilityPanelWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def _stats(self):
        return {
            "MONITORING": _ms("MONITORING", "5", "20", win="50"),
            "MANUAL_EXIT": _ms("MANUAL_EXIT", "50", "100", win="100"),
            "BTC_FOLLOW": _ms("BTC_FOLLOW", "25", "50", win="0"),
        }

    def test_cards_follow_leaderboard_order(self):
        panel = ProfitabilityPanel()
        panel.set_data(self._stats(), [_trade("2", "20"), _trade("-1", "-10")])
        self.assertEqual(panel.card_modes(), ["MANUAL_EXIT", "BTC_FOLLOW", "MONITORING"])
        # عند وجود بيانات: رسالة الفراغ مخفية (isHidden يعكس النيّة بلا إظهار الأب).
        self.assertTrue(panel.empty_note.isHidden())

    def test_card_shows_win_rate_text(self):
        panel = ProfitabilityPanel()
        panel.set_data(self._stats(), [])
        self.assertEqual(panel._cards["MANUAL_EXIT"].win_rate_val.text(), "+100.00%")

    def test_mode_selected_signal_and_highlight(self):
        panel = ProfitabilityPanel()
        panel.set_data(self._stats(), [])
        received = []
        panel.modeSelected.connect(received.append)
        panel._on_select("MANUAL_EXIT")
        self.assertEqual(received, ["MANUAL_EXIT"])
        self.assertEqual(panel.active_mode(), "MANUAL_EXIT")
        self.assertTrue(panel._cards["MANUAL_EXIT"]._selected)
        self.assertFalse(panel._cards["MONITORING"]._selected)

    def test_all_button_clears_filter(self):
        panel = ProfitabilityPanel()
        panel.set_data(self._stats(), [])
        panel._on_select("MANUAL_EXIT")
        received = []
        panel.modeSelected.connect(received.append)
        panel._on_select("")
        self.assertEqual(received, [""])
        self.assertEqual(panel.active_mode(), "")

    def test_empty_data_shows_note_no_cards(self):
        panel = ProfitabilityPanel()
        panel.set_data({}, [])
        self.assertFalse(panel.empty_note.isHidden())
        self.assertEqual(panel.card_modes(), [])

    def test_retranslate_does_not_crash(self):
        panel = ProfitabilityPanel()
        panel.set_data(self._stats(), [_trade("2", "20")])
        panel.retranslate_i18n()
        self.assertEqual(len(panel.card_modes()), 3)


if __name__ == "__main__":
    unittest.main()
