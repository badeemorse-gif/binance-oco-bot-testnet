"""اختبارات الـ Audit Log الملحِق (T5 / M4).

يتحقّق أن إلحاق عدّة إدخالات في ملف مؤقّت (tmp_path) يُنتج عدّة أسطر JSONL
وأن الأسطر السابقة تبقى محفوظة (append-only)، وأن أيّ سر/مفتاح API يُوضَع في
إدخال لا يظهر في الملف المكتوب (مُخفّى — D8).
"""
import json
import unittest

from ocobot.core.audit_log import AuditLog


class TestAuditLog(unittest.TestCase):
    def _read_lines(self, path):
        with open(path, "r", encoding="utf-8") as handle:
            return [ln for ln in handle.read().splitlines() if ln.strip()]

    def _tmp_path(self):
        import os
        import tempfile

        d = tempfile.mkdtemp()
        return os.path.join(d, "sub", "audit.jsonl")

    def test_appends_multiple_jsonl_lines(self):
        path = self._tmp_path()
        log = AuditLog(path)
        log.record("connected", {"env": "TESTNET"})
        log.record("reposition_start", {"symbol": "BTCUSDT"})
        log.record("reposition_done", {"state": "SUCCESS"})

        lines = self._read_lines(path)
        self.assertEqual(len(lines), 3)
        for line in lines:
            obj = json.loads(line)  # كل سطر JSON صالح مستقل
            self.assertIn("ts", obj)
            self.assertIn("event", obj)
            self.assertIn("details", obj)

    def test_append_only_preserves_prior_lines(self):
        path = self._tmp_path()
        log = AuditLog(path)
        log.record("first", {"n": 1})
        first_snapshot = self._read_lines(path)
        self.assertEqual(len(first_snapshot), 1)

        # مُسجّل جديد على نفس الملف يجب أن يُلحق لا أن يُقتطع.
        log2 = AuditLog(path)
        log2.record("second", {"n": 2})
        lines = self._read_lines(path)
        self.assertEqual(len(lines), 2)
        # السطر الأول لم يتغيّر (append-only).
        self.assertEqual(lines[0], first_snapshot[0])
        self.assertEqual(json.loads(lines[0])["event"], "first")
        self.assertEqual(json.loads(lines[1])["event"], "second")

    def test_secret_apikey_is_redacted_in_file(self):
        path = self._tmp_path()
        log = AuditLog(path)
        secret = "RAWAPIKEY0123456789"
        sig = "deadBEEF0123456789abcdef"
        log.record(
            "signed_request",
            {
                "headers": {"X-MBX-APIKEY": secret},
                "url": "https://x/api/v3/account?timestamp=1&signature=" + sig,
            },
        )
        with open(path, "r", encoding="utf-8") as f:
            raw_file = f.read()
        self.assertNotIn(secret, raw_file)
        self.assertNotIn(sig, raw_file)
        self.assertIn("***", raw_file)


if __name__ == "__main__":
    unittest.main()
