# -*- coding: utf-8 -*-
"""اختبارات G1.45 / chunk_1 — منطق PercentTracker الخالص + تغطية i18n (§1.5).

لا QApplication: نختبر الدوال الخالصة (نسبة/اتجاه/تنسيق/لون) + وجود مفاتيح
الترجمة الإنجليزية الخالية من العربية لكلّ عنوان جديد.
"""
import re
import unittest
from decimal import Decimal

from ocobot.ui.percent_tracker import (
    UP, DOWN, FLAT,
    pct_change, direction_key, format_pct, format_price, color_for, _CAPTIONS,
)
from ocobot.ui.theme import PALETTE
from ocobot.ui.i18n import AR_TO_EN

_ARABIC = re.compile(r"[\u0600-\u06FF]")


class TestPercentChange(unittest.TestCase):
    def test_rise(self):
        self.assertEqual(pct_change(Decimal("101"), Decimal("100")), Decimal("1"))

    def test_drop(self):
        self.assertEqual(pct_change(Decimal("99"), Decimal("100")), Decimal("-1"))

    def test_flat(self):
        self.assertEqual(pct_change(Decimal("100"), Decimal("100")), Decimal("0"))

    def test_undefined_on_zero_or_none(self):
        self.assertIsNone(pct_change(Decimal("100"), Decimal("0")))
        self.assertIsNone(pct_change(None, Decimal("100")))
        self.assertIsNone(pct_change(Decimal("100"), None))


class TestDirection(unittest.TestCase):
    def test_keys(self):
        self.assertEqual(direction_key(Decimal("0.0001")), UP)
        self.assertEqual(direction_key(Decimal("-0.0001")), DOWN)
        self.assertEqual(direction_key(Decimal("0")), FLAT)
        self.assertEqual(direction_key(None), FLAT)


class TestFormatPct(unittest.TestCase):
    def test_five_decimals_and_sign(self):
        self.assertEqual(format_pct(Decimal("1")), "+1.00000%")
        self.assertEqual(format_pct(Decimal("-2")), "-2.00000%")
        self.assertEqual(format_pct(Decimal("0")), "0.00000%")

    def test_none_is_neutral_placeholder(self):
        # مطلب المستخدم: متاح افتراضيًّا بصيغة 0.00000%.
        self.assertEqual(format_pct(None), "0.00000%")

    def test_rounds_to_five(self):
        self.assertEqual(format_pct(Decimal("1.2345678")), "+1.23457%")


class TestFormatPrice(unittest.TestCase):
    def test_none_is_dash(self):
        self.assertEqual(format_price(None), "—")

    def test_trims_trailing_zeros(self):
        self.assertEqual(format_price(Decimal("100.5000")), "100.5")
        self.assertEqual(format_price(Decimal("100")), "100")

    def test_no_scientific_notation(self):
        self.assertNotIn("E", format_price(Decimal("100")))


class TestColor(unittest.TestCase):
    def test_colors_match_palette(self):
        self.assertEqual(color_for(Decimal("1")), PALETTE["GREEN"])
        self.assertEqual(color_for(Decimal("-1")), PALETTE["RED"])
        self.assertEqual(color_for(Decimal("0")), PALETTE["MUTED"])
        self.assertEqual(color_for(None), PALETTE["MUTED"])


class TestI18nCoverage(unittest.TestCase):
    def test_every_caption_has_english_without_arabic(self):
        for cap in _CAPTIONS:
            self.assertIn(cap, AR_TO_EN, "عنوان بلا مدخل AR_TO_EN: %r" % (cap,))
            en = AR_TO_EN.get(cap, "")
            self.assertFalse(_ARABIC.search(en), "ترجمة تحوي عربية للعنوان %r ⇒ %r" % (cap, en))


if __name__ == "__main__":
    unittest.main()
