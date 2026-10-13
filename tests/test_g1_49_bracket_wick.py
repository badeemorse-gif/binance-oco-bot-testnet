# -*- coding: utf-8 -*-
"""G1.49 — اختبار انحدار: لمس القوس الكاذب على wick لحظي (منطق خالص، بلا Qt).

الغرض: إثبات العيب المُبلَّغ عنه ثم حمايته بعد الإصلاح.
العيب الحالي (قبل chunk_3): ``BracketMonitor.check`` يطلق الخروج فور أول tick
يلمس/يتجاوز الحد، بلا أي debounce — فشمعة/wick لحظية واحدة ترتدّ بعدها تُطلق
خروجًا وتُرسي أمر البيع على سعر الـwick (أعلى من السوق المستقر ⇒ تعليق).

السلوك المطلوب (بعد chunk_3): الـwick المنفرد لا يُطلق الخروج؛ الإطلاق يتطلّب
ثبات الاختراق (تِكّتان متتاليتان على الأقل أو نافذة debounce). الإطلاق على
اختراق مستمرّ يبقى صحيحًا.

هذا الاختبار **أحمر بالتصميم** حتى يُضاف wick-debounce في chunk_3، ثم يصير أخضر.
الترسية على أفضل BID حيّ لحظة الإطلاق تُغطَّى في اختبارات الربط (chunk_4).
"""
import unittest
from decimal import Decimal

from ocobot.domain.bracket import BracketConfig, BracketMonitor


class _ExitSpy:
    """مُنفّذ خروج محقون يسجّل الاستدعاءات (بلا شبكة)."""

    def __init__(self):
        self.calls = []

    def __call__(self, exit_side, price):
        self.calls.append((exit_side, price))
        return {"action": "PLACED", "exit_side": exit_side, "price": price}


class BracketWickFalseTouchTests(unittest.TestCase):
    def _monitor(self, upper):
        cfg = BracketConfig(enabled=True, lower=None, upper=Decimal(upper))
        spy = _ExitSpy()
        mon = BracketMonitor(exit_executor=spy, config_getter=lambda: cfg)
        return mon, spy

    def test_lone_wick_touch_must_not_fire(self):
        """شمعة wick منفردة تلمس الحد العلوي ثم ترتدّ ⇒ يجب ألّا تُطلق خروجًا."""
        mon, spy = self._monitor("110")
        # ضمن النطاق
        self.assertEqual(mon.check(Decimal("109.0"))["action"], "WITHIN_BRACKET")
        # wick لحظي يلمس الحد العلوي (ثم سيرتدّ)
        mon.check(Decimal("110.0"))
        # السعر المستقر رجع ~0.8% تحت الحد
        mon.check(Decimal("108.3"))
        # المطلوب: الـwick المنفرد لم يُطلق خروجًا (يتطلّب debounce)
        self.assertFalse(
            mon.fired,
            "عيب G1.49: wick منفرد أطلق القوس بلا debounce (يجب ألّا يُطلق)",
        )
        self.assertEqual(
            spy.calls, [],
            "عيب G1.49: استُدعي مُنفّذ الخروج على wick منفرد (يجب ألّا يُستدعى)",
        )

    def test_sustained_breach_fires(self):
        """اختراق مستمرّ (تِكّتان متتاليتان فوق الحد) ⇒ يجب أن يُطلق الخروج."""
        mon, spy = self._monitor("110")
        self.assertEqual(mon.check(Decimal("109.0"))["action"], "WITHIN_BRACKET")
        mon.check(Decimal("110.0"))   # اختراق أول
        mon.check(Decimal("110.5"))   # اختراق ثانٍ متتالٍ (مستمرّ)
        self.assertTrue(mon.fired, "اختراق مستمرّ يجب أن يُطلق الخروج")
        self.assertEqual(len(spy.calls), 1, "خروج واحد فقط (latch)")

    def test_first_breach_is_armed_not_fired(self):
        """أول اختراق يعيد ARMED (مُسلَّح) بلا استدعاء المُنفّذ."""
        mon, spy = self._monitor("110")
        r = mon.check(Decimal("110.0"))
        self.assertEqual(r["action"], "ARMED")
        self.assertEqual(r["exit_side"], "upper")
        self.assertEqual(r["count"], 1)
        self.assertFalse(mon.fired)
        self.assertEqual(spy.calls, [])

    def test_non_consecutive_wicks_do_not_accumulate(self):
        """لمستا wick متقطّعتان (بينهما عودة داخل القوس) لا تتراكمان ⇒ لا إطلاق."""
        mon, spy = self._monitor("110")
        mon.check(Decimal("110.0"))   # اختراق (count=1)
        mon.check(Decimal("109.0"))   # عودة داخل القوس ⇒ تصفير العدّاد
        mon.check(Decimal("110.0"))   # اختراق جديد (count=1) ⇒ ما زال ARMED
        self.assertFalse(mon.fired)
        self.assertEqual(spy.calls, [])


