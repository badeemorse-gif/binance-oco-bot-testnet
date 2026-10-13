"""اختبارات توصيل Failure Matrix (T7 / M4c) — WIRING فقط.

تتحقّق أن كل سطح أخطاء للمستخدم (preflight + أوامر CLI) يمرّ عبر
``failure_matrix.humanize()`` فلا يظهر للمستخدم أبدًا نصّ استثناء خام أو
stack trace، وأن الأكواد الحرجة (-1021/-1022/429/418) والحالة الداخلية
FAILED_NEEDS_ATTENTION تُترجَم إلى رسائل عربية بشرية. لا تُعيد كتابة الموديول
core/failure_matrix.py — التوصيل فقط. تُعيد استخدام fakes الموجودة بلا شبكة.
"""
import io
import unittest
from contextlib import redirect_stdout

from ocobot.config import AppConfig
from ocobot.core.connection_state import ConnectionStatus
from ocobot.core.errors import BinanceApiError, TransportError
from ocobot.core.failure_matrix import (
    MSG_1021,
    MSG_1022,
    MSG_418,
    MSG_429,
    MSG_FALLBACK,
    MSG_TRANSPORT,
)
from ocobot.core.keys import ApiCredentials
from ocobot.core.preflight import _interpret, run_preflight
from ocobot.core.rest_client import Response


def _has_arabic(text: str) -> bool:
    return any("\u0600" <= ch <= "\u06ff" for ch in text)


class FakeTransport:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def send(self, method, url, headers, body):
        self.calls.append(url)
        return self._responses.pop(0)


class RaisingTransport:
    """يرمي استثناءً خامًا غير مصنّف لمحاكاة تسرّب محتمل للـ stack."""

    def __init__(self, exc):
        self._exc = exc

    def send(self, method, url, headers, body):
        raise self._exc


def _resp(obj, status=200):
    import json

    return Response(status=status, headers={}, body=json.dumps(obj))


class TestPreflightHumanizeWiring(unittest.TestCase):
    def setUp(self):
        self.cfg = AppConfig(keys_path="x")
        self.creds = ApiCredentials(api_key="KEY12345678", api_secret="SECRETVALUE")

    def _run(self, transport):
        return run_preflight(
            self.cfg, transport=transport, now_ms=lambda: 1000, credentials=self.creds
        )

    def test_bad_signature_message_is_humanized(self):
        st = self._run(
            FakeTransport(
                [_resp({"serverTime": 5000}), _resp({"code": -1022, "msg": "bad"}, status=400)]
            )
        )
        self.assertEqual(st.status, ConnectionStatus.ERROR)
        self.assertEqual(st.message, MSG_1022)
        self.assertIn("-1022", st.message)

    def test_timestamp_message_is_humanized(self):
        # sync_time + get_account، و-1021 يُعاد مزامنته ويُوقّع مرّة واحدة (D18):
        # time, account(-1021), time(resync), account(-1021 مجددًا) => يرفع الخطأ
        st = self._run(
            FakeTransport(
                [
                    _resp({"serverTime": 5000}),
                    _resp({"code": -1021, "msg": "x"}, status=400),
                    _resp({"serverTime": 5000}),
                    _resp({"code": -1021, "msg": "x"}, status=400),
                ]
            )
        )
        self.assertEqual(st.status, ConnectionStatus.ERROR)
        # الرسالة النهائية بشرية عربية موحّدة (مرّت عبر humanize)
        self.assertEqual(st.message, MSG_1021)

    def test_raw_exception_never_leaks_to_message(self):
        raw = "SUPERSECRETSTACKTOKEN boom at line 42"
        st = self._run(RaisingTransport(RuntimeError(raw)))
        self.assertEqual(st.status, ConnectionStatus.ERROR)
        self.assertNotIn(raw, st.message)
        self.assertNotIn("SUPERSECRETSTACKTOKEN", st.message)
        self.assertNotIn("Traceback", st.message)
        self.assertTrue(_has_arabic(st.message))

    def test_transport_error_is_humanized(self):
        st = self._run(RaisingTransport(TransportError("connection reset by peer")))
        self.assertEqual(st.status, ConnectionStatus.ERROR)
        self.assertEqual(st.message, MSG_TRANSPORT)
        self.assertNotIn("connection reset by peer", st.message)

    def test_interpret_routes_through_humanize(self):
        # -1021/-1022/429/418 كلها تمرّ عبر humanize الموحّدة
        self.assertEqual(_interpret(BinanceApiError(-1022, "sig")), MSG_1022)
        self.assertEqual(_interpret(BinanceApiError(-1021, "ts")), MSG_1021)
        self.assertEqual(_interpret(BinanceApiError(None, "rate", http_status=429)), MSG_429)
        self.assertEqual(_interpret(BinanceApiError(None, "ban", http_status=418)), MSG_418)

    def test_interpret_unknown_binance_is_safe_fallback(self):
        msg = _interpret(BinanceApiError(-9999, "Traceback secret detail", http_status=500))
        self.assertEqual(msg, MSG_FALLBACK)
        self.assertNotIn("Traceback", msg)
        self.assertNotIn("secret", msg)

    def test_interpret_keeps_specific_key_permission_message(self):
        # -2014/-2015 تبقى رسالة مفتاح API محدّدة (بشرية) وليست fallback
        msg = _interpret(BinanceApiError(-2014, "bad key"))
        self.assertTrue(_has_arabic(msg))
        self.assertIn("-2014", msg)
        self.assertNotIn("bad key", msg)


class TestCliHumanizeWiring(unittest.TestCase):
    """كل مسار CLI يطبع رسالة humanize بدل نصّ الاستثناء الخام."""

    def _capture(self, fn):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = fn()
        return code, buf.getvalue()

    def test_orders_binance_error_humanized(self):
        from ocobot import cli

        cfg = AppConfig(keys_path="x")

        def _raise_client(_cfg):
            raise BinanceApiError(-1022, "Signature not valid: SECRETSTACK")

        orig = cli._client_with_keys
        cli._client_with_keys = _raise_client
        try:
            code, out = self._capture(lambda: cli._cmd_orders(cfg))
        finally:
            cli._client_with_keys = orig

        self.assertEqual(code, 1)
        self.assertIn(MSG_1022, out)
        self.assertNotIn("SECRETSTACK", out)
        self.assertNotIn("Traceback", out)

    def test_orders_unexpected_error_humanized(self):
        from ocobot import cli

        cfg = AppConfig(keys_path="x")

        def _raise_client(_cfg):
            raise RuntimeError("KABOOM-INTERNAL-DETAIL")

        orig = cli._client_with_keys
        cli._client_with_keys = _raise_client
        try:
            code, out = self._capture(lambda: cli._cmd_orders(cfg))
        finally:
            cli._client_with_keys = orig

        self.assertEqual(code, 1)
        self.assertIn(MSG_FALLBACK, out)
        self.assertNotIn("KABOOM-INTERNAL-DETAIL", out)
        self.assertNotIn("Traceback", out)


if __name__ == "__main__":
    unittest.main()
