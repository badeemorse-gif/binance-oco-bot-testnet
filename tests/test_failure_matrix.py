"""اختبارات جدول الأخطاء → رسائل عربية (T5 / M4).

يتحقّق أن -1021 / -1022 / 429 / 418 / FAILED_NEEDS_ATTENTION وخطأ غير معروف
تُترجَم كلّها إلى سلسلة عربية بشرية غير فارغة، وأن نصّ الاستثناء الخام / stack
لا يظهر حرفيًا في المخرجات أبدًا (معيار القبول: No raw Exception messages).
"""
import unittest

from ocobot.core.errors import BinanceApiError, OcoBotError, TransportError
from ocobot.core.failure_matrix import (
    FAILED_NEEDS_ATTENTION,
    FailureMatrix,
    humanize,
)


def _has_arabic(text: str) -> bool:
    return any("\u0600" <= ch <= "\u06ff" for ch in text)


class TestFailureMatrix(unittest.TestCase):
    def _assert_human(self, msg: str):
        self.assertIsInstance(msg, str)
        self.assertTrue(msg.strip(), "الرسالة يجب ألّا تكون فارغة")
        self.assertTrue(_has_arabic(msg), "الرسالة يجب أن تكون عربية بشرية")

    def test_binance_1021(self):
        msg = humanize(BinanceApiError(-1021, "Timestamp for this request is outside of the recvWindow"))
        self._assert_human(msg)
        self.assertIn("-1021", msg)

    def test_binance_1022(self):
        msg = humanize(BinanceApiError(-1022, "Signature for this request is not valid"))
        self._assert_human(msg)
        self.assertIn("-1022", msg)

    def test_http_429_rate_limit(self):
        msg = humanize(BinanceApiError(None, "Too many requests", http_status=429))
        self._assert_human(msg)

    def test_http_418_ip_ban(self):
        msg = humanize(BinanceApiError(None, "IP banned", http_status=418))
        self._assert_human(msg)

    def test_failed_needs_attention_string(self):
        msg = humanize(FAILED_NEEDS_ATTENTION)
        self._assert_human(msg)

    def test_unknown_error_falls_back(self):
        msg = humanize(RuntimeError("boom"))
        self._assert_human(msg)

    def test_raw_exception_text_never_returned_verbatim(self):
        raw = "Traceback (most recent call last): SUPERSECRETSTACKTOKEN at line 42"
        err = BinanceApiError(-9999, raw, http_status=500)
        msg = humanize(err)
        self._assert_human(msg)
        self.assertNotIn(raw, msg)
        self.assertNotIn("SUPERSECRETSTACKTOKEN", msg)
        self.assertNotIn("Traceback", msg)

    def test_generic_exception_message_not_leaked(self):
        raw = "KABOOM-INTERNAL-DETAIL-1234"
        msg = humanize(OcoBotError(raw))
        self._assert_human(msg)
        self.assertNotIn(raw, msg)

    def test_class_and_function_api_agree(self):
        err = BinanceApiError(-1022, "sig")
        self.assertEqual(humanize(err), FailureMatrix.humanize(err))


if __name__ == "__main__":
    unittest.main()
