# -*- coding: utf-8 -*-
"""G1.12 — اختبارات طبقة قطع الاتصال المعزولة (زران Topbar + ConnectionScreen).

تغطّي: وجود زرّي القطع، تحويل حالة Topbar إلى أحمر عبر واسِم USER_DISCONNECT،
معالج القطع يمسح مصدر مفاتيح الجلسة ويعيد DISCONNECTED دون شبكة، إعادة الاتصال
بعد القطع، إقلاع آمن بلا مفاتيح، وربط مفتاح DISCONNECTED_USER باللون الأحمر.
كل شيء offscreen/offline — لا اتصال شبكي حقيقي.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest
from unittest import mock

from ocobot.ui._qt import QApplication, QPushButton
from ocobot.ui.theme import apply_theme, PALETTE
from ocobot.ui.topbar import Topbar
from ocobot.ui.connection_screen import ConnectionScreen, _STATE_DISPLAY
from ocobot.core import connection as connection_mod
from ocobot.core import session as session_mod
from ocobot.core.connection import (
    ConnectionResult,
    make_gui_disconnect_handler,
)
from ocobot.core.connection_state import ConnectionState, ConnectionStatus


class G112DisconnectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    def setUp(self):
        session_mod.clear_key_source()

    def tearDown(self):
        session_mod.clear_key_source()

    # --- presence of the two disconnect buttons ---------------------------

    def test_connection_screen_has_disconnect_button(self):
        screen = ConnectionScreen(runner=None)
        btn = screen.findChild(QPushButton, "ConnectionDisconnect")
        self.assertIsNotNone(btn, "زر القطع مفقود في شاشة الاتصال")
        # الزر الأصلي «اتصال» يبقى سليمًا باسمه.
        self.assertIsNotNone(screen.findChild(QPushButton, "ConnectionConnect"))

    def test_topbar_has_disconnect_button(self):
        topbar = Topbar()
        btn = topbar.findChild(QPushButton, "TopbarDisconnect")
        self.assertIsNotNone(btn, "زر القطع مفقود في التوب-بار")

    # --- Topbar RED via USER_DISCONNECT marker ----------------------------

    def test_disconnect_sets_state_disconnected_red_on_topbar(self):
        topbar = Topbar()
        topbar.set_connection_state(
            ConnectionState(
                status=ConnectionStatus.DISCONNECTED,
                detail="USER_DISCONNECT",
            )
        )
        self.assertEqual(topbar.conn_pill.text(), "غير متصل")
        self.assertIn(PALETTE["RED"], topbar.conn_pill.styleSheet())

    def test_plain_disconnected_stays_muted_on_topbar(self):
        # non-breaking: DISCONNECTED بلا واسِم يبقى MUTED كما في G1.11.
        topbar = Topbar()
        topbar.set_connection_state(
            ConnectionState(status=ConnectionStatus.DISCONNECTED)
        )
        self.assertEqual(topbar.conn_pill.text(), "غير متصل")
        self.assertIn(PALETTE["MUTED"], topbar.conn_pill.styleSheet())

    # --- isolated disconnect handler: clears keys, no network -------------

    def test_disconnect_handler_clears_key_source_and_returns_disconnected(self):
        session_mod.set_key_source("k", "s", None)
        self.assertEqual(session_mod.get_key_source().api_key, "k")
        handler = make_gui_disconnect_handler()
        state = handler()
        src = session_mod.get_key_source()
        self.assertIsNone(src.api_key)
        self.assertIsNone(src.api_secret)
        self.assertIsNone(src.keys_path)
        self.assertEqual(state.status, ConnectionStatus.DISCONNECTED)
        self.assertEqual(state.detail, "USER_DISCONNECT")

    def test_disconnect_handler_no_network(self):
        # القطع أوفلاين بحت: لا يستدعي test_connection ولا build_signed_client.
        session_mod.set_key_source("k", "s", None)
        with mock.patch.object(
            connection_mod, "test_connection",
            side_effect=AssertionError("test_connection must NOT be called on disconnect"),
        ), mock.patch.object(
            connection_mod, "build_signed_client",
            side_effect=AssertionError("build_signed_client must NOT be called on disconnect"),
        ):
            handler = make_gui_disconnect_handler()
            state = handler()
        self.assertEqual(state.status, ConnectionStatus.DISCONNECTED)
        self.assertIsNone(session_mod.get_key_source().api_key)

    # --- reconnect after disconnect ---------------------------------------

    def test_reconnect_after_disconnect(self):
        # 1) القطع يمسح المصدر ويعيد DISCONNECTED.
        session_mod.set_key_source("k", "s", None)
        make_gui_disconnect_handler()()
        self.assertIsNone(session_mod.get_key_source().api_key)

        # 2) إعادة الاتصال عبر مسار الاتصال المزيّف (كما في مؤشر الاتصال)
        #    تُعيد الحالة إلى CONNECTED دون إعادة تشغيل.
        screen = ConnectionScreen(
            runner=None,
            connect_handler=lambda **kw: ConnectionResult(True, "متصل"),
        )
        screen._api_key_input.setText("K")
        screen._api_secret_input.setText("S")
        screen._on_connect_clicked()
        self.assertEqual(screen._light.text(), "متصل")

    # --- safe boot with no keys -------------------------------------------

    def test_safe_boot_no_keys_disconnect_no_crash(self):
        session_mod.clear_key_source()
        screen = ConnectionScreen(runner=None)
        # لا معالج محقون + لا مفاتيح: يجب ألا يرمي استثناءً وتظهر «غير متصل».
        screen._on_disconnect_clicked()
        self.assertEqual(screen._light.text(), "غير متصل")
        self.assertIn(PALETTE["RED"], screen._light.styleSheet())

    def test_connection_screen_disconnect_key_maps_red(self):
        label, accent_key = _STATE_DISPLAY["DISCONNECTED_USER"]
        self.assertEqual(label, "غير متصل")
        self.assertEqual(accent_key, "RED")


if __name__ == "__main__":
    unittest.main()
