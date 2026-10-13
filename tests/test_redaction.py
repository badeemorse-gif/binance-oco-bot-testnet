import logging
import unittest

from ocobot.core.redaction import (
    RedactingFilter,
    mask_key,
    mask_secret,
    redact_signature,
)


class TestRedaction(unittest.TestCase):
    def test_redact_signature(self):
        url = "https://x/api/v3/account?timestamp=1&signature=deadBEEF0123456789abcdef"
        out = redact_signature(url)
        self.assertIn("signature=***", out)
        self.assertNotIn("deadBEEF0123456789abcdef", out)

    def test_mask_secret_always_masked(self):
        self.assertNotIn("whatever", mask_secret("whatever"))

    def test_mask_key(self):
        self.assertEqual(mask_key("abcdefghij"), "abc\u2026hij")
        self.assertEqual(mask_key("short"), "\u2022\u2022\u2022\u2022")

    def test_logging_filter_scrubs(self):
        rec = logging.LogRecord(
            "n", logging.INFO, "p", 1, "signature=abcdef012345 done", None, None
        )
        RedactingFilter().filter(rec)
        self.assertIn("signature=***", rec.getMessage())
        self.assertNotIn("abcdef012345", rec.getMessage())


if __name__ == "__main__":
    unittest.main()
