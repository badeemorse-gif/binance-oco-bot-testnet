import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest
from unittest import mock

from ocobot.ui._qt import QApplication
from ocobot.ui.theme import apply_theme
from ocobot.ui.open_orders import OpenOrdersScreen
from ocobot.ui.app import make_connect_wrapper
from ocobot.core.connection_state import ConnectionStatus
from tests._fakes import FakeResult, FakeContent, FakeWindow, FakeCfg


class _SyncRunner:
    """Runner منفّذ متزامنًا (كما في اختبارات الواجهة الأخرى) — بلا خيوط/شبكة."""

    def submit(self, fn, *a, on_result=None, on_error=None, **k):
        try:
            r = fn(*a, **k)
        except Exception as exc:  # pragma: no cover - دفاعي
            if on_error:
                on_error(exc)
            return None
        if on_result:
            on_result(r)
        return r


class _FakeWindowWithRunner(FakeWindow):
    """FakeWindow + runner: make_connect_wrapper يحتاج window.runner لـ set_source."""

    def __init__(self, connection_notifier, content, runner):
        super().__init__(connection_notifier, content)
        self.runner = runner


class _Notifier:
    def __init__(self):
        self.state = None

    def set_state(self, state):
        self.state = state


def _fake_open_sell_orders():
    """صفوف بيع وهمية (list[dict]) — set_orders يستهلك dicts عبر .get()."""
    return [
        {
            "orderListId": 31,
            "symbol": "BTCUSDT",
            "status": "EXECUTING",
            "qty": "0.5",
            "saleTp": "70000.00",
            "stopTrigger": "58500.00",
            "limitAfterTrigger": "58000.00",
        },
        {
            "orderListId": 42,
            "symbol": "ETHUSDT",
            "status": "NEW",
            "qty": "1.0",
            "saleTp": "4000.00",
            "stopTrigger": "3500.00",
            "limitAfterTrigger": "3450.00",
        },
    ]


class G117OpenOrdersAfterConnectTests(unittest.TestCase):
    """G1.17: بعد اتصال ناجح، شاشة Open Orders تستقبل مصدر بيانات وتعرض صفوفًا فعليًا.

    يفشل ضد الكود القديم (الذي كان يستدعي oo.refresh() فقط دون set_source،
    فيبقى _build_fn=None ويخرج refresh مبكرًا والجدول فارغ) وينجح مع الإصلاح.
    """

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    def test_successful_connect_injects_source_and_renders_rows(self):
        screen = OpenOrdersScreen()  # شاشة حقيقية بـ _build_fn=None (كما عند الإقلاع البارد)
        self.assertEqual(screen.table.rowCount(), 0)
        self.assertIsNone(screen._build_fn)

        notifier = _Notifier()
        runner = _SyncRunner()
        window = _FakeWindowWithRunner(
            notifier, FakeContent({"02_open_orders": screen}), runner
        )
        cfg = FakeCfg()

        # لا شبكة ولا مفاتيح: نُرقّع read_all_open_sell_orders و build_gui_client
        # اللذين يستعملهما make_connect_wrapper داخل app.py.
        with mock.patch(
            "ocobot.ui.app.read_all_open_sell_orders",
            side_effect=lambda _client: _fake_open_sell_orders(),
        ), mock.patch(
            "ocobot.ui.app.build_gui_client", return_value=object()
        ):
            wrapped = make_connect_wrapper(
                window, lambda *a, **k: FakeResult(ok=True), cfg
            )
            result = wrapped(api_key="k", api_secret="s", keys_path="")

        self.assertTrue(getattr(result, "ok", False))
        self.assertIsNotNone(notifier.state)
        self.assertEqual(notifier.state.status, ConnectionStatus.CONNECTED)
        # الجوهر: الشاشة استقبلت مصدرًا قابلًا للاستعمال وعرضت صفوفًا فعلية —
        # وليس مجرد أن refresh() استُدعي.
        self.assertIsNotNone(screen._build_fn)
        self.assertGreater(screen.table.rowCount(), 0)
        self.assertEqual(screen.table.rowCount(), 2)
        self.assertEqual(screen.table.item(0, 2).text(), "BTCUSDT")

    def test_failed_connect_does_not_inject_source_or_render(self):
        screen = OpenOrdersScreen()
        notifier = _Notifier()
        window = _FakeWindowWithRunner(
            notifier, FakeContent({"02_open_orders": screen}), _SyncRunner()
        )
        cfg = FakeCfg()

        with mock.patch(
            "ocobot.ui.app.read_all_open_sell_orders",
            side_effect=lambda _client: _fake_open_sell_orders(),
        ), mock.patch(
            "ocobot.ui.app.build_gui_client", return_value=object()
        ):
            wrapped = make_connect_wrapper(
                window, lambda *a, **k: FakeResult(ok=False), cfg
            )
            result = wrapped(api_key="k", api_secret="s")

        self.assertFalse(getattr(result, "ok", True))
        self.assertIsNone(notifier.state)
        self.assertIsNone(screen._build_fn)
        self.assertEqual(screen.table.rowCount(), 0)


if __name__ == "__main__":
    unittest.main()
