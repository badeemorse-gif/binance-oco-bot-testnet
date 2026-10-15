# -*- coding: utf-8 -*-
"""اختبارات G1.56 · c8 — Backtest/Walk-Forward (backtest.py) + CLI."""
import io
import unittest
from contextlib import redirect_stdout

from ocobot.core.errors import OcoBotError
from ocobot.domain import backtest as bt
from ocobot.domain.volatility import Candle
from ocobot import cli_backtest


def _uptrend(n):
    return [Candle(100 + i, 100 + i + 0.8, 100 + i - 0.3, 100 + i + 0.5)
            for i in range(n)]


class SimulateTradeTests(unittest.TestCase):
    def test_tp_hit_early_exit(self):
        tr = bt.simulate_trade(100, [101, 103, 106], [99.5, 100, 102],
                               [100.5, 102, 105], tp_pct=1, sl_pct=1, side="long")
        self.assertEqual(tr.exit_reason, "tp")
        self.assertAlmostEqual(tr.outcome_pct, 1.0, places=9)
        self.assertAlmostEqual(tr.potential_mfe_pct, 6.0, places=9)
        self.assertTrue(tr.early_exit)
        self.assertAlmostEqual(tr.mfe_capture, 1.0 / 6.0, places=9)

    def test_tp_hit_full_capture(self):
        tr = bt.simulate_trade(100, [101, 103, 106], [99.5, 100, 102],
                               [100.5, 102, 105], tp_pct=6, sl_pct=3, side="long")
        self.assertEqual(tr.exit_reason, "tp")
        self.assertFalse(tr.early_exit)
        self.assertAlmostEqual(tr.mfe_capture, 1.0, places=9)

    def test_sl_hit(self):
        tr = bt.simulate_trade(100, [100.5, 100.5], [98, 99], [99, 99],
                               tp_pct=5, sl_pct=1, side="long")
        self.assertEqual(tr.exit_reason, "sl")
        self.assertAlmostEqual(tr.outcome_pct, -1.0, places=9)
        self.assertEqual(tr.captured_favorable_pct, 0.0)

    def test_time_exit(self):
        tr = bt.simulate_trade(100, [100.2, 100.3], [99.8, 99.9], [100.1, 100.2],
                               tp_pct=5, sl_pct=5, side="long")
        self.assertEqual(tr.exit_reason, "time")
        self.assertAlmostEqual(tr.outcome_pct, 0.2, places=9)

    def test_guards(self):
        self.assertIsNone(bt.simulate_trade(0, [1], [1], [1], 1, 1))
        self.assertIsNone(bt.simulate_trade(100, [], [], [], 1, 1))


class PolicyComparisonTests(unittest.TestCase):
    def test_wide_beats_tight_on_uptrend(self):
        candles = _uptrend(40)
        tight = bt.evaluate_policy(candles, tp_pct=1, sl_pct=1, horizon=10, step=3)
        wide = bt.evaluate_policy(candles, tp_pct=6, sl_pct=3, horizon=10, step=3)
        self.assertGreater(tight.n_trades, 0)
        self.assertGreater(tight.early_exit_rate, wide.early_exit_rate)
        self.assertGreater(wide.avg_mfe_capture, tight.avg_mfe_capture)

    def test_metrics_empty(self):
        m = bt.metrics_from_trades([])
        self.assertEqual(m.n_trades, 0)
        self.assertIsNone(m.early_exit_rate)

    def test_collect_validation(self):
        with self.assertRaises(ValueError):
            bt.collect_trades(_uptrend(10), 1, 1, horizon=0)


class WalkForwardTests(unittest.TestCase):
    def test_structure_and_recommended_not_worse(self):
        candles = _uptrend(90)
        res = bt.walk_forward(candles, train_size=30, test_size=20, horizon=10,
                              step=3, baseline=(1.0, 1.0))
        self.assertGreaterEqual(res.folds, 1)
        self.assertGreater(res.recommended.n_trades, 0)
        self.assertIsNotNone(res.baseline)
        # الاقتراح لا يخرج مبكرًا أكثر من خطّ الأساس الضيّق على اتجاه صاعد
        self.assertLessEqual(res.recommended.early_exit_rate,
                             res.baseline.early_exit_rate)
        d = res.to_dict()
        self.assertIn("recommended", d)
        self.assertIn("folds", d)

    def test_validation(self):
        with self.assertRaises(ValueError):
            bt.walk_forward(_uptrend(50), train_size=0, test_size=10, horizon=5)


class CliTests(unittest.TestCase):
    def test_run_returns_metrics(self):
        args = cli_backtest.build_arg_parser().parse_args(
            ["--symbol", "BTCUSDT", "--train", "30", "--test", "20",
             "--horizon", "10", "--step", "3", "--baseline-tp", "1",
             "--baseline-sl", "1"])
        d = cli_backtest.run(_uptrend(90), args)
        self.assertIn("recommended", d)
        self.assertGreaterEqual(d["folds"], 1)

    def test_main_with_stub_provider(self):
        calls = {}

        def provider(symbol, interval, limit):
            calls["args"] = (symbol, interval, limit)
            return _uptrend(90)

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli_backtest.main(
                ["--symbol", "ETHUSDT", "--interval", "4h", "--limit", "90",
                 "--train", "30", "--test", "20", "--horizon", "10"],
                candles_provider=provider)
        self.assertEqual(rc, 0)
        self.assertEqual(calls["args"], ("ETHUSDT", "4h", 90))
        self.assertIn("recommended", buf.getvalue())

    def test_default_provider_raises(self):
        with self.assertRaises(OcoBotError):
            cli_backtest.main(["--symbol", "BTCUSDT"])


if __name__ == "__main__":
    unittest.main()
