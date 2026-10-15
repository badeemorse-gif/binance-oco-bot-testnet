# -*- coding: utf-8 -*-
"""اختبارات G1.56 · c6 — لوحة ترشيح النِّسب (rec_panel.py) + §1.5."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import re
import unittest
from decimal import Decimal

from ocobot.ui._qt import QApplication
from ocobot.ui import i18n
from ocobot.ui import rec_panel
from ocobot.ui.rec_panel import (MODE_LIVE, MODE_OBSERVE, MODE_OFF,
                                 RecommendationPanel, format_rec_fields,
                                 _FIELDS, _MODE_ITEMS, _TITLE, _FILL_BTN,
                                 _MODE_CAPTION)
from ocobot.domain.recommender import Recommendation

_ARABIC = re.compile(r"[\u0600-\u06FF\uFB50-\uFDFF\uFE70-\uFEFF]")


def _rec():
    return Recommendation(
        tp_pct=Decimal("5.5"), sl_pct=Decimal("4.0"), trigger_pct=Decimal("0.7"),
        gap_ticks=2, rationale={"regimeLabel": "trending"},
        flags=["liquidity_thin", "tp_tick_floor"])


class FormatPureTests(unittest.TestCase):
    def test_none_dashes(self):
        f = format_rec_fields(None)
        self.assertEqual(f["tp"], "—")
        self.assertEqual(f["gap"], "—")
        self.assertEqual(f["flags"], "")

    def test_values(self):
        f = format_rec_fields(_rec())
        self.assertEqual(f["tp"], "5.5%")
        self.assertEqual(f["sl"], "4%")
        self.assertEqual(f["trigger"], "0.7%")
        self.assertEqual(f["gap"], "2")
        self.assertEqual(f["regime"], "trending")
        self.assertIn("liquidity_thin", f["flags"])


class PanelWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        i18n.set_language("ar")

    def tearDown(self):
        i18n.set_language("ar")

    def test_update_sets_values_and_enables_fill(self):
        p = RecommendationPanel()
        self.assertFalse(p._fill_btn.isEnabled())
        p.update_recommendation(_rec())
        self.assertTrue(p._fill_btn.isEnabled())
        self.assertEqual(p.value_texts()["tp"], "5.5%")
        self.assertEqual(p.value_texts()["gap"], "2")

    def test_update_none_disables_fill(self):
        p = RecommendationPanel()
        p.update_recommendation(_rec())
        p.update_recommendation(None)
        self.assertFalse(p._fill_btn.isEnabled())
        self.assertEqual(p.value_texts()["tp"], "—")

    def test_fill_once_callback(self):
        got = []
        p = RecommendationPanel(on_fill_once=got.append)
        p._on_fill_clicked()  # لا شيء بلا اقتراح
        self.assertEqual(got, [])
        rec = _rec()
        p.update_recommendation(rec)
        p._on_fill_clicked()
        self.assertEqual(got, [rec])

    def test_mode_default_and_change(self):
        changes = []
        p = RecommendationPanel(on_mode_change=changes.append)
        self.assertEqual(p.mode(), MODE_OBSERVE)
        p.set_mode(MODE_LIVE)
        self.assertEqual(p.mode(), MODE_LIVE)
        self.assertIn(MODE_LIVE, changes)
        p.set_mode(MODE_OFF)
        self.assertEqual(p.mode(), MODE_OFF)

    def test_english_mode_no_arabic_leak(self):
        p = RecommendationPanel()
        p.update_recommendation(_rec())
        i18n.set_language("en")
        i18n.retranslate_widget_tree(p)
        chrome = [p._title.text(), p._fill_btn.text(), p._mode_caption.text()]
        chrome += p.caption_texts()
        chrome += [p._mode_combo.itemText(i) for i in range(p._mode_combo.count())]
        offenders = [t for t in chrome if _ARABIC.search(t or "")]
        self.assertEqual(offenders, [], "تسرّب عربي: %r" % (offenders,))
        self.assertEqual(p._fill_btn.text(), "Fill Once")

    def test_arabic_mode_restored(self):
        p = RecommendationPanel()
        i18n.set_language("en")
        i18n.retranslate_widget_tree(p)
        i18n.set_language("ar")
        i18n.retranslate_widget_tree(p)
        self.assertEqual(p._fill_btn.text(), _FILL_BTN)


class I18nCoverageTests(unittest.TestCase):
    def test_all_source_literals_mapped_without_arabic(self):
        literals = [_TITLE, _FILL_BTN, _MODE_CAPTION]
        literals += [cap for _k, cap in _FIELDS]
        literals += [ar for ar, _k in _MODE_ITEMS]
        for lit in literals:
            self.assertIn(lit, i18n.AR_TO_EN, "بلا مدخل: %r" % (lit,))
            en = i18n.AR_TO_EN[lit]
            self.assertFalse(_ARABIC.search(en), "ترجمة تحوي عربية: %r=>%r" % (lit, en))


if __name__ == "__main__":
    unittest.main()
