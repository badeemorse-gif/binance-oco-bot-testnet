# -*- coding: utf-8 -*-
"""اختبارات G1.65 increment #5 — شادو-مود + مصرف observability (قراءة-فقط).

تثبّت:
  (1) ``shadow_divergence`` خالصة وتطابق صيغة ``reposition.build_draft`` (fill=reference).
  (2) شادو في ``MonitoringEngine``: **التنفيذ يبقى المسار الحالي تمامًا** (نداء execute
      بلا وسائط تكيّفية) + يُسجَّل حدثا ``dynamic_exit_shadow`` و``dynamic_exit_atr``.
  (3) الافتراضي (shadow=False) = لا تسجيل شادو ولا تغيير سلوك.
  (4) شادو محصّن: فشل المزوّد لا يكسر دورة المراقبة.
  (5) config: علم ``OCOBOT_DYNAMIC_EXIT_SHADOW`` (افتراض off).
  (6) cli ``_dynamic_exit_kwargs``: شادو-فقط ⇒ shadow=True + enabled=False؛ الكل مُطفأ ⇒ {}.

صفر رأس مال، صفر تنفيذ فعلي، صفر شبكة — fakes فقط.
"""
import os
import unittest
from decimal import Decimal

from ocobot.config import AppConfig
from ocobot.cli import _dynamic_exit_kwargs
from ocobot.domain.dynamic_exit import DynamicExitConfig, next_stop, shadow_divergence
from ocobot.domain.monitoring import MonitoringEngine
from tests._fakes_monitoring import FakeSelectedOCO, make_result
from ocobot.domain.reposition import ExecutionState


def _success():
    return make_result(ExecutionState.SUCCESS, new_order_list_id=99,
                       cancelled_order_list_id=31)


class _RecordingExecutor:
    """منفّذ تسجيل: يلتقط وسائط execute للتأكّد من مطابقة المسار الحالي."""

    def __init__(self):
        self.calls = []

    def execute(self, **kwargs):
        self.calls.append(kwargs)
        return _success()


class _FakeAudit:
    """سجلّ تدقيق وهميّ: يجمع (event, details) — يطابق واجهة AuditLog.record."""

    def __init__(self):
        self.events = []

    def record(self, event, details):
        self.events.append((event, details))

    def events_of(self, name):
        return [d for (e, d) in self.events if e == name]


class _BoomProvider:
    """مزوّد ATR٪ يرمي دائمًا (لاختبار حصانة شادو)."""

    def __call__(self):
        raise RuntimeError("provider down")


class TestShadowDivergencePure(unittest.TestCase):
    def test_matches_build_draft_formula(self):
        ref, peak, prev_stop, atr, cur_sl = 60000.0, 63000.0, 59000.0, 1.0, 2.0
        p = DynamicExitConfig(enabled=True).params()
        rec = shadow_divergence(ref, peak, prev_stop, atr, cur_sl, p)

        ns = next_stop(ref, peak, prev_stop, atr, p)
        exp_eff = (1.0 - ns / ref) * 100.0
        self.assertAlmostEqual(rec["adaptive_next_stop"], ns, places=9)
        self.assertAlmostEqual(rec["adaptive_eff_sl_pct"], exp_eff, places=9)
        self.assertAlmostEqual(rec["divergence_pct"], exp_eff - cur_sl, places=9)
        self.assertEqual(rec["current_sl_pct"], cur_sl)
        self.assertEqual(rec["reference"], ref)

    def test_matches_reposition_decimal_formula(self):
        # تطابق عدديّ مع صيغة reposition.build_draft (Decimal) ضمن تفاوت صغير.
        ref, peak, prev_stop, atr, cur_sl = 250.5, 258.0, 246.0, 1.5, 3.0
        p = DynamicExitConfig(enabled=True).params()
        rec = shadow_divergence(ref, peak, prev_stop, atr, cur_sl, p)
        ns = next_stop(ref, peak, prev_stop, atr, p)
        eff_dec = (Decimal("1") - Decimal(str(ns)) / Decimal(str(ref))) * Decimal("100")
        self.assertAlmostEqual(rec["adaptive_eff_sl_pct"], float(eff_dec), places=6)


