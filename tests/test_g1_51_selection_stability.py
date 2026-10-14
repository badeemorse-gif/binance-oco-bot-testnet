# -*- coding: utf-8 -*-
"""اختبار انحدار ثبات التحديد في شاشة الصفقات المنتهية — G1.51.

خلفية العيب (root-cause): كان ``set_trades`` يُعيد بناء الجدول بالكامل في كل
نبضة تحديث دوري (كل 1s) عبر ``setRowCount(0)`` ثم يفرض ``setCurrentCell(0, 0)``
دائمًا، فيسرق تحديد المستخدم ويعيده للصف الأول خلال ثانية واحدة كحدّ أقصى.

تتحقّق هذه الاختبارات من السلوك المُصحَّح (كلها «حمراء بالتصميم» قبل الإصلاح):
  1) تحديث دوري بنفس البيانات (نفس قائمة ``trade_key``) لا يُعيد بناء الجدول
     ولا يسرق التحديد — يبقى الصف المحدّد كما هو ويبقى عنصر الخلية نفسه (هُويّة).
  2) عند تغيّر القائمة فعلًا (إدراج صفقة جديدة) يتبع التحديد نفس ``trade_key``
     إلى موضعه الجديد بدل القفز للصف الأول.
  3) عند اختفاء الصفقة المحدّدة من القائمة يتراجع التحديد للصف الأول بأمان.

قراءة فقط من الطبقة المعزولة (``ocobot.ui.completed_trades``) بلا شبكة ولا IO
على سجل التدقيق (يُمرَّر مسار غير موجود فيعيد الـ domain قائمة فارغة).
تعمل تحت ``QT_QPA_PLATFORM=offscreen``.
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
    """خطوة تموضع واحدة بأسعار Decimal (سعر البيع غائب كصفقة قديمة)."""
    return SimpleNamespace(
        ts="2026-10-14T10:00:00Z",
        order_list_id=1,
        price=Decimal("100"),
        stop_trigger=Decimal("95"),
        sell_price=None,
    )


def _trade(key):
    """صفقة منتهية زائفة (duck-typed) بالحقول التي تقرؤها الشاشة فقط."""
    return SimpleNamespace(
        trade_key=key,
        symbol="BTCUSDT",
        reference_price=Decimal("100"),
        closed_at="2026-10-14T10:05:00Z",
        profit_available=False,
        profit_pct=None,
        profit_usd=None,
        session_id="",
        end_reason="",
        steps=[_step()],
    )


class CompletedTradesSelectionStabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def _screen(self):
        """شاشة بمسار تدقيق غير موجود ⇒ تبدأ فارغة بلا أي IO حقيقي."""
        tmp = tempfile.mkdtemp(prefix="g1_51_")
        audit = os.path.join(tmp, "ocobot_audit.jsonl")  # غير موجود عمدًا
        return CompletedTradesScreen(audit_path=audit)

    def test_identical_refresh_keeps_selection_without_rebuild(self):
        """التحديد يثبت عبر تحديث دوري متطابق + لا إعادة بناء (هُويّة الخلية)."""
        screen = self._screen()
        trades = [_trade("k0"), _trade("k1"), _trade("k2")]
        screen.set_trades(trades)

        # المستخدم يختار الصف الثالث (الفهرس 2).
        screen.list_table.setCurrentCell(2, 0)
        self.assertEqual(screen.list_table.currentRow(), 2)
        item_before = screen.list_table.item(2, 0)

        # نبضة تحديث دوري بنفس البيانات تمامًا (نفس قائمة trade_key).
        screen.set_trades([_trade("k0"), _trade("k1"), _trade("k2")])

        # التحديد لم يُسرَق، ولم يُعَد بناء الجدول (نفس عنصر الخلية بالهُويّة).
        self.assertEqual(screen.list_table.currentRow(), 2)
        self.assertIs(screen.list_table.item(2, 0), item_before)
        self.assertEqual(screen._selected_trade().trade_key, "k2")

    def test_selection_follows_trade_key_on_list_change(self):
        """عند تغيّر القائمة يتبع التحديد نفس trade_key لا الصف الأول."""
        screen = self._screen()
        screen.set_trades([_trade("k0"), _trade("k1"), _trade("k2")])

        # اختيار الصفقة ذات المفتاح k1 (الفهرس 1).
        screen.list_table.setCurrentCell(1, 0)
        self.assertEqual(screen._selected_trade().trade_key, "k1")

        # إدراج صفقة جديدة في المقدّمة ⇒ إعادة بناء فعلية (تغيّر التوقيع).
        screen.set_trades([_trade("kN"), _trade("k0"), _trade("k1"), _trade("k2")])

        # التحديد تبع k1 إلى موضعه الجديد (الفهرس 2) بدل القفز للصف 0.
        self.assertEqual(screen.list_table.currentRow(), 2)
        self.assertEqual(screen._selected_trade().trade_key, "k1")

    def test_selection_falls_back_to_first_when_selected_disappears(self):
        """اختفاء الصفقة المحدّدة ⇒ تراجع آمن للصف الأول."""
        screen = self._screen()
        screen.set_trades([_trade("k0"), _trade("k1"), _trade("k2")])

        # اختيار الصفقة ذات المفتاح k2 (الفهرس 2).
        screen.list_table.setCurrentCell(2, 0)
        self.assertEqual(screen._selected_trade().trade_key, "k2")

        # قائمة جديدة بلا k2 ⇒ لا مطابقة للمفتاح المحفوظ.
        screen.set_trades([_trade("k0"), _trade("k1")])

        self.assertEqual(screen.list_table.currentRow(), 0)
        self.assertEqual(screen._selected_trade().trade_key, "k0")


if __name__ == "__main__":
    unittest.main()
