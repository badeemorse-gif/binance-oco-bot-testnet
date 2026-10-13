"""اختبارات G1.25 (step_7_verify_offline) — قناة تنبيهات Telegram بلا شبكة.

تحقّق offline بالكامل عبر نقل مُحاكى (fake transport) يُحقَن في
``TelegramClient(transport=...)`` أو عبر ``client_provider`` للـ``Notifier`` —
صفر نداء شبكي حقيقي. كل اختبار يغطّي بندًا متمايزًا من تعريف الإنجاز
(DoD / step_7) لـ G1.25. الطابور يُستنزَف بإيقاف الـworker حتميًا
(``start()``/``stop()``) بلا نوم عشوائي طويل.

خريطة البند ⇒ الاختبار (10 بنود، مع دمجين موثّقين):
  (1) تهريب MarkdownV2            -> test_markdownv2_escaping
  (2) القوالب monitor_start/
      repositioned + 🟢/🔴/🟡     -> test_templates_monitor_start_and_repositioned
  (3) enqueue غير حاجب            -> test_enqueue_non_blocking_returns_immediately
  (4) سلوك الطابور (معالجة/إسقاط
      عند الامتلاء/التعطيل)        -> test_queue_processes_and_drops_when_full_or_disabled
  (5) مهلة+إعادة محاولة (مدموجان) -> test_timeout_and_retry_merged_then_counts_failed
  (6) ابتلاع الاستثناءات          -> test_exceptions_never_raise_into_caller
  (7) إدارة البوت/المستلمين       -> test_bot_and_recipient_management
  (8) التحقّق من المدخلات         -> test_input_validation_rejects_bad_chat_id_and_token
  (9) حفظ/إعادة التحميل           -> test_persistence_round_trip_settings_and_token
  (10) جسر القراءة فقط poll_once  -> test_bridge_poll_once_only_alert_events_and_swallows

ملاحظات الدمج (موثّقة):
  * الدمج أ (بند 5): المهلة وإعادة المحاولة ليستا آليتين منفصلتين في الكود —
    المهلة = معامل ``TelegramClient(timeout=...)`` بينما إعادة المحاولة =
    ``Notifier(retries=, retry_delay=)``. لذا يُغطَّيان في اختبار واحد مدموج
    يثبت أن النقل يُستدعى (1 + retries) مرّة لكل مستلِم ثم يُحتسب ``_failed``.
  * الدمج ب (بند 3+4 جزئيًا): «عدم الحجب» يُثبَت بأن ``enqueue`` يعود فورًا دون
    انتظار أي شبكة (لا worker يعمل)؛ وسلوك الطابور يُغطَّى في اختباره المستقل.
"""
import os
import time
import unittest

from ocobot.alerts.telegram_client import TelegramClient, TelegramError
from ocobot.alerts.notifier import Notifier
from ocobot.alerts.formatting import (
    escape_mdv2,
    build_monitor_start_message,
    build_reposition_message,
    format_event,
)
from ocobot.alerts.bridge import AlertsAuditBridge
from ocobot.alerts.storage import AlertsStore


# ---------------------------------------------------------------------------
# مساعدات نقل مُحاكى (بلا شبكة إطلاقًا)
# ---------------------------------------------------------------------------
class _OkTransport:
    """نقل يُعيد ردًّا ناجحًا ``{ok:true}`` ويُحصي نداءاته."""

    def __init__(self):
        self.calls = []

    def __call__(self, method_url, params, timeout):
        self.calls.append({"url": method_url, "params": dict(params), "timeout": timeout})
        return {"ok": True, "result": {"message_id": len(self.calls)}}


class _ApiErrorTransport:
    """نقل يُعيد مغلّفًا ``{ok:false}`` (خطأ API) — يرفع TelegramError داخل _call."""

    def __init__(self, description="bad", error_code=400):
        self.calls = []
        self._description = description
        self._error_code = error_code

    def __call__(self, method_url, params, timeout):
        self.calls.append({"url": method_url, "params": dict(params)})
        return {"ok": False, "description": self._description, "error_code": self._error_code}


class _RaisingTransport:
    """نقل يرفع استثناء شبكة (يُحاكي timeout/انقطاع) — يجب أن يُبتلَع في الـNotifier."""

    def __init__(self, exc=None):
        self.calls = []
        self._exc = exc if exc is not None else TimeoutError("simulated network timeout")

    def __call__(self, method_url, params, timeout):
        self.calls.append({"url": method_url, "params": dict(params)})
        raise self._exc


def _drain(notifier, timeout=2.0):
    """يُشغّل الـworker حتى يُفرَّغ الطابور ثم يوقفه حتميًا (بلا نوم طويل عشوائي)."""
    notifier.start()
    deadline = time.time() + timeout
    while time.time() < deadline:
        if notifier.stats()["queued"] == 0:
            break
        time.sleep(0.01)
    notifier.stop(timeout=timeout)


