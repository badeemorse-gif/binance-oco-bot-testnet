"""CLI معايرة/Backtest Walk-Forward لمُرشِّح النِّسب (G1.56 · c8).

غلاف رفيع حول ocobot.domain.backtest.walk_forward: يجلب الشموع عبر مزوّد
(``candles_provider``) ثم يطبع المقاييس JSON. المزوّد قابل للحقن حتى تعمل
الاختبارات بلا شبكة؛ المزوّد الافتراضي يتطلّب تمريرًا صريحًا (لا شبكة ضمنية هنا).
"""
from __future__ import annotations

import argparse
import json
from typing import Callable, List, Optional

from ocobot.core.errors import OcoBotError
from ocobot.domain.backtest import walk_forward
from ocobot.domain.volatility import Candle


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ocobot-backtest",
        description="معايرة/Backtest Walk-Forward لمُرشِّح النِّسب (G1.56).")
    p.add_argument("--symbol", required=True)
    p.add_argument("--interval", default="1h")
    p.add_argument("--limit", type=int, default=500)
    p.add_argument("--train", type=int, default=200)
    p.add_argument("--test", type=int, default=50)
    p.add_argument("--horizon", type=int, default=12)
    p.add_argument("--side", default="long", choices=["long", "short"])
    p.add_argument("--step", type=int, default=1)
    p.add_argument("--baseline-tp", type=float, default=None)
    p.add_argument("--baseline-sl", type=float, default=None)
    return p


def run(candles: List[Candle], args) -> dict:
    """يشغّل Walk-Forward على شموع مُعطاة ويُعيد قاموس المقاييس."""
    baseline = None
    if args.baseline_tp is not None and args.baseline_sl is not None:
        baseline = (args.baseline_tp, args.baseline_sl)
    result = walk_forward(
        candles, train_size=args.train, test_size=args.test,
        horizon=args.horizon, side=args.side, step=args.step, baseline=baseline)
    return result.to_dict()


def _default_provider(symbol: str, interval: str, limit: int):
    raise OcoBotError(
        "لا مزوّد شموع: مرّر candles_provider (الواجهة/الرَنَر توفّره)؛ "
        "لا شبكة ضمنية في هذا الـCLI.")


def main(argv: Optional[list] = None,
         candles_provider: Optional[Callable[[str, str, int], List[Candle]]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    provider = candles_provider or _default_provider
    candles = provider(args.symbol, args.interval, args.limit)
    print(json.dumps(run(candles, args), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
