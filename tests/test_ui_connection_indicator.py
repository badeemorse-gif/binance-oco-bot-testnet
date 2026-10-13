import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest

from ocobot.ui._qt import QApplication, QEventLoop, QTimer
from ocobot.ui.theme import apply_theme, PALETTE
from ocobot.ui.topbar import Topbar
from ocobot.ui.connection import ConnectionStateNotifier
from ocobot.ui.main_window import MainWindow
from ocobot.ui.app import make_connect_wrapper
from ocobot.core.connection_state import ConnectionState, ConnectionStatus
from tests._fakes import (
    FakeResult,
    FakeOpenOrdersScreen,
    FakeContent,
    FakeWindow,
    FakeCfg,
)


def _pump(loop, timeout_ms=5000):
    guard = QTimer()
    guard.setSingleShot(True)
    guard.timeout.connect(loop.quit)
    guard.start(timeout_ms)
    loop.exec()
    guard.stop()


class UIConnectionIndicatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    def test_topbar_set_connection_state_mapping(self):
        topbar = Topbar()
        cases = {
            ConnectionStatus.CONNECTED: ("متصل", PALETTE["GREEN"]),
            ConnectionStatus.CONNECTING: ("جارٍ الاتصال", PALETTE["AMBER"]),
            ConnectionStatus.ERROR: ("خطأ اتصال", PALETTE["RED"]),
            ConnectionStatus.DISCONNECTED: ("غير متصل", PALETTE["MUTED"]),
        }
        for status, (label, accent) in cases.items():
            topbar.set_connection_state(status)
            self.assertEqual(topbar.conn_pill.text(), label)
            self.assertIn(accent, topbar.conn_pill.styleSheet())

    def test_notifier_updates_connected_topbar(self):
        topbar = Topbar()
        notifier = ConnectionStateNotifier()
        notifier.changed.connect(topbar.set_connection_state)

        state = ConnectionState(status=ConnectionStatus.ERROR)
        notifier.set_state(state)

        self.assertEqual(topbar.conn_pill.text(), "خطأ اتصال")
        self.assertIn(PALETTE["RED"], topbar.conn_pill.styleSheet())
        self.assertIs(notifier.state, state)

    def test_main_window_refresh_connection_updates_topbar(self):
        window = MainWindow()
        loop = QEventLoop()
        window.connection_notifier.changed.connect(lambda _s: loop.quit())

        def fake_preflight_fn():
            # Hand-built ConnectionState, NO network.
            return ConnectionState(status=ConnectionStatus.CONNECTED)

        window.refresh_connection(fake_preflight_fn)
        # Drain any already-queued outcome first, then pump if still pending —
        # so a fast worker whose quit fired before exec() never wedges us.
        QApplication.instance().processEvents()
        if window.topbar.conn_pill.text() != "متصل":
            _pump(loop)

        self.assertEqual(window.topbar.conn_pill.text(), "متصل")
        self.assertIn(PALETTE["GREEN"], window.topbar.conn_pill.styleSheet())

    # --- G1.15 DoD a: نجاح الاتصال ينشر CONNECTED ويُحدِّث الأوامر المفتوحة ---

    def test_branch_connect_propagates_connected_and_refreshes_open_orders(self):
        notifier = ConnectionStateNotifier()
        oo = FakeOpenOrdersScreen()
        window = FakeWindow(notifier, FakeContent({"02_open_orders": oo}))
        cfg = FakeCfg()
        wrapped = make_connect_wrapper(window, lambda *a, **k: FakeResult(ok=True), cfg)
        result = wrapped(api_key="k", api_secret="s", keys_path="")
        self.assertTrue(getattr(result, "ok", False))
        self.assertIsNotNone(notifier.state)
        self.assertEqual(notifier.state.status, ConnectionStatus.CONNECTED)
        self.assertEqual(oo.refresh_called, 1)

    # --- G1.15 DoD b: فشل الاتصال لا ينشر حالة ولا يُحدِّث الأوامر ------------

    def test_branch_connect_failure_does_not_propagate_or_refresh(self):
        notifier = ConnectionStateNotifier()
        oo = FakeOpenOrdersScreen()
        window = FakeWindow(notifier, FakeContent({"02_open_orders": oo}))
        cfg = FakeCfg()
        wrapped = make_connect_wrapper(window, lambda *a, **k: FakeResult(ok=False), cfg)
        result = wrapped(api_key="k", api_secret="s")
        self.assertFalse(getattr(result, "ok", True))
        self.assertIsNone(notifier.state)
        self.assertEqual(oo.refresh_called, 0)


if __name__ == "__main__":
    unittest.main()
