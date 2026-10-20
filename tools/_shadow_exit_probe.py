# -*- coding: utf-8 -*-
"""G1.65 increment #5 — probe شادو-مود على بيانات Binance حقيقية (قراءة-فقط).

يُظهر ماذا كان الخروج التكيّف **سيفعل** على ATR٪ حيّ حقيقي مقابل الستوب الحالي —
عبر **نفس** دالة ``dynamic_exit.shadow_divergence`` التي يستعملها ``MonitoringEngine``
في شادو-مود. لا تفعيل علم، لا رأس مال، لا تنفيذ، لا مساس بأي سجلّ/حالة؛ مجرّد
نداء ``GET /api/v3/klines`` عام + حساب خالص. مفيد كدليل قبل أي live-forward.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ocobot.app_wiring import build_live_atr_pct_provider
from ocobot.domain.dynamic_exit import DynamicExitConfig, shadow_divergence
from ocobot.domain.klines import KlinesService

BASE = "https://data-api.binance.vision"  # marketDataBaseUrl
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
ATR_WIN = 10
CURRENT_SL_PCT = 2.0               # الستوب الثابت الحالي (خط الأساس) للمقارنة
RUN_UPS = [0.5, 1.0, 2.0, 3.0]     # نِسب ركضة القمّة% (g) لعرض تشديد الستوب التكيّف


class RealPublicClient:
    def __init__(self, base):
        self._base = base.rstrip("/")

    def public_request(self, method, path, params):
        url = f"{self._base}{path}?{urllib.parse.urlencode(list(params))}"
        req = urllib.request.Request(
            url, method=method, headers={"User-Agent": "ocobot-shadow-probe/1.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))


def main():
    svc = KlinesService(RealPublicClient(BASE))
    p = DynamicExitConfig(enabled=False).params()  # نفس بارامترات شادو (wadapt_tight/0.80)

    print("=== G1.65 shadow-mode probe (REAL data, read-only) ===")
    print(f"base_url={BASE}  current_sl={CURRENT_SL_PCT}%  atr_win={ATR_WIN}")

    ok = True
    for sym in SYMBOLS:
        provider = build_live_atr_pct_provider(svc, lambda s=sym: s, atr_win=ATR_WIN)
        atr = provider()
        candles = svc.get_candles(sym, interval="1m", limit=max(ATR_WIN + 5, 20))
        ref = float(candles[-1].close)
        prev_stop = ref * (1.0 - CURRENT_SL_PCT / 100.0)
        if atr <= 0.0:
            ok = False
        print(f"\n-- {sym}  last={ref:.4f}  liveATR%={atr:.6f} --")
        print(f"   {'runUp%':>7} {'trailDist%':>11} {'adaptEffSL%':>12} "
              f"{'divergence%':>12}")
        for g in RUN_UPS:
            peak = ref * (1.0 + g / 100.0)
            rec = shadow_divergence(ref, peak, prev_stop, atr, CURRENT_SL_PCT, p)
            print(f"   {g:>7.2f} {rec['trail_dist_pct']:>11.4f} "
                  f"{rec['adaptive_eff_sl_pct']:>12.4f} {rec['divergence_pct']:>12.4f}")

    print(f"\nRESULT: {'ALL symbols produced live ATR% > 0' if ok else 'SOME ATR% == 0 (investigate)'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