class TestMonitoringShadowMode(unittest.TestCase):
    def _run(self, *, shadow, dynamic_exit, provider):
        rec = _RecordingExecutor()
        audit = _FakeAudit()
        eng = MonitoringEngine(rec, dynamic_exit=dynamic_exit,
                               live_atr_pct_provider=provider, shadow=shadow,
                               audit=audit)
        eng.start(FakeSelectedOCO(), trigger_pct="1", tp_pct="4",
                  sl_pct="2", reference_price="100")
        tick = eng.on_price_tick("130")
        return rec, audit, tick

    def test_shadow_executes_plain_and_records(self):
        rec, audit, tick = self._run(
            shadow=True, dynamic_exit=DynamicExitConfig(enabled=False),
            provider=lambda: 1.0)

        self.assertEqual(tick.event, "REPOSITIONED")
        self.assertEqual(len(rec.calls), 1)
        kw = rec.calls[0]
        # **صفر تغيير سلوك**: المسار الحالي تمامًا (لا وسائط تكيّفية في execute).
        for forbidden in ("dynamic_exit", "peak_price", "prev_stop", "live_atr_pct_value"):
            self.assertNotIn(forbidden, kw)
        self.assertEqual(kw["reference_price"], Decimal("130"))
        # لكن الشادو سُجّل (حساب فقط).
        shadows = audit.events_of("dynamic_exit_shadow")
        self.assertEqual(len(shadows), 1)
        self.assertIn("adaptive_eff_sl_pct", shadows[0])
        self.assertIn("divergence_pct", shadows[0])
        self.assertEqual(shadows[0]["current_sl_pct"], 2.0)
        self.assertTrue(audit.events_of("dynamic_exit_atr"))

    def test_shadow_off_default_is_plain_no_records(self):
        rec, audit, tick = self._run(
            shadow=False, dynamic_exit=None, provider=lambda: 1.0)
        self.assertEqual(tick.event, "REPOSITIONED")
        kw = rec.calls[0]
        self.assertNotIn("dynamic_exit", kw)
        self.assertEqual(audit.events_of("dynamic_exit_shadow"), [])
        self.assertEqual(audit.events_of("dynamic_exit_atr"), [])

    def test_shadow_provider_failure_does_not_break_cycle(self):
        rec, audit, tick = self._run(
            shadow=True, dynamic_exit=DynamicExitConfig(enabled=False),
            provider=_BoomProvider())
        # رغم فشل المزوّد: الدورة تُنفَّذ (المسار الحالي) ولا استثناء.
        self.assertEqual(tick.event, "REPOSITIONED")
        self.assertEqual(len(rec.calls), 1)
        self.assertNotIn("dynamic_exit", rec.calls[0])


class TestShadowConfig(unittest.TestCase):
    def test_env_default_off(self):
        env = dict(os.environ)
        env.pop("OCOBOT_DYNAMIC_EXIT_SHADOW", None)
        saved = os.environ.get("OCOBOT_DYNAMIC_EXIT_SHADOW")
        try:
            os.environ.pop("OCOBOT_DYNAMIC_EXIT_SHADOW", None)
            cfg = AppConfig.from_env_vars()
            self.assertFalse(cfg.dynamic_exit_shadow)
        finally:
            if saved is not None:
                os.environ["OCOBOT_DYNAMIC_EXIT_SHADOW"] = saved

    def test_env_on(self):
        saved = os.environ.get("OCOBOT_DYNAMIC_EXIT_SHADOW")
        try:
            os.environ["OCOBOT_DYNAMIC_EXIT_SHADOW"] = "1"
            cfg = AppConfig.from_env_vars()
            self.assertTrue(cfg.dynamic_exit_shadow)
        finally:
            if saved is None:
                os.environ.pop("OCOBOT_DYNAMIC_EXIT_SHADOW", None)
            else:
                os.environ["OCOBOT_DYNAMIC_EXIT_SHADOW"] = saved


class TestCliShadowKwargs(unittest.TestCase):
    def test_shadow_only(self):
        cfg = AppConfig(dynamic_exit_enabled=False, dynamic_exit_shadow=True)
        kw = _dynamic_exit_kwargs(cfg, object(), "BTCUSDT")
        self.assertTrue(kw.get("shadow"))
        self.assertIn("dynamic_exit", kw)
        self.assertFalse(kw["dynamic_exit"].enabled)
        self.assertIn("live_atr_pct_provider", kw)

    def test_both_off_empty(self):
        cfg = AppConfig(dynamic_exit_enabled=False, dynamic_exit_shadow=False)
        self.assertEqual(_dynamic_exit_kwargs(cfg, object(), "BTCUSDT"), {})

    def test_enabled_has_no_shadow_key(self):
        cfg = AppConfig(dynamic_exit_enabled=True, dynamic_exit_shadow=False)
        kw = _dynamic_exit_kwargs(cfg, object(), "BTCUSDT")
        self.assertNotIn("shadow", kw)
        self.assertTrue(kw["dynamic_exit"].enabled)


if __name__ == "__main__":
    unittest.main()