class _Rec:
    """كائن MonitoringState-شبيه بسيط لتغذية القوالب (سمات فقط)."""

    def __init__(self, **kw):
        self.__dict__.update(kw)


# ===========================================================================
# (1) تهريب MarkdownV2
# ===========================================================================
class TestG125MarkdownV2Escaping(unittest.TestCase):
    def test_markdownv2_escaping(self):
        specials = "_*[]()~`>#+-=|{}.!"
        out = escape_mdv2(specials)
        for ch in specials:
            self.assertIn("\\" + ch, out)
        self.assertEqual(len(out), 2 * len(specials))
        self.assertEqual(escape_mdv2("abc"), "abc")
        self.assertEqual(escape_mdv2("🟢"), "🟢")
        self.assertEqual(escape_mdv2(12.5), "12\\.5")


# ===========================================================================
# (2) القوالب monitor_start / repositioned + الإيموجي 🟢/🔴/🟡
# ===========================================================================
class TestG125Templates(unittest.TestCase):
    def test_templates_monitor_start_and_repositioned(self):
        start_record = {
            "event": "monitor_start",
            "ts": "2026-01-01T00:00:00Z",
            "details": {
                "trade_uid": "ab12cd34",
                "session_no": 1,
                "symbol": "BTCUSDT",
                "order_list_id": 999,
                "reference_price": "100",
                "trigger_pct": "1",
                "tp_pct": "2",
                "sl_pct": "1",
            },
        }
        msg = build_monitor_start_message(start_record)
        self.assertIn("🚀 *Monitor Started*", msg)
        self.assertIn("🟡", msg)
        self.assertIn("🟢", msg)
        self.assertIn("🔴", msg)
        self.assertIn("BTCUSDT", msg)

        state = _Rec(
            trade_uid="ab12cd34",
            session_no=2,
            symbol="BTCUSDT",
            reference_price="100",
            trigger_pct="1",
            tp_pct="2",
            sl_pct="1",
            last_price="101",
        )
        repo_record = {
            "event": "repositioned",
            "ts": "2026-01-01T00:05:00Z",
            "details": {"new_target": 1000, "old_target": 999, "price": "101", "cursor": "C3"},
        }
        rmsg = build_reposition_message(repo_record, state, prev_price="100")
        self.assertIn("🔁 *Repositioned*", rmsg)
        self.assertIn("🟡", rmsg)
        self.assertIn("🟢", rmsg)
        self.assertIn("🔴", rmsg)

        self.assertEqual(format_event(start_record), msg)
        self.assertIsNone(format_event({"event": "something_else"}))


# ===========================================================================
# (3) enqueue غير حاجب (المسار الساخن لا ينتظر الشبكة)
# ===========================================================================
class TestG125NonBlocking(unittest.TestCase):
    def test_enqueue_non_blocking_returns_immediately(self):
        transport = _RaisingTransport()
        client = TelegramClient("TESTTOKEN", timeout=10.0, transport=transport)
        notifier = Notifier(
            client_provider=lambda: client,
            recipients_provider=lambda: ["123"],
        )
        start = time.perf_counter()
        ok = notifier.enqueue("hello")
        elapsed = time.perf_counter() - start
        self.assertTrue(ok)
        self.assertLess(elapsed, 0.5)
        self.assertEqual(transport.calls, [])
        self.assertEqual(notifier.stats()["queued"], 1)


# ===========================================================================
# (4) سلوك الطابور: معالجة المُدرَج + إسقاط وعدّ عند الامتلاء/التعطيل
# ===========================================================================
class TestG125QueueBehavior(unittest.TestCase):
    def test_queue_processes_and_drops_when_full_or_disabled(self):
        transport = _OkTransport()
        client = TelegramClient("TESTTOKEN", transport=transport)

        n1 = Notifier(
            client_provider=lambda: client,
            recipients_provider=lambda: ["1", "2"],
        )
        for i in range(3):
            self.assertTrue(n1.enqueue("m%d" % i))
        _drain(n1)
        self.assertEqual(n1.stats()["sent"], 6)
        self.assertEqual(n1.stats()["failed"], 0)
        self.assertEqual(len(transport.calls), 6)

        n2 = Notifier(
            client_provider=lambda: client,
            recipients_provider=lambda: ["1"],
            max_queue=1,
        )
        self.assertTrue(n2.enqueue("first"))
        self.assertFalse(n2.enqueue("second"))
        self.assertEqual(n2.stats()["dropped"], 1)

        n3 = Notifier(
            client_provider=lambda: client,
            recipients_provider=lambda: ["1"],
            enabled_provider=lambda: False,
        )
        self.assertFalse(n3.enqueue("blocked"))
        self.assertEqual(n3.stats()["queued"], 0)


