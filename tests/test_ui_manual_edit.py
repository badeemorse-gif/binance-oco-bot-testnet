"""اختبارات شاشة التعديل اليدوي (T12a — s6): كشف تدريجي + معاينة الأسعار
الثلاث + مؤشّر الترتيب الصارم + عرض القيم القديمة + زر Max Available Stop +
خُطّاف set_current_price. كلها offscreen ونقيّة بلا شبكة (يحترم حارس
tests/test_ui_no_direct_network) وبلا خيوط رَنَر (runner=None)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest
from decimal import Decimal

from ocobot.ui._qt import QApplication
from ocobot.ui.theme import apply_theme
from ocobot.ui.selected_oco import SelectedOcoScreen, EMPTY
from ocobot.domain.models import SelectedOCO, SymbolFilters, fmt
from ocobot.domain.pricing import compute_levels, max_available_stop


def _sample(current_price=None, tick_size=Decimal("0.00001")):
    """هوية SelectedOCO محددة (بلا شبكة) بفلاتر tick + سعر مرجعي اختياري."""
    return SelectedOCO(
        order_list_id=31,
        symbol="BTCUSDT",
        quantity=Decimal("10"),
        tp=Decimal("0.05200"),
        stop_trigger=Decimal("0.04900"),
        stop_limit=Decimal("0.04899"),
        leg_ids=[11, 12],
        status="EXECUTING",
        current_price=current_price,
        filters=SymbolFilters(symbol="BTCUSDT", tick_size=tick_size),
    )


class ManualEditScreenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    # 1) كشف تدريجي: حقلا TP%/SL% مخفيّان ابتداءً ويظهران عند التفعيل.
    def test_progressive_disclosure_of_pct_fields(self):
        screen = SelectedOcoScreen(runner=None)
        screen.show()
        self.assertFalse(screen._tp_pct_edit.isVisible())
        self.assertFalse(screen._sl_pct_edit.isVisible())
        screen._edit_toggle.setChecked(True)
        self.assertTrue(screen._tp_pct_edit.isVisible())
        self.assertTrue(screen._sl_pct_edit.isVisible())

    # 2) القيم القديمة معروضة للمرجع (acceptance #2).
    def test_old_values_shown_for_reference(self):
        sample = _sample()
        screen = SelectedOcoScreen(runner=None)
        screen.set_selected(sample)
        self.assertEqual(
            screen._old_fields["stop_limit"].text(), fmt(sample.stop_limit)
        )
        self.assertEqual(
            screen._old_fields["stop_trigger"].text(), fmt(sample.stop_trigger)
        )
        self.assertEqual(screen._old_fields["tp"].text(), fmt(sample.tp))
        for key in ("stop_limit", "stop_trigger", "tp"):
            self.assertNotEqual(screen._old_fields[key].text(), EMPTY)

    # 3) معاينة الأسعار الثلاث تطابق مثال التصميم.
    def test_three_price_preview_matches_design_example(self):
        sample = _sample(current_price=Decimal("0.05060"))
        screen = SelectedOcoScreen(runner=None)
        screen.set_selected(sample)
        screen._edit_toggle.setChecked(True)
        screen._tp_pct_edit.setText("4")
        screen._sl_pct_edit.setText("2")
        tp, trigger, stop_limit = compute_levels(
            Decimal("0.05060"), Decimal("4"), Decimal("2"), Decimal("0.00001")
        )
        # مطابقة القيم المتوقّعة من مثال التصميم صراحةً.
        self.assertEqual(fmt(tp), "0.05262")
        self.assertEqual(fmt(trigger), "0.04959")
        self.assertEqual(fmt(stop_limit), "0.04958")
        # مطابقة ما تعرضه الواجهة (بنفس صيغة fmt).
        self.assertEqual(screen._new_tp.text(), fmt(tp))
        self.assertEqual(screen._new_trigger.text(), fmt(trigger))
        self.assertEqual(screen._new_stop_limit.text(), fmt(stop_limit))

    # 4) مؤشّر الترتيب الصارم سليم (acceptance #1).
    def test_strict_order_indicator_ok(self):
        sample = _sample(current_price=Decimal("0.05060"))
        screen = SelectedOcoScreen(runner=None)
        screen.set_selected(sample)
        screen._edit_toggle.setChecked(True)
        screen._tp_pct_edit.setText("4")
        screen._sl_pct_edit.setText("2")
        self.assertEqual(screen._order_indicator.property("state"), "ok")
        self.assertIn("سليم", screen._order_indicator.text())

    # 5) خُطّاف set_current_price: يحدّث المعاينة ويُفرِّغها عند None (D14).
    def test_set_current_price_hook_refreshes_and_blanks(self):
        sample = _sample(current_price=None)
        screen = SelectedOcoScreen(runner=None)
        screen.set_selected(sample)
        screen._edit_toggle.setChecked(True)
        screen._tp_pct_edit.setText("4")
        screen._sl_pct_edit.setText("2")
        # لا معاينة قبل توفّر سعر مرجعي حقيقي.
        self.assertEqual(screen._new_tp.text(), EMPTY)
        # حقن سعر → تظهر الأسعار الثلاث.
        screen.set_current_price(Decimal("0.05060"))
        self.assertEqual(screen._new_tp.text(), "0.05262")
        self.assertEqual(screen._new_trigger.text(), "0.04959")
        self.assertEqual(screen._new_stop_limit.text(), "0.04958")
        # None يُفرِّغ المعاينة (D14).
        screen.set_current_price(None)
        self.assertEqual(screen._new_tp.text(), EMPTY)
        self.assertEqual(screen._new_trigger.text(), EMPTY)
        self.assertEqual(screen._new_stop_limit.text(), EMPTY)

    # 6) زر Max Available Stop يملأ SelectedLiveMaxStop بالقيمة المحسوبة.
    def test_max_available_stop_button_populates_label(self):
        sample = _sample(current_price=Decimal("0.05060"))
        screen = SelectedOcoScreen(runner=None)
        screen.set_selected(sample)
        screen._on_max_available_stop()
        expected = max_available_stop(Decimal("0.05060"), Decimal("0.00001"))
        self.assertEqual(screen._live_max_stop.text(), fmt(expected))
        self.assertNotEqual(screen._live_max_stop.text(), EMPTY)

    # 7) D14: بلا سعر مرجعي حقيقي لا معاينة ولا مؤشّر (لا قيم بائتة).
    def test_no_static_preview_without_current_price_D14(self):
        sample = _sample(current_price=None)
        screen = SelectedOcoScreen(runner=None)
        screen.set_selected(sample)
        screen._edit_toggle.setChecked(True)
        screen._tp_pct_edit.setText("4")
        screen._sl_pct_edit.setText("2")
        for cell in (screen._new_stop_limit, screen._new_trigger, screen._new_tp):
            self.assertEqual(cell.text(), EMPTY)
        self.assertEqual(screen._order_indicator.text(), EMPTY)

    # 8) clear() يُصفّر السعر المرجعي والمعاينة والمؤشّر.
    def test_clear_resets_price_preview_and_indicator(self):
        sample = _sample(current_price=Decimal("0.05060"))
        screen = SelectedOcoScreen(runner=None)
        screen.set_selected(sample)
        screen._edit_toggle.setChecked(True)
        screen._tp_pct_edit.setText("4")
        screen._sl_pct_edit.setText("2")
        # قبل clear المعاينة ممتلئة.
        self.assertEqual(screen._new_tp.text(), "0.05262")
        screen.clear()
        self.assertIsNone(screen._current_price)
        for cell in (screen._new_stop_limit, screen._new_trigger, screen._new_tp):
            self.assertEqual(cell.text(), EMPTY)


# ---- T12b (s5): اختبارات قبول التنفيذ الآمن (Activate عبر SafeExecutor) ----
from ocobot.domain.reposition import ExecutionState
from ocobot.core.failure_matrix import humanize
from tests._fakes_monitoring import FakeSafeExecutor, make_result


class _SyncRunner:
    def submit(self, fn, *a, on_result=None, on_error=None, **k):
        try:
            r = fn(*a, **k)
        except Exception as exc:  # pragma: no cover
            if on_error:
                on_error(exc)
            return None
        if on_result:
            on_result(r)
        return r


def _exec_cb(fake):
    def _cb(order_list_id, tp_pct, sl_pct, reference_price):
        return fake.execute(order_list_id=order_list_id, tp_pct=tp_pct,
                            sl_pct=sl_pct, reference_price=reference_price)
    return _cb


class ActivateSafeExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    def _prepare(self, screen):
        screen.set_selected(_sample(current_price=Decimal("0.05060")))
        screen.set_current_price(Decimal("0.05060"))
        screen._edit_toggle.setChecked(True)
        screen._tp_pct_edit.setText("4")
        screen._sl_pct_edit.setText("2")
        screen.activate_button.setEnabled(True)
        screen.show()
        return screen

    def test_activate_rejected_does_not_execute(self):
        fake = FakeSafeExecutor()
        screen = SelectedOcoScreen(runner=_SyncRunner(), execute_cb=_exec_cb(fake),
                                   confirm_cb=lambda text: False)
        self._prepare(screen)
        screen.activate_button.click()
        self.assertEqual(fake.calls, [])
        self.assertFalse(screen._naked_banner.isVisible())
        self.assertTrue(screen.activate_button.isEnabled())

    def test_activate_confirmed_executes_once_with_args(self):
        fake = FakeSafeExecutor()
        screen = SelectedOcoScreen(runner=_SyncRunner(), execute_cb=_exec_cb(fake),
                                   confirm_cb=lambda text: True)
        self._prepare(screen)
        screen.activate_button.click()
        self.assertEqual(len(fake.calls), 1)
        call = fake.calls[0]
        self.assertEqual(call["order_list_id"], 31)
        self.assertEqual(call["tp_pct"], "4")
        self.assertEqual(call["sl_pct"], "2")
        self.assertEqual(call["reference_price"], screen._current_price)

    def test_naked_banner_visible_during_and_hidden_after(self):
        fake = FakeSafeExecutor()
        observed = {}

        def cb(order_list_id, tp_pct, sl_pct, reference_price):
            observed["during"] = screen._naked_banner.isVisible()
            return fake.execute(order_list_id=order_list_id, tp_pct=tp_pct,
                                sl_pct=sl_pct, reference_price=reference_price)

        screen = SelectedOcoScreen(runner=_SyncRunner(), execute_cb=cb,
                                   confirm_cb=lambda text: True)
        self._prepare(screen)
        self.assertFalse(screen._naked_banner.isVisible())
        screen.activate_button.click()
        self.assertTrue(observed.get("during"))
        self.assertFalse(screen._naked_banner.isVisible())

    def test_failure_path_shows_humanize_message(self):
        result = make_result(ExecutionState.FAILED_NEEDS_ATTENTION)
        fake = FakeSafeExecutor(result=result)
        screen = SelectedOcoScreen(runner=_SyncRunner(), execute_cb=_exec_cb(fake),
                                   confirm_cb=lambda text: True)
        self._prepare(screen)
        screen.activate_button.click()
        self.assertEqual(screen._activate_status.text(), humanize(result))
        self.assertFalse(screen._naked_banner.isVisible())


if __name__ == "__main__":
    unittest.main()
