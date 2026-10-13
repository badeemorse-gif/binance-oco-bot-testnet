# -*- coding: utf-8 -*-
"""اختبارات واجهة بطاقة نتيجة الصفقة (DealResultCard) — G1.46.

تتحقّق من: الإظهار/الإخفاء حسب توفّر نتيجة، تعبئة الدخول/الخروج/الجانب/الربح،
وثنائية اللغة §1.5 (التبديل EN↔AR دون تسرّب أي حرف عربي في وضع الإنجليزية).
تعمل تحت ``QT_QPA_PLATFORM=offscreen``.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest
from decimal import Decimal
from types import SimpleNamespace

from ocobot.ui._qt import QApplication, QLabel
from ocobot.ui.deal_result_card import DealResultCard
from ocobot.ui import i18n


def _app():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _has_arabic(text):
    return any("\u0600" <= ch <= "\u06ff" for ch in (text or ""))


class DealResultCardUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def setUp(self):
        i18n.set_language("ar")

    def tearDown(self):
        i18n.set_language("ar")

    def _trade(self, **kw):
        base = dict(
            reference_price=Decimal("100"), exit_price=Decimal("104"),
            side="SELL", profit_pct=Decimal("4"), profit_usd=Decimal("8"),
            profit_available=True, status="closed", exit_source="PRICE_BRACKET",
        )
        base.update(kw)
        return SimpleNamespace(**base)

    def test_hidden_when_no_result(self):
        card = DealResultCard()
        card.update_result(None)
        self.assertTrue(card.isHidden())
        self.assertEqual(card._val_entry.text(), "—")

    def test_populates_and_shows_on_result(self):
        card = DealResultCard()
        card.update_result(self._trade())
        self.assertFalse(card.isHidden())
        self.assertEqual(card._val_entry.text(), "100")
        self.assertEqual(card._val_exit.text(), "104")
        self.assertEqual(card._val_side.text(), "SELL")
        self.assertIn("%", card._val_pnl.text())

    def test_profit_unavailable_shows_dash_pnl(self):
        card = DealResultCard()
        card.update_result(self._trade(profit_available=False))
        self.assertEqual(card._val_pnl.text(), "—")

    def test_bilingual_en_no_arabic_leak(self):
        card = DealResultCard()
        card.update_result(self._trade())
        i18n.set_language("en")
        i18n.retranslate_widget_tree(card)
        self.assertEqual(card._title.text(), "Deal Result")
        for lab in card.findChildren(QLabel):
            self.assertFalse(
                _has_arabic(lab.text()),
                "تسرّب عربي في وضع الإنجليزية: %r" % lab.text(),
            )

    def test_bilingual_toggle_back_to_arabic(self):
        card = DealResultCard()
        card.update_result(self._trade())
        i18n.set_language("en")
        i18n.retranslate_widget_tree(card)
        i18n.set_language("ar")
        i18n.retranslate_widget_tree(card)
        self.assertEqual(card._title.text(), "نتيجة الصفقة")


if __name__ == "__main__":
    unittest.main()
