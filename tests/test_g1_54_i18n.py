# -*- coding: utf-8 -*-
"""G1.54 chunk_3 — اختبارات i18n §1.5 ثنائية اللغة + retranslate للوحة الربحية.

يتحقّق (تحت ``QT_QPA_PLATFORM=offscreen``):
  - كل مفاتيح اللوحة الجديدة تُترجَم إلى الإنجليزية (لا تبقى عربية في EN).
  - تسميات الأوضاع ثنائية اللغة.
  - بعد set_language("en") + retranslate لا يتبقّى أي حرف عربي في نصوص اللوحة
    الثابتة (عنوان/زرّ/بطاقات)، سواء عبر retranslate_widget_tree أو داخل الشاشة 08.
يُعيد اللغة إلى "ar" في tearDown حفاظًا على الحالة العامّة لبقية السويت.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import unittest
from decimal import Decimal
from types import SimpleNamespace

from ocobot.domain.profitability import ModeProfitability
from ocobot.ui._qt import QApplication
from ocobot.ui import i18n
from ocobot.ui import profitability_panel as pp
from ocobot.ui.profitability_panel import ProfitabilityPanel
from ocobot.ui.completed_trades import CompletedTradesScreen


def _app():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _has_arabic(text):
    return any("\u0600" <= ch <= "\u06ff" for ch in (text or ""))


def _stats():
    return {
        "MANUAL_EXIT": ModeProfitability(
            mode="MANUAL_EXIT", n=2, win_rate=Decimal("100"),
            avg_return_pct=Decimal("5"), net_usd=Decimal("100"),
            expectancy=Decimal("50"), avg_slippage_pct=Decimal("0.2")),
        "MONITORING": ModeProfitability(
            mode="MONITORING", n=2, win_rate=Decimal("50"),
            avg_return_pct=Decimal("0.5"), net_usd=Decimal("20"),
            expectancy=Decimal("5")),
    }


class G1_54I18nTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def setUp(self):
        i18n.set_language("ar")

    def tearDown(self):
        i18n.set_language("ar")

    def test_keys_translate_to_english(self):
        i18n.set_language("en")
        pairs = {
            "ملخّص الربحية": "Profitability Summary",
            "كل الأوضاع": "All Modes",
            "معدّل الربح": "Win Rate",
            "الصافي": "Net",
            "التوقّع/صفقة": "Expectancy/Trade",
            "متوسط الانزلاق": "Avg Slippage",
            "عدد الصفقات": "Trades",
            "رابحة": "Wins",
            "خاسرة": "Losses",
            "لا بيانات ربحية بعد.": "No profitability data yet.",
        }
        for ar, en in pairs.items():
            self.assertEqual(i18n.translate(ar), en)
            self.assertFalse(_has_arabic(i18n.translate(ar)))

    def test_mode_labels_bilingual(self):
        i18n.set_language("ar")
        self.assertEqual(pp.mode_label("MANUAL_EXIT"), "خروج يدوي")
        i18n.set_language("en")
        self.assertEqual(pp.mode_label("MANUAL_EXIT"), "Manual Exit")
        self.assertEqual(pp.mode_label("MONITORING"), "Dynamic Monitoring")
        self.assertEqual(pp.mode_label("BTC_FOLLOW"), "BTC Follow")

    def test_panel_retranslate_no_arabic_leak(self):
        panel = ProfitabilityPanel()
        panel.set_data(_stats(), [])
        self.assertTrue(_has_arabic(panel.heading.text()))  # عربي افتراضًا

        i18n.set_language("en")
        i18n.retranslate_widget_tree(panel)

        self.assertEqual(panel.heading.text(), "Profitability Summary")
        self.assertEqual(panel.all_button.text(), "All Modes")
        self.assertEqual(panel._cards["MANUAL_EXIT"].title.text(), "Manual Exit")
        for txt in (panel.heading.text(), panel.all_button.text(),
                    panel.lb_head.text(), panel.curve_head.text(),
                    panel.dist_head.text(), panel.leaderboard.text(),
                    panel._cards["MANUAL_EXIT"].title.text()):
            self.assertFalse(_has_arabic(txt), "تسرّب عربي: %r" % txt)

    def test_screen_retranslate_wires_panel(self):
        tmp = tempfile.mkdtemp(prefix="g1_54_i18n_")
        screen = CompletedTradesScreen(audit_path=os.path.join(tmp, "x.jsonl"))
        screen.set_trades([
            SimpleNamespace(trade_key="k", symbol="BTCUSDT",
                            reference_price=Decimal("100"), closed_at="t",
                            profit_available=True, profit_pct=Decimal("5"),
                            profit_usd=Decimal("50"), session_id="", end_reason="",
                            status="closed", exit_source="MANUAL_EXIT", steps=[]),
        ])
        i18n.set_language("en")
        i18n.retranslate_widget_tree(screen)
        self.assertEqual(screen.profit_panel.heading.text(), "Profitability Summary")
        self.assertFalse(_has_arabic(screen.profit_panel.all_button.text()))


if __name__ == "__main__":
    unittest.main()