class BracketLiveBidAnchorTests(unittest.TestCase):
    """G1.49: ترسية الخروج على أفضل BID حيّ لحظة الإطلاق (لا على tick الاختراق)."""

    def _monitor(self, upper, *, bid_getter=None, debounce_ticks=2):
        cfg = BracketConfig(enabled=True, lower=None, upper=Decimal(upper))
        spy = _ExitSpy()
        mon = BracketMonitor(
            exit_executor=spy, config_getter=lambda: cfg,
            bid_getter=bid_getter, debounce_ticks=debounce_ticks,
        )
        return mon, spy

    def test_fire_anchors_on_live_bid(self):
        """عند الإطلاق يُمرَّر للمُنفّذ أفضل BID حيّ، لا سعر tick الاختراق."""
        live = {"bid": Decimal("109.4")}
        mon, spy = self._monitor("110", bid_getter=lambda: live["bid"])
        mon.check(Decimal("110.0"))        # ARMED
        r = mon.check(Decimal("110.6"))    # تأكيد ⇒ إطلاق
        self.assertEqual(r["action"], "EXIT_TRIGGERED")
        self.assertEqual(r["price"], Decimal("109.4"))        # المرجع = BID الحيّ
        self.assertEqual(r["trigger_price"], Decimal("110.6"))
        self.assertEqual(spy.calls, [("upper", Decimal("109.4"))])

    def test_bid_getter_none_falls_back_to_trigger(self):
        """لو أرجع bid_getter قيمة فارغة ⇒ يُستعمل سعر الاختراق المؤكِّد (fallback)."""
        mon, spy = self._monitor("110", bid_getter=lambda: None)
        mon.check(Decimal("110.0"))
        r = mon.check(Decimal("110.6"))
        self.assertEqual(r["price"], Decimal("110.6"))
        self.assertEqual(spy.calls, [("upper", Decimal("110.6"))])

    def test_debounce_ticks_one_fires_immediately(self):
        """debounce_ticks=1 ⇒ سلوك الإطلاق الفوري (توافق خلفي عند الحاجة)."""
        mon, spy = self._monitor("110", debounce_ticks=1)
        r = mon.check(Decimal("110.0"))
        self.assertEqual(r["action"], "EXIT_TRIGGERED")
        self.assertEqual(len(spy.calls), 1)


class BracketTimeWindowDebounceTests(unittest.TestCase):
    """G1.49: نافذة زمنية (debounce_ms) تؤكّد الاختراق المستمرّ عبر clock محقون."""

    def _monitor(self, upper, *, debounce_ms, clock):
        cfg = BracketConfig(enabled=True, lower=None, upper=Decimal(upper))
        spy = _ExitSpy()
        # debounce_ticks مرتفع لعزل مسار الزمن وحده («أو» بين التِكّات والنافذة).
        mon = BracketMonitor(
            exit_executor=spy, config_getter=lambda: cfg,
            debounce_ticks=99, debounce_ms=debounce_ms, clock=clock,
        )
        return mon, spy

    def test_time_window_confirms_sustained_breach(self):
        """اختراق مستمرّ يتجاوز نافذة الزمن ⇒ إطلاق ولو لم تبلغ التِكّات العتبة."""
        t = {"now": 1000.0}
        mon, spy = self._monitor("110", debounce_ms=300, clock=lambda: t["now"])
        self.assertEqual(mon.check(Decimal("110.0"))["action"], "ARMED")  # t=1000.0
        t["now"] = 1000.4                                                 # +400ms
        r = mon.check(Decimal("110.1"))
        self.assertEqual(r["action"], "EXIT_TRIGGERED")
        self.assertEqual(len(spy.calls), 1)

    def test_time_window_not_elapsed_stays_armed(self):
        """اختراق لم يتجاوز النافذة بعد ⇒ يبقى ARMED بلا إطلاق."""
        t = {"now": 1000.0}
        mon, spy = self._monitor("110", debounce_ms=300, clock=lambda: t["now"])
        self.assertEqual(mon.check(Decimal("110.0"))["action"], "ARMED")  # t=1000.0
        t["now"] = 1000.1                                                 # +100ms فقط
        self.assertEqual(mon.check(Decimal("110.1"))["action"], "ARMED")
        self.assertFalse(mon.fired)


if __name__ == "__main__":
    unittest.main()
