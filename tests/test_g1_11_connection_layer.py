# -*- coding: utf-8 -*-
"""اختبارات طبقة الاتصال المرنة G1.11.

تغطّي: أولوية مصدر المفاتيح (حقول > ملف > مسار ثابت)، رفض المفاتيح الناقصة،
اختبار الاتصال (قراءة فقط /api/v3/account) دون رفع استثناء، إقلاع الواجهة دون
تعطّل بغياب المسار الثابت، وسلوك شاشة الاتصال (لمبة الحالة، إخفاء السر، اختيار ملف).
لا تلمس منطق التداول.
"""
import os
import io
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ocobot.config import AppConfig
from ocobot.core.environment import Environment
from ocobot.core import connection as connection_mod
from ocobot.core.connection import (
    ConnectionResult,
    test_connection,
    make_gui_connect_handler,
)

from ocobot.core.keys import resolve_credentials, ApiCredentials, CredentialsError
from ocobot.core import session as session_mod


def _write_keyfile(text):
    fd, path = tempfile.mkstemp(suffix=".txt")
    with io.open(fd, "w", encoding="utf-8") as f:
        f.write(text)
    return path


class _FakeAccountClient:
    def __init__(self, *a, **k):
        pass

    def get_account(self):
        return {"canTrade": True, "balances": []}


class _FailAccountClient:
    def __init__(self, *a, **k):
        pass

    def get_account(self):
        raise RuntimeError("boom")


class ResolveCredentialsPriority(unittest.TestCase):
    def test_fields_take_priority(self):
        creds = resolve_credentials(Environment.TESTNET, api_key="K", api_secret="S")
        self.assertIsInstance(creds, ApiCredentials)
        self.assertEqual(creds.api_key, "K")
        self.assertEqual(creds.api_secret, "S")

    def test_single_field_rejected(self):
        with self.assertRaises(CredentialsError):
            resolve_credentials(Environment.TESTNET, api_key="K")

    def test_chosen_file_used(self):
        p = _write_keyfile("TESTNET_KEY=fromfile\nTESTNET_SECRET=filesecret\n")
        try:
            creds = resolve_credentials(Environment.TESTNET, keys_path=p)
            self.assertEqual(creds.api_key, "fromfile")
            self.assertEqual(creds.api_secret, "filesecret")
        finally:
            os.remove(p)

    def test_empty_fields_no_fixed_path_fallback_raises(self):
        p = _write_keyfile("TESTNET_KEY=fallbackkey\nTESTNET_SECRET=fallbacksecret\n")
        try:
            with self.assertRaises(ValueError):  # G1.15: لا رجوع لمسار ثابت — الاتصال فقط عبر فرع الاتصال
                resolve_credentials(
                    Environment.TESTNET,
                    api_key="",
                    api_secret="",
                    keys_path="",
                    fallback_path=p,
                )
        finally:
            os.remove(p)

    def test_no_source_rejected(self):
        with self.assertRaises(ValueError):
            resolve_credentials(Environment.TESTNET)


class TestConnectionBehavior(unittest.TestCase):
    def test_success_returns_connected(self):
        cfg = AppConfig(env=Environment.TESTNET)
        res = test_connection(
            cfg, api_key="K", api_secret="S", client_factory=lambda c, cr: _FakeAccountClient()
        )
        self.assertTrue(res.ok)
        self.assertEqual(res.message, "متصل")

    def test_account_failure_returns_error_not_raise(self):
        cfg = AppConfig(env=Environment.TESTNET)
        res = test_connection(
            cfg, api_key="K", api_secret="S", client_factory=lambda c, cr: _FailAccountClient()
        )
        self.assertFalse(res.ok)
        self.assertIn("فشل الاتصال", res.message)

    def test_missing_keys_returns_error_not_raise(self):
        cfg = AppConfig(
            env=Environment.TESTNET,
            keys_path=os.path.join(tempfile.gettempdir(), "no_such_key_g111.txt"),
        )
        res = test_connection(cfg)
        self.assertFalse(res.ok)
        self.assertIsInstance(res, ConnectionResult)

    def test_single_field_returns_error(self):
        cfg = AppConfig(env=Environment.TESTNET)
        res = test_connection(cfg, api_key="K")
        self.assertFalse(res.ok)


