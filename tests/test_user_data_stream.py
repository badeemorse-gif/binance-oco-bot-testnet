"""اختبارات دورة حياة listenKey (M4e/1 · T9a) — بلا شبكة.

يغطّي: create (POST) يُرجع listenKey، keepalive (PUT)، close (DELETE)،
التجديد التلقائي عبر ساعة محقونة (يُطلَق قبل ~30م)، وتأكيد المصادقة بمفتاح فقط
(X-MBX-APIKEY فقط، بلا signature/timestamp) على مستوى النقل.
"""
import json
import unittest

from ocobot.config import AppConfig
from ocobot.core.errors import BinanceApiError
from ocobot.core.keys import ApiCredentials
from ocobot.core.rest_client import Response, SignedRestClient
from ocobot.core.user_data_stream import (
    KEEPALIVE_INTERVAL_MS,
    PATH_USER_DATA_STREAM,
    ListenKeyError,
    ListenKeyManager,
)

LISTEN_KEY = "pqia91ma19a5s61cv6a81va65sdf19v8a65a1a5f19v8a65a1"


class FakeTransport:
    """نقل بلا شبكة: يسجّل كل نداء ويعيد ردودًا معلّبة بالترتيب."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def send(self, method, url, headers, body):
        self.calls.append(
            {"method": method, "url": url, "headers": dict(headers or {}), "body": body}
        )
        return self._responses.pop(0)


def _resp(obj, status=200, headers=None):
    return Response(status=status, headers=headers or {}, body=json.dumps(obj))


class FakeKeyedClient:
    """عميل خفيف يلتقط نداءات keyed_request (method, path, params) بلا نقل حقيقي."""

    def __init__(self, listen_key=LISTEN_KEY):
        self.listen_key = listen_key
        self.keyed_calls = []

    def keyed_request(self, method, path, params=None):
        self.keyed_calls.append((method, path, dict(params or [])))
        if method == "POST" and path == PATH_USER_DATA_STREAM:
            return {"listenKey": self.listen_key}
        # keepalive/close يعيدان جسمًا فارغًا كما في Binance
        return {}


class _FakeClock:
    """ساعة محقونة قابلة للتقديم يدويًا (نمط ServerClock — بلا time/sleep)."""

    def __init__(self, start_ms=0):
        self.value = int(start_ms)

    def __call__(self):
        return self.value

    def advance(self, ms):
        self.value += int(ms)


class TestListenKeyLifecycle(unittest.TestCase):
    def _mgr(self, clock=None):
        client = FakeKeyedClient()
        clk = clock or _FakeClock(0)
        return ListenKeyManager(client, now_ms=clk), client, clk

    def test_create_returns_and_stores_listen_key(self):
        mgr, client, _ = self._mgr()
        key = mgr.create()
        self.assertEqual(key, LISTEN_KEY)
        self.assertEqual(mgr.listen_key, LISTEN_KEY)
        self.assertTrue(mgr.active)
        method, path, params = client.keyed_calls[0]
        self.assertEqual(method, "POST")
        self.assertEqual(path, PATH_USER_DATA_STREAM)
        self.assertEqual(params, {})  # POST لا يحمل listenKey

    def test_keepalive_sends_put_with_listen_key(self):
        mgr, client, _ = self._mgr()
        mgr.create()
        mgr.keepalive()
        method, path, params = client.keyed_calls[-1]
        self.assertEqual(method, "PUT")
        self.assertEqual(path, PATH_USER_DATA_STREAM)
        self.assertEqual(params["listenKey"], LISTEN_KEY)

    def test_keepalive_without_create_raises(self):
        mgr, _, _ = self._mgr()
        with self.assertRaises(ListenKeyError):
            mgr.keepalive()

    def test_close_sends_delete_and_clears(self):
        mgr, client, _ = self._mgr()
        mgr.create()
        mgr.close()
        method, path, params = client.keyed_calls[-1]
        self.assertEqual(method, "DELETE")
        self.assertEqual(path, PATH_USER_DATA_STREAM)
        self.assertEqual(params["listenKey"], LISTEN_KEY)
        self.assertFalse(mgr.active)
        self.assertIsNone(mgr.listen_key)

    def test_close_without_key_is_noop(self):
        mgr, client, _ = self._mgr()
        mgr.close()  # لا يرفع ولا يرسل
        self.assertEqual(client.keyed_calls, [])

    # ---- auto-renew via injected clock ----
    def test_keepalive_not_due_before_interval(self):
        clk = _FakeClock(0)
        mgr, client, _ = self._mgr(clock=clk)
        mgr.create()
        # قبل ~30م (باستخدام العتبة 25م) لا شيء
        clk.advance(KEEPALIVE_INTERVAL_MS - 1)
        self.assertFalse(mgr.maybe_keepalive())
        self.assertEqual(len(client.keyed_calls), 1)  # POST فقط

    def test_keepalive_fires_automatically_before_30m(self):
        clk = _FakeClock(0)
        mgr, client, _ = self._mgr(clock=clk)
        mgr.create()
        # العتبة 25م < 30م: التجديد يُطلَق تلقائيًا قبل علامة ~30م
        self.assertLess(KEEPALIVE_INTERVAL_MS, 30 * 60 * 1000)
        clk.advance(KEEPALIVE_INTERVAL_MS)
        self.assertTrue(mgr.maybe_keepalive())
        method, path, params = client.keyed_calls[-1]
        self.assertEqual((method, path), ("PUT", PATH_USER_DATA_STREAM))
        self.assertEqual(params["listenKey"], LISTEN_KEY)
        # بعد التجديد يُعاد ضبط المؤقّت (لا تجديد فوري ثانٍ)
        self.assertFalse(mgr.maybe_keepalive())

    def test_ensure_active_alias(self):
        clk = _FakeClock(0)
        mgr, client, _ = self._mgr(clock=clk)
        mgr.create()
        clk.advance(KEEPALIVE_INTERVAL_MS)
        self.assertTrue(mgr.ensure_active())

    def test_due_false_without_active_key(self):
        clk = _FakeClock(0)
        mgr, _, _ = self._mgr(clock=clk)
        clk.advance(KEEPALIVE_INTERVAL_MS * 10)
        self.assertFalse(mgr.due_for_keepalive())


class TestKeyOnlyAuth(unittest.TestCase):
    """تأكيد المصادقة بمفتاح فقط على مستوى النقل الحقيقي (keyed_request)."""

    def _client(self, responses):
        cfg = AppConfig(keys_path="x", recv_window=5000)
        creds = ApiCredentials(api_key="KEY", api_secret="SECRET")
        transport = FakeTransport(responses)
        client = SignedRestClient(cfg, creds, transport=transport, now_ms=lambda: 1000)
        return client, transport

    def test_create_is_key_only_no_signature_no_timestamp(self):
        client, transport = self._client([_resp({"listenKey": LISTEN_KEY})])
        mgr = ListenKeyManager(client, now_ms=lambda: 0)
        key = mgr.create()
        self.assertEqual(key, LISTEN_KEY)

        call = transport.calls[0]
        self.assertEqual(call["method"], "POST")
        self.assertIn(PATH_USER_DATA_STREAM, call["url"])
        # المفتاح فقط في الرأس
        self.assertEqual(call["headers"]["X-MBX-APIKEY"], "KEY")
        # لا توقيع ولا timestamp ولا سرّ
        self.assertNotIn("signature", call["url"])
        self.assertNotIn("timestamp", call["url"])
        self.assertNotIn("SECRET", call["url"])
        # لا مزامنة ساعة (unsigned لا يحتاج serverTime)
        self.assertEqual(len(transport.calls), 1)

    def test_keepalive_put_carries_listenkey_only(self):
        client, transport = self._client(
            [_resp({"listenKey": LISTEN_KEY}), _resp({})]
        )
        mgr = ListenKeyManager(client, now_ms=lambda: 0)
        mgr.create()
        mgr.keepalive()
        call = transport.calls[-1]
        self.assertEqual(call["method"], "PUT")
        self.assertIn(f"listenKey={LISTEN_KEY}", call["url"])
        self.assertNotIn("signature", call["url"])
        self.assertNotIn("timestamp", call["url"])
        self.assertEqual(call["headers"]["X-MBX-APIKEY"], "KEY")

    def test_close_delete_key_only(self):
        client, transport = self._client(
            [_resp({"listenKey": LISTEN_KEY}), _resp({})]
        )
        mgr = ListenKeyManager(client, now_ms=lambda: 0)
        mgr.create()
        mgr.close()
        call = transport.calls[-1]
        self.assertEqual(call["method"], "DELETE")
        self.assertNotIn("signature", call["url"])
        self.assertEqual(call["headers"]["X-MBX-APIKEY"], "KEY")

    def test_binance_error_propagates(self):
        client, _ = self._client([_resp({"code": -1125, "msg": "bad"}, status=400)])
        mgr = ListenKeyManager(client, now_ms=lambda: 0)
        with self.assertRaises(BinanceApiError):
            mgr.create()

    def test_no_key_or_listenkey_leak_in_logs(self):
        client, _ = self._client(
            [_resp({"listenKey": LISTEN_KEY}), _resp({}), _resp({})]
        )
        mgr = ListenKeyManager(client, now_ms=lambda: 0)
        import logging
        logging.getLogger("ocobot.userdata").setLevel(logging.INFO)
        with self.assertLogs("ocobot.userdata", level="INFO") as cm:
            mgr.create()
            mgr.keepalive()
            mgr.close()
        blob = "\n".join(cm.output)
        self.assertNotIn(LISTEN_KEY, blob)


if __name__ == "__main__":
    unittest.main()
