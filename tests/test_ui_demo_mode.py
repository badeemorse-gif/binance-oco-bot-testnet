"""اختبارات شاشة وضع العرض (Demo Mode) — T14.s3، offscreen، بلا شبكة/كتابة حقيقية.

تعكس نمط tests/test_ui_monitoring.py: QT_QPA_PLATFORM=offscreen؛ unittest؛
setUpClass QApplication + apply_theme؛ ContentRouter. تغطّي:
  - بناء الشاشة offscreen بأمان.
  - DemoSimulator يُنتج أسعارًا *متغيّرة* عبر ticks (حتميّ ببذرة/تسلسل محقون).
  - الشاشة قابلة للوصول تحت المفتاح "06_demo".
  - لا آثار كتابة حقيقية: لا شبكة/عميل صرف/إنشاء أوامر/SafeExecutor/persistence.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import inspect
import unittest
from decimal import Decimal

from ocobot.ui._qt import QApplication
from ocobot.ui.theme import apply_theme
from ocobot.ui.demo_mode import (
    DemoModeScreen,
    DemoSimulator,
    LIVE_FIELDS,
    EMPTY,
    DEMO_ENVIRONMENT,
)
from ocobot.ui.content import ContentRouter


class DemoModeScreenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    # --- يُنشأ offscreen بأمان ------------------------------------------
    def test_screen_constructs_offscreen(self):
        screen = DemoModeScreen()
        screen.show()
        self.assertEqual(screen.screen_key, "06_demo")
        self.assertEqual(screen.objectName(), "Screen_06_demo")
        # كل حقول اللوحة الحيّة مبنيّة وظاهرة.
        for key, _label in LIVE_FIELDS:
            self.assertIn(key, screen._live, "حقل مفقود: %s" % key)
            self.assertTrue(screen._live[key].isVisible(), "حقل غير ظاهر: %s" % key)

    # --- وسم البيئة يقرأ DEMO صراحةً (لا يُوهم أنه Live) -----------------
    def test_environment_reads_demo_not_live(self):
        screen = DemoModeScreen()
        self.assertEqual(screen._live["environment"].text(), DEMO_ENVIRONMENT)
        self.assertEqual(DEMO_ENVIRONMENT, "DEMO")
        # شارة DEMO بارزة موجودة.
        self.assertIn("DEMO", screen.badge.text())

    # --- DemoSimulator يُنتج أسعارًا متغيّرة عبر ticks (حتميّ) ------------
    def test_simulator_produces_changing_prices_deterministic(self):
        sim = DemoSimulator(seed=1337)
        prices = [sim.tick() for _ in range(12)]
        # كلها Decimal.
        for p in prices:
            self.assertIsInstance(p, Decimal)
        # السعر يتحرّك: ليست كل القيم متطابقة (لا سعر ثابت موهِم).
        self.assertGreater(len(set(prices)), 1, "السعر لا يتحرّك عبر ticks")
        # حتميّ: نفس البذرة تُنتج نفس المسار.
        sim2 = DemoSimulator(seed=1337)
        prices2 = [sim2.tick() for _ in range(12)]
        self.assertEqual(prices, prices2)

    def test_simulator_injected_sequence_is_exact(self):
        seq = [Decimal("100"), Decimal("101"), Decimal("103"), Decimal("102")]
        sim = DemoSimulator(prices=seq)
        got = [sim.tick() for _ in range(4)]
        self.assertEqual(got, seq)

    # --- تحريك السعر على الشاشة يغيّر القيمة المعروضة --------------------
    def test_screen_advance_updates_displayed_price(self):
        seq = [Decimal("60000.00"), Decimal("60100.00"), Decimal("60250.00")]
        screen = DemoModeScreen(simulator=DemoSimulator(prices=seq))
        screen.show()
        # قبل أي تقدّم: لا سعر معروض.
        self.assertEqual(screen._live["current_price"].text(), EMPTY)
        screen.advance()
        first = screen._live["current_price"].text()
        screen.advance()
        second = screen._live["current_price"].text()
        self.assertNotEqual(first, EMPTY)
        self.assertNotEqual(first, second, "السعر المعروض لا يتغيّر عبر الخطوات")

    # --- دورة العرض: بدء → مراقبة → تفعيل → إعادة تموضع (محاكاة) --------
    def test_demo_cycle_reaches_trigger_and_reposition(self):
        # تسلسل صاعد يتجاوز مستوى التفعيل (1%).
        seq = [Decimal("60000"), Decimal("60700"), Decimal("60800"), Decimal("60900")]
        screen = DemoModeScreen(simulator=DemoSimulator(prices=seq))
        screen._pct_edits["trigger_pct"].setText("1")
        screen._pct_edits["tp_pct"].setText("4")
        screen._pct_edits["sl_pct"].setText("2")
        # أول tick لتثبيت السعر ثم بدء العرض.
        screen.advance()
        screen._on_start_clicked()
        # مرجع مثبّت؛ خطوات لاحقة تتجاوز التفعيل ثم تعيد التموضع.
        screen.advance()  # 60800 >= trigger(60600) → TRIGGERED
        self.assertEqual(screen._live["phase"].text(), "TRIGGERED")
        screen.advance()  # → REPOSITIONED
        self.assertEqual(screen._live["phase"].text(), "REPOSITIONED")

    # --- قابلة للوصول تحت "06_demo" في الراوتر --------------------------
    def test_registered_in_content_router(self):
        router = ContentRouter()
        page = router.screen_for("06_demo")
        self.assertIsInstance(page, DemoModeScreen)
        self.assertTrue(router.show_screen("06_demo"))
        self.assertEqual(router.current_key(), "06_demo")

    # --- لا آثار كتابة حقيقية: لا رموز شبكة/تنفيذ في المصدر --------------
    def test_no_real_write_side_effects(self):
        import ocobot.ui.demo_mode as demo_mod

        source = inspect.getsource(demo_mod)
        forbidden = (
            "urllib",
            "http.client",
            "import socket",
            "SignedRestClient",
            ".signed_request(",
            ".public_request(",
            "SafeExecutor",
            ".execute(",
            "requests.",
        )
        for marker in forbidden:
            self.assertNotIn(
                marker, source, "رمز كتابة حقيقية محظور في demo_mode: %s" % marker
            )

    def test_simulator_has_no_network_or_executor_attributes(self):
        sim = DemoSimulator()
        # المحاكي لا يحمل عميلًا/منفّذًا/شبكة.
        for attr in ("execute", "cancel", "create_order", "client", "session"):
            self.assertFalse(
                hasattr(sim, attr), "المحاكي يحمل سمة كتابة حقيقية: %s" % attr
            )
        # الشاشة لا تحمل engine/executor.
        screen = DemoModeScreen()
        self.assertFalse(hasattr(screen, "_engine"))
        self.assertFalse(hasattr(screen, "_executor"))


if __name__ == "__main__":
    unittest.main()
