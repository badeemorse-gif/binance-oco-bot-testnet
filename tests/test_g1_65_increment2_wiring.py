# -*- coding: utf-8 -*-
"""اختبار انحدار G1.65 increment #2 — وصل الخروج المتكيّف خلف الـflag.

يثبّت الثابت الأهمّ: **enabled=False / dynamic_exit=None = السلوك الحالي تمامًا**
في كلٍّ من reposition.build_draft/execute و monitoring.MonitoringEngine؛ ثم يثبت
أنّ المسار المفعّل (enabled=True) يطبّق صيغة next_stop فعليًّا ويمرّر مدخلاتها.
صفر رأس مال، صفر شبكة — fakes فقط.
"""
import unittest
from decimal import Decimal

from ocobot.domain.exchange_info import ExchangeInfoService
from ocobot.domain.oco_reader import OcoReader
from ocobot.domain.reposition import ExecutionState, SafeExecutor
from ocobot.domain.pricing import compute_levels
from ocobot.domain.dynamic_exit import DynamicExitConfig, next_stop
from ocobot.domain.monitoring import MonitoringEngine
from tests._fakes import FakeClient
from tests._fakes_monitoring import (
    FakeSafeExecutor,
    FakeSelectedOCO,
    make_result,
)


def _executor(client):
    exi = ExchangeInfoService(client, monotonic=lambda: 1.0)
    reader = OcoReader(client)
    return SafeExecutor(client, reader, exi)


def _success():
    return make_result(ExecutionState.SUCCESS, new_order_list_id=99,
                       cancelled_order_list_id=31)


# مصفوفة مدخلات (tp_pct, sl_pct, reference_price) — رموز BTCUSDT بفلتر tick=0.01
_MATRIX = [("4", "2", "60000"), ("1", "3", "100"),
           ("2.5", "1.5", "45000"), ("4", "2", "250.5")]


class TestRepositionDisabledIdentity(unittest.TestCase):
    def test_none_equals_disabled_config(self):
        # dynamic_exit=None  ==  dynamic_exit=DynamicExitConfig() (enabled=False)
        for tp, sl, ref in _MATRIX:
            _, d_none = _executor(FakeClient()).build_draft(31, tp, sl, ref)
            _, d_cfg = _executor(FakeClient()).build_draft(
                31, tp, sl, ref, dynamic_exit=DynamicExitConfig())
            self.assertEqual(d_none.to_dict(), d_cfg.to_dict(),
                             msg="disabled config must not change the draft")

    def test_enabled_but_missing_inputs_is_identical(self):
        # enabled=True لكن بلا peak/prev_stop/atr ⇒ الحارس يمنع أي تغيير
        for tp, sl, ref in _MATRIX:
            _, d_none = _executor(FakeClient()).build_draft(31, tp, sl, ref)
            _, d_guard = _executor(FakeClient()).build_draft(
                31, tp, sl, ref, dynamic_exit=DynamicExitConfig(enabled=True))
            self.assertEqual(d_none.to_dict(), d_guard.to_dict())

    def test_execute_disabled_identity(self):
        r1 = _executor(FakeClient()).execute(31, "4", "2", "60000", dry_run=True)
        r2 = _executor(FakeClient()).execute(
            31, "4", "2", "60000", dry_run=True, dynamic_exit=DynamicExitConfig())
        self.assertEqual(r1.state, r2.state)
        self.assertEqual(r1.draft.to_dict(), r2.draft.to_dict())