# ===========================================================================
# (5) مهلة + إعادة المحاولة (مدموجان — انظر ملاحظة الدمج أ)
# ===========================================================================
class TestG125TimeoutRetryMerged(unittest.TestCase):
    def test_timeout_and_retry_merged_then_counts_failed(self):
        transport = _RaisingTransport()
        client = TelegramClient("TESTTOKEN", timeout=0.01, transport=transport)
        notifier = Notifier(
            client_provider=lambda: client,
            recipients_provider=lambda: ["555"],
            retries=2,
            retry_delay=0.0,
        )
        self.assertTrue(notifier.enqueue("will-fail"))
        _drain(notifier)
        self.assertEqual(len(transport.calls), 3)
        self.assertEqual(notifier.stats()["failed"], 1)
        self.assertEqual(notifier.stats()["sent"], 0)


# ===========================================================================
# (6) ابتلاع الاستثناءات — لا شيء يرفع إلى المستدعي
# ===========================================================================
class TestG125ExceptionSwallow(unittest.TestCase):
    def test_exceptions_never_raise_into_caller(self):
        raising = _RaisingTransport(RuntimeError("boom"))
        client = TelegramClient("TESTTOKEN", transport=raising)
        notifier = Notifier(
            client_provider=lambda: client,
            recipients_provider=lambda: ["1"],
            retries=0,
            retry_delay=0.0,
        )
        self.assertTrue(notifier.enqueue("x"))
        try:
            _drain(notifier)
        except Exception as exc:  # pragma: no cover
            self.fail("notifier worker raised into caller: %r" % exc)
        self.assertEqual(notifier.stats()["failed"], 1)

        bad = Notifier(
            client_provider=lambda: client,
            recipients_provider=lambda: (_ for _ in ()).throw(ValueError("nope")),
        )
        self.assertTrue(bad.enqueue("y"))
        _drain(bad)
        self.assertEqual(bad.stats()["sent"], 0)

        api_err = _ApiErrorTransport()
        c2 = TelegramClient("TESTTOKEN", transport=api_err)
        with self.assertRaises(TelegramError):
            c2.send_message("1", "hi")


# ===========================================================================
# (7) إدارة البوت/المستلمين عبر AlertsStore
# ===========================================================================
class TestG125Management(unittest.TestCase):
    def setUp(self):
        import tempfile

        self._dir = tempfile.mkdtemp()
        self._alerts = os.path.join(self._dir, "ocobot_alerts.json")
        self._token = os.path.join(self._dir, ".tok")
        self._saved_env = os.environ.pop("OCOBOT_TELEGRAM_TOKEN", None)

    def tearDown(self):
        if self._saved_env is not None:
            os.environ["OCOBOT_TELEGRAM_TOKEN"] = self._saved_env

    def test_bot_and_recipient_management(self):
        store = AlertsStore(path=self._alerts, token_path=self._token)

        store.set_bot(username="my_bot", label="main")
        s = store.load()
        self.assertIsNotNone(s.bot)
        self.assertEqual(s.bot.username, "my_bot")
        self.assertTrue(s.bot.present)

        store.add_recipient("100", "alice")
        store.add_recipient("200", "bob")
        store.add_recipient("100", "alice2")
        listed = store.load().recipients
        self.assertEqual([r.chat_id for r in listed], ["100", "200"])
        self.assertEqual(listed[0].label, "alice2")

        self.assertEqual(store.recipients_provider(), ["100", "200"])

        store.remove_recipients(["100"])
        self.assertEqual(store.recipients_provider(), ["200"])
        store.remove_recipients(["999"])
        self.assertEqual(store.recipients_provider(), ["200"])

        store.clear_bot()
        self.assertIsNone(store.load().bot)


# ===========================================================================
# (8) التحقّق من المدخلات: chat_id/token غير صالح يُرفَض
# ===========================================================================
class TestG125InputValidation(unittest.TestCase):
    def setUp(self):
        import tempfile

        self._dir = tempfile.mkdtemp()
        self._alerts = os.path.join(self._dir, "ocobot_alerts.json")
        self._token = os.path.join(self._dir, ".tok")
        self._saved_env = os.environ.pop("OCOBOT_TELEGRAM_TOKEN", None)

    def tearDown(self):
        if self._saved_env is not None:
            os.environ["OCOBOT_TELEGRAM_TOKEN"] = self._saved_env

    def test_input_validation_rejects_bad_chat_id_and_token(self):
        store = AlertsStore(path=self._alerts, token_path=self._token)

        store.add_recipient("", "x")
        store.add_recipient("   ", "y")
        self.assertEqual(store.recipients_provider(), [])

        store.add_recipient("  321  ", "z")
        self.assertEqual(store.recipients_provider(), ["321"])

        api_err = _ApiErrorTransport(description="Unauthorized", error_code=401)
        client = TelegramClient("BAD-TOKEN", transport=api_err)
        with self.assertRaises(TelegramError):
            client.get_me()


