# -*- coding: utf-8 -*-
"""G1.53 chunk_1 — اختبارات المُجمِّع الخالص profitability_by_mode + قارئ telemetry.

يغطّي على مقطع تخليقي (بلا شبكة، بلا Qt، بلا قرص):
  - تجميع صفقتين من وضعين مختلفين وحساب n/win_rate/avg_return_pct/net_usd/expectancy
    بدقّة ``Decimal``.
  - صفقة بلا ربح متاح (profit=None): تُحتسب في n فقط ولا تدخل المتوسّطات.
  - إقصاء الصفقة المفتوحة (status == "live").
  - مقاييس telemetry (avg_slippage_pct/floor_rate) على السجلّات الحقيقية فقط
    مع إقصاء سجلّات dry_run.
  - extract_exit_executions يُعيد Decimal للحقول الرقمية ومنطقيًّا لـ
    reached_floor/dry_run، ويتجاهل الأحداث غير المطابقة.
  - المدخل الفارغ يُعيد قاموسًا فارغًا، وكل القيم من نوع Decimal.

قابل للتشغيل عبر: python -m unittest tests.test_g1_53_profitability
"""
import unittest
from decimal import Decimal

from ocobot.domain.completed_trades import CompletedTrade
from ocobot.domain.profitability import (
    ModeProfitability,
    extract_exit_executions,
    profitability_by_mode,
)


def _trade(mode, pct, usd, status="closed"):
    """يبني ``CompletedTrade`` تخليقيًّا بوضع/ربح معلومَين (الباقي قيم آمنة)."""
    return CompletedTrade(
        trade_key="k-%s-%s" % (mode, pct),
        symbol="LSKUSDT",
        reference_price=Decimal("100"),
        opened_at="2026-01-01T00:00:00+00:00",
        closed_at="2026-01-01T01:00:00+00:00",
        close_reason="",
        exit_price=Decimal("101"),
        side="SELL",
        quantity=Decimal("1"),
        profit_usd=(None if usd is None else Decimal(str(usd))),
        profit_pct=(None if pct is None else Decimal(str(pct))),
        profit_available=(pct is not None),
        status=status,
        exit_source=mode,
    )


def _exec(source, slippage, reached_floor, dry_run=False):
    """يبني سطر تدقيق ``exit_execution`` (قيم مُسلسَلة كنصوص كما في AuditLog)."""
    return {
        "event": "exit_execution",
        "details": {
            "source": source,
            "exit_side": "upper",
            "order_type": "LIMIT_IOC",
            "tif": "IOC",
            "slippage_pct": str(slippage),
            "band_pct": "0.2",
            "reached_floor": reached_floor,
            "floor_price": "92",
            "qty": "10",
            "dry_run": dry_run,
        },
    }