class TestRepositionEnabledAppliesNextStop(unittest.TestCase):
    def test_enabled_applies_next_stop_formula(self):
        tp, sl, ref = "4", "2", "60000"
        peak, prev_stop, atr = 63000.0, 59000.0, 1.0

        ex = _executor(FakeClient())
        _, d_dis = ex.build_draft(31, tp, sl, ref)
        _, d_en = ex.build_draft(
            31, tp, sl, ref, dynamic_exit=DynamicExitConfig(enabled=True),
            peak_price=peak, prev_stop=prev_stop, live_atr_pct_value=atr)

        # القيمة المتوقّعة محسوبة مستقلّةً من نفس الصيغة المُتحقَّقة
        cfg = DynamicExitConfig(enabled=True)
        ns = next_stop(float(ref), peak, prev_stop, atr, p=cfg.params())
        eff = (Decimal("1") - Decimal(str(ns)) / Decimal(ref)) * Decimal("100")
        _, exp_trg, exp_lim = compute_levels(
            Decimal(ref), Decimal(tp), eff, d_en.filters.tick_size,
            gap_ticks=d_en.gap_ticks)

        self.assertEqual(d_en.stop_trigger, exp_trg)
        self.assertEqual(d_en.stop_limit, exp_lim)
        # الخروج المتكيّف يغيّر الستوب فعلًا، ولا يمسّ الـTP
        self.assertNotEqual(d_en.stop_trigger, d_dis.stop_trigger)
        self.assertEqual(d_en.tp_price, d_dis.tp_price)


class TestMonitoringDisabledIdentity(unittest.TestCase):
    def _start(self, engine):
        engine.start(FakeSelectedOCO(), trigger_pct="1", tp_pct="4",
                     sl_pct="2", reference_price="100")

    def test_none_equals_disabled_config(self):
        ex1 = FakeSafeExecutor(result=_success())
        eng1 = MonitoringEngine(ex1)
        ex2 = FakeSafeExecutor(result=_success())
        eng2 = MonitoringEngine(ex2, dynamic_exit=DynamicExitConfig())

        self._start(eng1)
        self._start(eng2)
        t1 = eng1.on_price_tick("130")
        t2 = eng2.on_price_tick("130")

        self.assertEqual(t1.event, "REPOSITIONED")
        self.assertEqual(t1.event, t2.event)
        self.assertEqual(ex1.calls, ex2.calls)  # نفس وسائط execute تمامًا
        s1 = eng1.state.to_dict()
        s2 = eng2.state.to_dict()
        # tradeUid مُعرّف عشوائي (uuid) لكل محرّك — غير متعلّق بالخروج المتكيّف
        s1.pop("tradeUid", None)
        s2.pop("tradeUid", None)
        self.assertEqual(s1, s2)


class _RecordingExecutor:
    """منفّذ تسجيل يقبل أي وسائط (للتأكّد من التمرير في المسار المفعّل)."""

    def __init__(self):
        self.calls = []

    def execute(self, **kwargs):
        self.calls.append(kwargs)
        return _success()


class TestMonitoringEnabledForwardsInputs(unittest.TestCase):
    def test_enabled_forwards_adaptive_inputs(self):
        rec = _RecordingExecutor()
        eng = MonitoringEngine(rec, dynamic_exit=DynamicExitConfig(enabled=True),
                               live_atr_pct_provider=lambda: 1.0)
        eng.start(FakeSelectedOCO(), trigger_pct="1", tp_pct="4",
                  sl_pct="2", reference_price="100")
        tick = eng.on_price_tick("130")

        self.assertEqual(tick.event, "REPOSITIONED")
        self.assertEqual(len(rec.calls), 1)
        kw = rec.calls[0]
        self.assertIn("dynamic_exit", kw)
        self.assertTrue(kw["dynamic_exit"].enabled)
        self.assertEqual(kw["live_atr_pct_value"], 1.0)
        self.assertEqual(kw["peak_price"], Decimal("130"))  # آخر سعر = القمّة
        expected_prev = Decimal("100") * (Decimal("1") - Decimal("2") / Decimal("100"))
        self.assertEqual(kw["prev_stop"], expected_prev)
        self.assertEqual(kw["reference_price"], Decimal("130"))


if __name__ == "__main__":
    unittest.main()
