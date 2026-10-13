"""ربط قوس الخروج بالمُنفّذ (Bracket Exit Wiring) — G1.32b / chunk_2.

إضافيّ بحت خارج المسار الحار: يبني ``BracketMonitor`` فوق منفّذ الخروج المعزول
(``execute_market_exit`` من G1.32a) + ``MarketExitBroker``، ويوفّر ``tick()`` يقرأ
السعر الحيّ وإعداد القوس من الواجهة ويفحص لمس الحدّين؛ عند اللمس يستدعي الخروج
**مرّة واحدة** (latch في ``BracketMonitor``) منسّقًا مع الحارس (بعد الخروج الرصيد
صفر ⇒ الحارس NOOP).

كل التبعيات محقونة (DI) فتبقى الوحدة قابلة للاختبار بلا أيّ شبكة. المفتاح مطفأ
افتراضيًّا ⇒ ``tick()`` بلا أثر. لا يلمس hot_path ولا reposition ولا المختوم.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable, Dict, Optional

from ocobot.domain.bracket import BracketMonitor
from ocobot.domain.market_exit import execute_market_exit

log = logging.getLogger(__name__)


class BracketExitWiring:
    def __init__(self, *, broker, config_getter: Callable, price_getter: Callable,
                 selected_getter: Callable, filters_fn: Callable, base_asset_fn: Callable,
                 dry_run_getter: Optional[Callable] = None,
                 kill_switch_getter: Optional[Callable] = None,
                 on_event: Optional[Callable] = None,
                 notifier: Optional[Callable] = None,
                 exit_source_noter: Optional[Callable] = None):
        self._broker = broker
        self._config_getter = config_getter
        self._price_getter = price_getter
        self._selected_getter = selected_getter
        self._filters_fn = filters_fn
        self._base_asset_fn = base_asset_fn
        self._dry_run_getter = dry_run_getter
        self._kill_switch_getter = kill_switch_getter
        # G1.37 (emit-only): مُطلِق تنبيه الخروج الفعلي؛ يُمرَّر إلى
        #        execute_market_exit الذي يستدعي notifier(result) على PLACED فقط.
        self._notifier = notifier
        # G1.46: مُطلِق وسم مصدر الخروج (PRICE_BRACKET) — إضافة بحتة محروسة.
        self._exit_source_noter = exit_source_noter
        # G1.49 chunk_4b: ترسية الخروج على أفضل BID حيّ لحظة الإطلاق (``bid_getter``)
        # لا على سعر tick الاختراق — يُزيل «الأمر فوق السوق» المُبلَّغ عنه. مع
        # wick-debounce (chunk_3) ⇒ لا لمس كاذب ولا تعليق.
        self.monitor = BracketMonitor(
            exit_executor=self._exit, config_getter=config_getter, on_event=on_event,
            bid_getter=price_getter,
        )
        self.last_tick = None

    @staticmethod
    def _field(sel, *names, default=None):
        for n in names:
            v = getattr(sel, n, None)
            if v is None and isinstance(sel, dict):
                v = sel.get(n)
            if v is not None:
                return v
        return default

    def _exit(self, exit_side, price) -> Dict[str, Any]:
        sel = self._selected_getter() if self._selected_getter else None
        if sel is None:
            return {"action": "NO_SELECTION"}
        symbol = self._field(sel, "symbol")
        if not symbol:
            return {"action": "NO_SYMBOL"}
        order_list_id = self._field(sel, "order_list_id", "orderListId")
        target_qty = self._field(sel, "quantity", "orig_qty", "qty", default=0)
        filters = self._filters_fn(symbol) if self._filters_fn else None
        base_asset = self._base_asset_fn(symbol) if self._base_asset_fn else None
        if filters is None or base_asset is None:
            return {"action": "NO_FILTERS_OR_ASSET"}
        dry_run = True
        if self._dry_run_getter is not None:
            try:
                dry_run = bool(self._dry_run_getter())
            except Exception:  # pragma: no cover - دفاعي
                dry_run = True
        kill_switch = None
        if self._kill_switch_getter is not None:
            try:
                kill_switch = self._kill_switch_getter()
            except Exception:  # pragma: no cover - دفاعي
                kill_switch = None
        # G1.33: نِسب التسعير القابلة للتعديل من الواجهة (الفارغ ⇒ الافتراضي القديم).
        pricing = {}
        try:
            cfg = self._config_getter() if self._config_getter else None
            if cfg is not None and hasattr(cfg, "pricing_kwargs"):
                pricing = cfg.pricing_kwargs() or {}
        except Exception:  # pragma: no cover - دفاعي
            pricing = {}
        coid = "bexit-%s-%d" % (exit_side, int(time.time()))
        # G1.46: وسم مصدر الخروج (قوس الخروج بالسعر) قبل التنفيذ — إضافة بحتة محروسة.
        if self._exit_source_noter is not None:
            try:
                self._exit_source_noter("PRICE_BRACKET")
            except Exception:  # pragma: no cover - دفاعي
                pass
        return execute_market_exit(
            client=self._broker, symbol=symbol, base_asset=base_asset,
            exit_side=exit_side, reference_price=price, target_qty=target_qty,
            filters=filters, client_order_id=coid, order_list_id=order_list_id,
            kill_switch=kill_switch, notifier=self._notifier, dry_run=dry_run, **pricing,
        )

    def tick(self) -> Dict[str, Any]:
        try:
            price = self._price_getter() if self._price_getter else None
        except Exception:  # pragma: no cover - دفاعي
            price = None
        self.last_tick = self.monitor.check(price)
        return self.last_tick