class ProfitabilityByModeTests(unittest.TestCase):
    def test_two_modes_metrics_exact_decimal(self):
        trades = [
            _trade("MONITORING", 2, 20),
            _trade("MONITORING", -1, -10),
            _trade("MONITORING", 4, 40),
            _trade("MONITORING", -3, -30),
            _trade("MANUAL_EXIT", 10, 100),
            _trade("MANUAL_EXIT", 0, 0),
        ]
        res = profitability_by_mode(trades)
        self.assertEqual(set(res.keys()), {"MONITORING", "MANUAL_EXIT"})

        m = res["MONITORING"]
        self.assertEqual(m.n, 4)
        self.assertEqual(m.win_rate, Decimal("50"))
        self.assertEqual(m.avg_return_pct, Decimal("0.5"))
        self.assertEqual(m.net_usd, Decimal("20"))
        self.assertEqual(m.expectancy, Decimal("5"))

        x = res["MANUAL_EXIT"]
        self.assertEqual(x.n, 2)
        self.assertEqual(x.win_rate, Decimal("50"))
        self.assertEqual(x.avg_return_pct, Decimal("5"))
        self.assertEqual(x.net_usd, Decimal("100"))
        self.assertEqual(x.expectancy, Decimal("50"))

    def test_unavailable_profit_counts_in_n_only(self):
        trades = [
            _trade("BTC_FOLLOW", 5, 50),
            _trade("BTC_FOLLOW", None, None),  # موقوفة بلا exit/ربح
        ]
        res = profitability_by_mode(trades)
        b = res["BTC_FOLLOW"]
        self.assertEqual(b.n, 2)                       # تُحتسب في n
        self.assertEqual(b.win_rate, Decimal("50"))    # 1 رابحة من 2
        self.assertEqual(b.avg_return_pct, Decimal("5"))  # mean على المتاح فقط
        self.assertEqual(b.net_usd, Decimal("50"))
        self.assertEqual(b.expectancy, Decimal("25"))  # net/n = 50/2

    def test_live_trade_excluded(self):
        trades = [
            _trade("MONITORING", 2, 20),
            _trade("MONITORING", 9, 90, status="live"),  # يُقصى
        ]
        res = profitability_by_mode(trades)
        self.assertEqual(res["MONITORING"].n, 1)
        self.assertEqual(res["MONITORING"].net_usd, Decimal("20"))

    def test_empty_input_returns_empty(self):
        self.assertEqual(profitability_by_mode([]), {})
        self.assertEqual(profitability_by_mode(None), {})

    def test_telemetry_real_only_excludes_dry_run(self):
        trades = [
            _trade("MONITORING", 2, 20),
            _trade("MONITORING", -1, -10),
            _trade("MONITORING", 4, 40),
            _trade("MONITORING", -3, -30),
            _trade("MANUAL_EXIT", 10, 100),
        ]
        records = [
            _exec("MONITORING", "0.1", False),
            _exec("MONITORING", "0.3", True),
            _exec("MONITORING", "0.2", False),
            _exec("MONITORING", "0.2", False),
            _exec("MONITORING", "9.9", True, dry_run=True),  # معاينة ⇒ تُقصى
        ]
        execs = extract_exit_executions(records)
        res = profitability_by_mode(trades, exit_executions=execs)

        m = res["MONITORING"]
        self.assertEqual(m.n_exec, 4)
        self.assertEqual(m.avg_slippage_pct, Decimal("0.2"))
        self.assertEqual(m.floor_rate, Decimal("25"))

        # وضع بلا telemetry ⇒ تبقى حقول التنفيذ None/0.
        x = res["MANUAL_EXIT"]
        self.assertEqual(x.n_exec, 0)
        self.assertIsNone(x.avg_slippage_pct)
        self.assertIsNone(x.floor_rate)

    def test_extract_exit_executions_decimal_and_bools(self):
        records = [
            {"event": "monitor_start", "details": {"foo": "bar"}},   # يُتجاهل
            _exec("MANUAL_EXIT", "0.5", "true", dry_run="false"),
            {"event": "exit_execution", "details": "corrupt"},        # تالف ⇒ يُتجاهل
        ]
        out = extract_exit_executions(records)
        self.assertEqual(len(out), 1)
        rec = out[0]
        self.assertEqual(rec["source"], "MANUAL_EXIT")
        self.assertIsInstance(rec["slippage_pct"], Decimal)
        self.assertEqual(rec["slippage_pct"], Decimal("0.5"))
        self.assertIsInstance(rec["band_pct"], Decimal)
        self.assertIs(rec["reached_floor"], True)
        self.assertIs(rec["dry_run"], False)

    def test_metric_value_types_are_decimal(self):
        res = profitability_by_mode([_trade("MONITORING", 2, 20)])
        m = res["MONITORING"]
        self.assertIsInstance(m, ModeProfitability)
        self.assertIsInstance(m.win_rate, Decimal)
        self.assertIsInstance(m.avg_return_pct, Decimal)
        self.assertIsInstance(m.net_usd, Decimal)
        self.assertIsInstance(m.expectancy, Decimal)


if __name__ == "__main__":
    unittest.main()
