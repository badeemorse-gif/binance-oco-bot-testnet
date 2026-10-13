# -*- coding: utf-8 -*-
"""G1.20 (AC4) — اختبار تبديل لغة الواجهة عبر زر LanguageToggle.

يتحقق من السلوك الذي يوفّره الكود المُنفَّذ فعليًا:

- عند الإقلاع: اللغة الحالية عربية ("ar") والاتجاه RightToLeft.
- بعد تبديل واحد: اللغة إنجليزية ("en") والاتجاه LeftToRight.
- بعد تبديل آخر: العودة إلى العربية ("ar") والاتجاه RightToLeft.

التبديل يُفعَّل عبر المسار الموصول الحقيقي: النقر على زر
``languageToggle`` في التوب-بار (يصدر الإشارة ``language_toggle_requested``
الموصولة بـ ``MainWindow._on_language_toggle``، الذي ينفّذ
``i18n.toggle_language`` + ``i18n.apply_direction`` + ``i18n.retranslate_widget_tree``).

كل شيء offscreen كي يعمل بلا شاشة على Windows، على نمط باقي اختبارات الواجهة.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest

from ocobot.ui._qt import Qt, QApplication, QPushButton
from ocobot.ui.theme import apply_theme
from ocobot.ui.app import build_app
from ocobot.ui import i18n


class G120LanguageToggleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    def setUp(self):
        # اللغة حالة module-level؛ نضمن بدءًا نظيفًا بالعربية لكل اختبار.
        i18n.set_language("ar")
        # نبني التطبيق + النافذة ونفرض الاتجاه الابتدائي كما يفعل مسار الإقلاع.
        self.app, self.window = build_app()
        i18n.apply_direction(self.app, self.window)

    def tearDown(self):
        # إعادة الحالة إلى الافتراضي كي لا يتسرّب التبديل لاختبارات أخرى.
        i18n.set_language("ar")
        i18n.apply_direction(self.app, self.window)

    def _lang_button(self):
        btn = self.window.topbar.findChild(QPushButton, "languageToggle")
        self.assertIsNotNone(btn, "زر تبديل اللغة (languageToggle) مفقود في التوب-بار")
        return btn

    def _click_toggle(self):
        # النقر عبر المسار الموصول الحقيقي: إصدار الإشارة المرتبطة بالمعالج.
        self._lang_button().click()

    def test_default_launch_is_arabic_rtl(self):
        self.assertEqual(i18n.get_language(), "ar")
        self.assertEqual(
            self.app.layoutDirection(), Qt.LayoutDirection.RightToLeft
        )
        self.assertEqual(
            self.window.layoutDirection(), Qt.LayoutDirection.RightToLeft
        )

    def test_single_toggle_switches_to_english_ltr(self):
        self._click_toggle()
        self.assertEqual(i18n.get_language(), "en")
        self.assertEqual(
            self.app.layoutDirection(), Qt.LayoutDirection.LeftToRight
        )
        self.assertEqual(
            self.window.layoutDirection(), Qt.LayoutDirection.LeftToRight
        )

    def test_second_toggle_returns_to_arabic_rtl(self):
        self._click_toggle()
        self._click_toggle()
        self.assertEqual(i18n.get_language(), "ar")
        self.assertEqual(
            self.app.layoutDirection(), Qt.LayoutDirection.RightToLeft
        )
        self.assertEqual(
            self.window.layoutDirection(), Qt.LayoutDirection.RightToLeft
        )


if __name__ == "__main__":
    unittest.main()
