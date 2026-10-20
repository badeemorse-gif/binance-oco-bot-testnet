# -*- coding: utf-8 -*-
"""G1.65 — تحقّق قراءة-فقط من مزوّد ATR٪ الحيّ على بيانات Binance حقيقية.

أداة تشخيص عابرة (read-only): لا تُفعّل أي علم (OCOBOT_DYNAMIC_EXIT)، لا رأس مال،
لا Live/testnet تنفيذي، ولا تمسّ أي سجلّ تجارب/حالة. تثبت ثلاثة أشياء على شموع 1m
حيّة حقيقية عبر **المسار الإنتاجي الفعلي** (KlinesService -> as_candles -> provider):
  (1) تطابق ثلاثي: دالة domain == إعادة تنفيذ مستقلة == ناتج المزوّد.
  (2) المزوّد يُنتج قيمة > 0 (أي لا يسقط صامتًا على fail-safe=0.0 في المسار السعيد).
  (3) عدد الشموع كافٍ (>= atr_win + 1).
"""
from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request

# اجعل جذر المستودع متاحًا للاستيراد بغضّ النظر عن مجلد التشغيل.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ocobot.app_wiring import build_live_atr_pct_provider
from ocobot.domain.dynamic_exit import live_atr_pct
from ocobot.domain.klines import KlinesService

BASE = "https://data-api.binance.vision"  # marketDataBaseUrl (بيئة Binance Public Market Data)
PRIMARY = "BTCUSDT"                                      # رمز التطابق الثلاثي الدقيق
SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"]   # رموز سائلة تمثيلية
BAD_SYMBOL = "NOTAREALSYMBOLZZZ"                         # لإثبات تصنيف fail-safe على شبكة حقيقية
ATR_WIN = 10
LIMIT = max(ATR_WIN + 5, 20)


class RealPublicClient:
    """عميل قراءة-فقط بأقلّ واجهة يتوقّعها KlinesService: public_request -> JSON list."""

    def __init__(self, base: str):
        self._base = base.rstrip("/")

    def public_request(self, method, path, params):
        qs = urllib.parse.urlencode(list(params))
        url = f"{self._base}{path}?{qs}"
        req = urllib.request.Request(
            url, method=method, headers={"User-Agent": "ocobot-verify/1.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))


def independent_atr_pct(highs, lows, closes, win, ref):
    """إعادة تنفيذ مستقلة لصيغة متوسّط المدى الحقيقي٪ (oracle مستقل عن كود المشروع)."""
    n = len(highs)
    if n == 0 or ref <= 0 or win <= 0:
        return 0.0
    k = n - 1
    start = max(1, k - win + 1)
    pc = closes[start - 1]
    s = 0.0
    c = 0
    for i in range(start, k + 1):
        tr = max(highs[i] - lows[i], abs(highs[i] - pc), abs(lows[i] - pc))
        s += tr
        c += 1
        pc = closes[i]
    return 0.0 if c == 0 else 100.0 * (s / c) / ref


class _Holder:
    """حامل رمز قابل للتبديل يُمرَّر كـ symbol_fn (بلا وسائط)."""

    def __init__(self):
        self.symbol = None

    def __call__(self):
        return self.symbol


def main():
    client = RealPublicClient(BASE)
    svc = KlinesService(client)
    holder = _Holder()
    events = []
    provider = build_live_atr_pct_provider(
        svc, holder, atr_win=ATR_WIN, observer=events.append)

    print("=== G1.65 live ATR% verification (REAL data, read-only) ===")
    print(f"base_url : {BASE}")

    # (1) تطابق ثلاثي دقيق على الرمز الأساسي (domain == مستقل == provider).
    holder.symbol = PRIMARY
    candles = svc.get_candles(PRIMARY, interval="1m", limit=LIMIT)
    highs = [c.high for c in candles]
    lows = [c.low for c in candles]
    closes = [c.close for c in candles]
    ref = closes[-1]
    v_domain = float(live_atr_pct(highs, lows, closes, ATR_WIN, ref))
    v_indep = independent_atr_pct(highs, lows, closes, ATR_WIN, ref)
    v_provider = provider()  # يعيد استخدام الـcache -> نفس الشموع
    parity = abs(v_domain - v_indep) < 1e-9 and abs(v_provider - v_domain) < 1e-9
    print("\n-- (1) 3-way parity on primary --")
    print(f"{PRIMARY}: domain={v_domain:.9f} indep={v_indep:.9f} "
          f"provider={v_provider:.9f} ref={ref}")

    # (2) مسار سعيد على رموز متعدّدة — كلها يجب أن تُنتج ATR% > 0.
    print("\n-- (2) multi-symbol happy path --")
    per_symbol = {}
    for sym in SYMBOLS:
        holder.symbol = sym
        per_symbol[sym] = provider()
        print(f"{sym:10s} ATR%={per_symbol[sym]:.6f}")

    # (3) حالات فشل على شبكة حقيقية — يجب أن تسقط على fail-safe مع تصنيف السبب.
    print("\n-- (3) failure modes --")
    holder.symbol = None
    r_nosym = provider()
    holder.symbol = BAD_SYMBOL
    r_bad = provider()
    print(f"no_symbol -> {r_nosym} ; {BAD_SYMBOL} -> {r_bad}")

    # (4) ملخّص العدّادات (observability — increment #4).
    stats = provider.stats
    print("\n-- (4) provider.stats --")
    print(f"calls={stats['calls']} ok={stats['ok']} failsafe={stats['failsafe']}")
    print(f"failsafe_by_reason={stats['failsafe_by_reason']}")
    print(f"last_value={stats['last_value']} last_reason={stats['last_reason']}")

    # تجميع أسباب كل رمز من سجلّ الأحداث (observer).
    reasons = {}
    for ev in events:
        reasons.setdefault(ev["symbol"], set()).add(ev["reason"])

    chk_parity = parity
    chk_nonzero = all(v > 0.0 for v in per_symbol.values())
    chk_real_ok = all(reasons.get(s) == {"ok"} for s in SYMBOLS)
    chk_nosym = (r_nosym == 0.0 and reasons.get(None) == {"no_symbol"})
    chk_bad = (r_bad == 0.0 and bool(
        {"exception", "empty_candles", "zero_value"} & reasons.get(BAD_SYMBOL, set())))

    print("\n--- checks ---")
    print(f"[{'PASS' if chk_parity else 'FAIL'}] 3-way parity on {PRIMARY}")
    print(f"[{'PASS' if chk_nonzero else 'FAIL'}] all real symbols ATR% > 0 (no silent fail-safe)")
    print(f"[{'PASS' if chk_real_ok else 'FAIL'}] real symbols classified 'ok' only")
    print(f"[{'PASS' if chk_nosym else 'FAIL'}] no_symbol -> 0.0 classified 'no_symbol'")
    print(f"[{'PASS' if chk_bad else 'FAIL'}] bad symbol -> 0.0 classified fail-safe")

    ok = all([chk_parity, chk_nonzero, chk_real_ok, chk_nosym, chk_bad])
    print(f"\nRESULT: {'ALL PASS' if ok else 'FAIL'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
