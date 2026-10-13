# -*- coding: utf-8 -*-
"""اختبارات G1.44 / chunk_4 — تغطية i18n لكلّ نصّ عربي جديد (بلا QApplication).

رُكْن §1.5 / G1.28 / G1.41: الوضع الإنجليزي يجب ألّا يُبقي أيّ نصّ عربي ظاهر.
نؤكّد أن كلّ نصّ عربي جديد أدخله chunk_4 له مدخل في ``AR_TO_EN`` وأن ترجمته
الإنجليزية خالية من الحروف العربية.
"""
import re
import unittest

from ocobot.ui.i18n import AR_TO_EN
from ocobot.ui.guardian_indicator import _BTC_STATE_TEXT

# نطاق الحروف العربية (للتأكّد أن الترجمة الإنجليزية بلا عربية).
_ARABIC = re.compile(r"[\u0600-\u06FF]")

# كلّ نصّ عربي جديد يُعرض للمستخدم من chunk_4 (عناوين/أوضاع/حالات/بادئة تنبيه/ذيل).
_NEW_AR_STRINGS = [
    "حارس هبوط BTC",            # عنوان البطاقة + caption-ish
    "وضع حارس BTC",             # caption المُبدِّل
    "حارس BTC: مطفأ",
    "حارس BTC: نائم (يراقب)",
    "حارس BTC: رصد هبوط…",
    "حارس BTC: تدخّل ✓",
    "حارس BTC: —",              # fallback نصّ المؤشّر
    "حارس هبوط BTC على ",       # بادئة تنبيه BTC
    "نُفّذ خروج دفاعي (تضييق) عبر مسار الخروج المُختبَر.",
    "وضع مراقبة (Observe/dry_run): اقتراح تضييق دون تنفيذ.",
    "تعذّر تنفيذ التضييق؛ لا تغيير.",
]


class TestChunk4I18nCoverage(unittest.TestCase):
    def test_every_new_arabic_string_has_entry(self):
        missing = [s for s in _NEW_AR_STRINGS if s not in AR_TO_EN]
        self.assertEqual(missing, [], "نصوص عربية جديدة بلا مدخل AR_TO_EN: %r" % (missing,))

    def test_english_translations_have_no_arabic(self):
        for s in _NEW_AR_STRINGS:
            en = AR_TO_EN.get(s, "")
            self.assertFalse(
                _ARABIC.search(en),
                "ترجمة إنجليزية تحتوي عربية للنصّ %r ⇒ %r" % (s, en),
            )

    def test_btc_indicator_state_texts_are_covered(self):
        # كلّ نصّ حالة في مؤشّر BTC له مدخل ترجمة.
        for text in _BTC_STATE_TEXT.values():
            self.assertIn(text, AR_TO_EN, "نصّ حالة مؤشّر BTC بلا ترجمة: %r" % (text,))


if __name__ == "__main__":
    unittest.main()
