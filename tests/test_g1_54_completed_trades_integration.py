# -*- coding: utf-8 -*-
"""G1.54 chunk_2 — اختبارات دمج لوحة الربحية + فلترة الوضع + drill-down في شاشة 08.

يتحقّق (تحت ``QT_QPA_PLATFORM=offscreen``، بلا شبكة):
  - اللوحة العلوية موجودة وتعرض بطاقات الأوضاع عند توفّر صفقات.
  - drill-down: اختيار وضع من اللوحة يُصفّي القائمة الوسطى لذلك الوضع فقط.
  - زرّ «كل الأوضاع» (modeSelected "") يُعيد كل الصفقات.
  - ثبات التحديد (G1.51) محفوظ أثناء الفلترة والتحديث الدوري المتطابق.
  - اختيار صفقة بعد الفلترة يحمّل تفاصيلها (drill-down حتى التفاصيل).
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import unittest
from decimal import Decimal
from types import SimpleNamespace

from ocobot.ui._qt import QApplication
from ocobot.ui.completed_trades import CompletedTradesScreen


def _app():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _step():
    return SimpleNamespace(
        ts="2026-10-14T10:00:00Z", order_list_id=1, price=Decimal("100"),
        stop_trigger=Decimal("95"), stop_limit=Decimal("94"), sell_price=Decimal("101"))


def _trade(key, mode, pct, usd):
    return SimpleNamespace(
        trade_key=key, symbol="BTCUSDT", reference_price=Decimal("100"),
        opened_at="2026-10-14T10:00:00Z", closed_at="2026-10-14T10:05:00Z",
        close_reason="", exit_price=Decimal("101"), side="SELL", quantity=Decimal("1"),
        profit_available=True, profit_pct=Decimal(pct), profit_usd=Decimal(usd),
        session_id="", session_no=0, end_reason="completed_tp", status="closed",
        exit_source=mode, steps=[_step()])


def _trades():
    # ثلاث صفقات: وضعان (MANUAL_EXIT ×2، MONITORING ×1).
    return [
        _trade("kA", "MANUAL_EXIT", "5", "50"),
        _trade("kB", "MONITORING", "-1", "-10"),
        _trade("kC", "MANUAL_EXIT", "3", "30"),
    ]


class CompletedTradesG1_54IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def _screen(self):
        tmp = tempfile.mkdtemp(prefix="g1_54_")
        audit = os.path.join(tmp, "ocobot_audit.jsonl")  # غير موجود عمدًا
        return CompletedTradesScreen(audit_path=audit)

    def test_panel_present_and_shows_cards(self):
        screen = self._screen()
        screen.set_trades(_trades())
        self.assertTrue(hasattr(screen, "profit_panel"))
        self.assertEqual(set(screen.profit_panel.card_modes()),
                         {"MANUAL_EXIT", "MONITORING"})
        self.assertEqual(screen.list_table.rowCount(), 3)

    def test_drill_down_filters_list_by_mode(self):
        screen = self._screen()
        screen.set_trades(_trades())
        # drill-down عبر مسار الإشارة الفعلي (نقر بطاقة الوضع).
        screen.profit_panel._on_select("MANUAL_EXIT")
        self.assertEqual(screen._mode_filter, "MANUAL_EXIT")
        self.assertEqual(screen.list_table.rowCount(), 2)
        self.assertTrue(all(t.exit_source == "MANUAL_EXIT" for t in screen._visible))

    def test_all_modes_restores_full_list(self):
        screen = self._screen()
        screen.set_trades(_trades())
        screen.profit_panel._on_select("MANUAL_EXIT")
        self.assertEqual(screen.list_table.rowCount(), 2)
        screen.profit_panel._on_select("")  # كل الأوضاع
        self.assertEqual(screen._mode_filter, "")
        self.assertEqual(screen.list_table.rowCount(), 3)

    def test_selection_stable_under_filter_identical_refresh(self):
        screen = self._screen()
        screen.set_trades(_trades())
        screen._on_mode_filter("MANUAL_EXIT")
        screen.list_table.setCurrentCell(1, 0)  # kC ضمن MANUAL_EXIT
        self.assertEqual(screen._selected_trade().trade_key, "kC")
        item_before = screen.list_table.item(1, 0)
        # تحديث دوري متطابق (نفس البيانات ونفس الفلتر) ⇒ لا إعادة بناء ولا سرقة تحديد.
        screen.set_trades(_trades())
        self.assertEqual(screen.list_table.currentRow(), 1)
        self.assertIs(screen.list_table.item(1, 0), item_before)
        self.assertEqual(screen._selected_trade().trade_key, "kC")

    def test_drill_down_to_details(self):
        screen = self._screen()
        screen.set_trades(_trades())
        screen._on_mode_filter("MANUAL_EXIT")
        screen.list_table.setCurrentCell(0, 0)
        trade = screen._selected_trade()
        self.assertIsNotNone(trade)
        screen.show_trade_details(trade)
        # جدول التفاصيل تعبّأ بخطوة واحدة على الأقل.
        self.assertGreaterEqual(screen.detail_table.rowCount(), 1)

    def test_filter_empty_mode_shows_note(self):
        screen = self._screen()
        screen.set_trades(_trades())
        screen._on_mode_filter("BTC_FOLLOW")  # لا صفقات لهذا الوضع
        self.assertEqual(screen.list_table.rowCount(), 0)
        self.assertFalse(screen.note.isHidden())


if __name__ == "__main__":
    unittest.main()