class MakeGuiConnectHandler(unittest.TestCase):
    def setUp(self):
        session_mod.clear_key_source()

    def tearDown(self):
        session_mod.clear_key_source()

    def test_success_sets_session_source(self):
        cfg = AppConfig(env=Environment.TESTNET)
        with mock.patch.object(
            connection_mod, "test_connection", return_value=ConnectionResult(True, "متصل")
        ):
            handler = make_gui_connect_handler(cfg)
            res = handler(api_key="MYKEY", api_secret="MYSEC", keys_path="")
        self.assertTrue(res.ok)
        src = session_mod.get_key_source()
        self.assertEqual(src.api_key, "MYKEY")
        self.assertEqual(src.api_secret, "MYSEC")

    def test_failure_does_not_set_session_source(self):
        cfg = AppConfig(env=Environment.TESTNET)
        with mock.patch.object(
            connection_mod, "test_connection", return_value=ConnectionResult(False, "فشل")
        ):
            handler = make_gui_connect_handler(cfg)
            res = handler(api_key="MYKEY", api_secret="MYSEC", keys_path="")
        self.assertFalse(res.ok)
        src = session_mod.get_key_source()
        self.assertIsNone(src.api_key)


class ConnectionScreenWidget(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from ocobot.ui._qt import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def _make(self, handler=None):
        from ocobot.ui.connection_screen import ConnectionScreen

        return ConnectionScreen(runner=None, connect_handler=handler)

    def test_secret_is_masked(self):
        from ocobot.ui._qt import QLineEdit

        screen = self._make()
        self.assertEqual(screen._api_secret_input.echoMode(), QLineEdit.EchoMode.Password)

    def test_connect_success_sets_green_label(self):
        screen = self._make(handler=lambda **kw: ConnectionResult(True, "متصل"))
        screen._api_key_input.setText("K")
        screen._api_secret_input.setText("S")
        screen._on_connect_clicked()
        self.assertEqual(screen._light.text(), "متصل")

    def test_connect_failure_sets_red_label(self):
        screen = self._make(handler=lambda **kw: ConnectionResult(False, "فشل واضح"))
        screen._on_connect_clicked()
        self.assertEqual(screen._light.text(), "خطأ اتصال")
        self.assertEqual(screen._message.text(), "فشل واضح")

    def test_no_handler_shows_disconnected(self):
        screen = self._make(handler=None)
        screen._on_connect_clicked()
        self.assertEqual(screen._light.text(), "غير متصل")

    def test_open_file_sets_selected_path(self):
        from ocobot.ui import connection_screen as cs

        screen = self._make()
        with mock.patch.object(
            cs.QFileDialog, "getOpenFileName", return_value=("C:/keys/key.txt", "")
        ):
            screen._on_open_file_clicked()
        self.assertEqual(screen.selected_file_path(), "C:/keys/key.txt")


class StartupCrashSafe(unittest.TestCase):
    def test_build_app_without_keys_has_connection_screen(self):
        from ocobot.ui.app import build_app

        app, window = build_app()
        self.assertIsNotNone(window.content.screen_for("07_connection"))


class ReadOnlyTestnetInvariants(unittest.TestCase):
    def test_account_endpoint_is_read_only_path(self):
        from ocobot.core import rest_client

        self.assertEqual(rest_client.PATH_ACCOUNT, "/api/v3/account")

    def test_default_env_is_testnet(self):
        self.assertEqual(AppConfig().env, Environment.TESTNET)


if __name__ == "__main__":
    unittest.main()