# ===========================================================================
# (9) حفظ/إعادة التحميل: الإعدادات + التوكِن السرّي (ملفات tmp عبر البيئة)
# ===========================================================================
class TestG125Persistence(unittest.TestCase):
    def setUp(self):
        import tempfile

        self._dir = tempfile.mkdtemp()
        self._alerts = os.path.join(self._dir, "ocobot_alerts.json")
        self._token = os.path.join(self._dir, ".ocobot_telegram_token")
        self._saved = {
            "OCOBOT_ALERTS_FILE": os.environ.get("OCOBOT_ALERTS_FILE"),
            "OCOBOT_TELEGRAM_TOKEN": os.environ.get("OCOBOT_TELEGRAM_TOKEN"),
            "OCOBOT_TELEGRAM_TOKEN_FILE": os.environ.get("OCOBOT_TELEGRAM_TOKEN_FILE"),
        }
        os.environ["OCOBOT_ALERTS_FILE"] = self._alerts
        os.environ["OCOBOT_TELEGRAM_TOKEN_FILE"] = self._token
        os.environ.pop("OCOBOT_TELEGRAM_TOKEN", None)

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_persistence_round_trip_settings_and_token(self):
        writer = AlertsStore()
        writer.set_enabled(True)
        writer.set_bot(username="persist_bot", label="L")
        writer.add_recipient("777", "charlie")
        writer.set_token("SECRET-TELEGRAM-TOKEN")

        reader = AlertsStore()
        s = reader.load()
        self.assertTrue(s.enabled)
        self.assertIsNotNone(s.bot)
        self.assertEqual(s.bot.username, "persist_bot")
        self.assertEqual([r.chat_id for r in s.recipients], ["777"])
        self.assertEqual(reader.get_token(), "SECRET-TELEGRAM-TOKEN")

        self.assertTrue(reader.enabled_provider())
        self.assertNotIn("SECRET-TELEGRAM-TOKEN", repr(reader))

        with open(self._alerts, "r", encoding="utf-8") as f:
            settings_raw = f.read()
        self.assertNotIn("SECRET-TELEGRAM-TOKEN", settings_raw)


# ===========================================================================
# (10) الجسر للقراءة فقط: poll_once يُدرِج فقط أحداث التنبيه ويبتلع الأخطاء
# ===========================================================================
class _CapturingNotifier:
    """بديل Notifier يلتقط نصوص enqueue فقط (لا شبكة، لا طابور)."""

    def __init__(self):
        self.texts = []

    def enqueue(self, text, **kw):
        self.texts.append(text)
        return True


class _EnabledStore:
    def enabled_provider(self):
        return True


class TestG125Bridge(unittest.TestCase):
    def setUp(self):
        import tempfile

        self._dir = tempfile.mkdtemp()
        self._audit = os.path.join(self._dir, "audit.jsonl")

    def _write(self, lines):
        with open(self._audit, "w", encoding="utf-8") as f:
            for ln in lines:
                f.write(ln + "\n")

    def test_bridge_poll_once_only_alert_events_and_swallows(self):
        import json

        self._write([
            "{ this is not valid json",
            json.dumps({"event": "connected", "details": {}}),
            json.dumps({
                "event": "monitor_start",
                "ts": "t1",
                "details": {"trade_uid": "u1", "session_no": 1, "symbol": "ETHUSDT",
                            "reference_price": "10", "tp_pct": "1", "sl_pct": "1",
                            "trigger_pct": "1"},
            }),
            json.dumps({"event": "repositioned", "ts": "t2",
                        "details": {"price": "11", "new_target": 2}}),
        ])

        notifier = _CapturingNotifier()
        bridge = AlertsAuditBridge(
            notifier=notifier,
            store=_EnabledStore(),
            audit_path=self._audit,
            start_at_end=False,
        )
        enqueued = bridge.poll_once()
        self.assertEqual(enqueued, 2)
        self.assertEqual(len(notifier.texts), 2)
        self.assertIn("🚀 *Monitor Started*", notifier.texts[0])
        self.assertIn("🔁 *Repositioned*", notifier.texts[1])

        self.assertEqual(bridge.poll_once(), 0)
        self.assertEqual(len(notifier.texts), 2)

        missing = AlertsAuditBridge(
            notifier=notifier,
            store=_EnabledStore(),
            audit_path=os.path.join(self._dir, "nope.jsonl"),
            start_at_end=False,
        )
        self.assertEqual(missing.poll_once(), 0)


if __name__ == "__main__":
    unittest.main()
