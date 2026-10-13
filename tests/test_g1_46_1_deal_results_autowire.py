# -*- coding: utf-8 -*-
"""اختبارات G1.46.1 — الاستدعاء التلقائي لتعبئة بطاقة نتيجة الصفقة (DealResultCard).

متابعة G1.46 (عرض فقط): تتحقّق من أنّ ``DynamicMonitoringScreen`` تُعبّئ بطاقات
نتيجة الصفقة تلقائيًّا من سجلّ التدقيق عبر ``load_completed_trades`` ثم
``set_deal_results`` القائمة، دون أي شبكة ولا مساس بأي منطق تنفيذ/إصدار:
  - ``refresh_deal_results`` يحمّل ويُظهر بطاقة الوسيلة المطابقة (PRICE_BRACKET).
  - ``showEvent`` (التنقّل) يُعبّئ ويبدأ المؤقّت الدوري؛ ``hideEvent`` يوقفه.
  - غياب ملف التدقيق لا يرمي والبطاقات تبقى مخفية (fail-safe).
  - ``ContentRouter`` يمرّر ``audit_path`` إلى شاشة المراقبة (نفس مِصرف الصفقات المنتهية).

تعمل تحت ``QT_QPA_PLATFORM=offscreen``.
"""
import json
import os
import tempfile
import unittest
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ocobot.ui._qt import QApplication, QT_BINDING
from ocobot.ui.monitoring import DynamicMonitoringScreen
from ocobot.ui.content import ContentRouter

if QT_BINDING == "PySide6":
    from PySide6.QtGui import QShowEvent, QHideEvent
else:  # pragma: no cover - exercised only without PySide6
    from PyQt6.QtGui import QShowEvent, QHideEvent


def _app():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _line(event, details):
    """سطر JSONL بنفس شكل AuditLog (Decimal كنصوص عبر default=str)."""
    return json.dumps(
        {"ts": "2026-05-01T00:00:00+00:00", "event": event, "details": details},
        ensure_ascii=False,
        default=str,
    )


def _write_audit_price_bracket(dirpath):
    """سجلّ تدقيق اصطناعي: صفقة مُغلقة واحدة مُسنَدة إلى PRICE_BRACKET (الدخول=100)."""
    path = os.path.join(dirpath, "ocobot_audit.jsonl")
    lines = [
        _line("monitor_start", {"order_list_id": 7001, "symbol": "BTCUSDT",
                                "reference_price": Decimal("100")}),
        _line("exit_source", {"source": "PRICE_BRACKET"}),
        _line("monitor_closed", {"end_reason": "completed_sl", "reason": "stopped"}),
    ]
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return path


class DealResultsAutowireTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def setUp(self):
        self._widgets = []

    def tearDown(self):
        # تنظيف صارم: أوقِف أي مؤقّت وحرِّر الودجت وادفع أحداث الحذف — حتى لا يتسرّب
        # مؤقّت دوري نشط أو ودجت offscreen عبر بقيّة السويت (تثبيت ضد قطع أصيل نادر).
        for w in self._widgets:
            try:
                t = getattr(w, "_deal_results_timer", None)
                if t is not None:
                    t.stop()
            except Exception:
                pass
            try:
                w.hide()
            except Exception:
                pass
            try:
                w.deleteLater()
            except Exception:
                pass
        self._widgets = []
        try:
            self.app.processEvents()
        except Exception:
            pass

    def _screen(self, **kwargs):
        """يُنشئ شاشة مراقبة ويسجّلها للتنظيف الصارم في tearDown."""
        screen = DynamicMonitoringScreen(**kwargs)
        self._widgets.append(screen)
        return screen

    def test_refresh_populates_matching_card_from_audit_path(self):
        """refresh_deal_results يحمّل من audit_path ويُظهر بطاقة الوسيلة المطابقة."""
        audit = _write_audit_price_bracket(tempfile.mkdtemp())
        screen = self._screen(audit_path=audit, runner=None)
        card = screen._deal_result_cards.get("PRICE_BRACKET")
        self.assertIsNotNone(card)
        # قبل التحديث: مخفية (لا نتيجة بعد).
        self.assertTrue(card.isHidden())
        # بعد التحديث التلقائي: تُعبّأ وتظهر بقيمة الدخول الصحيحة.
        screen.refresh_deal_results()
        self.assertFalse(card.isHidden())
        self.assertEqual(card._val_entry.text(), "100")

    def test_show_event_autofills_on_navigation_and_starts_timer(self):
        """showEvent (التنقّل) يملأ البطاقة فورًا ويبدأ المؤقّت الدوري."""
        audit = _write_audit_price_bracket(tempfile.mkdtemp())
        screen = self._screen(audit_path=audit, runner=None)
        card = screen._deal_result_cards.get("PRICE_BRACKET")
        self.assertTrue(card.isHidden())
        self.assertFalse(screen._deal_results_timer.isActive())
        screen.showEvent(QShowEvent())
        self.assertFalse(card.isHidden())
        self.assertTrue(screen._deal_results_timer.isActive())

    def test_hide_event_stops_timer(self):
        """hideEvent يوقف المؤقّت الدوري (لا IO وهي مخفية)."""
        screen = self._screen(audit_path=None, runner=None)
        screen.showEvent(QShowEvent())
        self.assertTrue(screen._deal_results_timer.isActive())
        screen.hideEvent(QHideEvent())
        self.assertFalse(screen._deal_results_timer.isActive())

    def test_missing_audit_file_is_failsafe_and_cards_hidden(self):
        """غياب ملف التدقيق لا يرمي والبطاقات تبقى مخفية (fail-safe)."""
        missing = os.path.join(tempfile.mkdtemp(), "does_not_exist.jsonl")
        screen = self._screen(audit_path=missing, runner=None)
        screen.refresh_deal_results()  # لا يجوز أن يرمي
        for src in ("MONITORING", "PRICE_BRACKET", "BTC_FOLLOW", "POSITION_SAFETY_NET"):
            card = screen._deal_result_cards.get(src)
            if card is not None:
                self.assertTrue(card.isHidden())

    def test_content_router_passes_audit_path_to_monitoring(self):
        """ContentRouter يمرّر audit_path إلى شاشة المراقبة (نفس مِصرف الصفقات المنتهية)."""
        audit = _write_audit_price_bracket(tempfile.mkdtemp())
        router = ContentRouter(audit_path=audit)
        self._widgets.append(router)
        mon = router.findChild(DynamicMonitoringScreen)
        self.assertIsNotNone(mon)
        self.assertEqual(mon._deal_audit_path, audit)


if __name__ == "__main__":
    unittest.main()
