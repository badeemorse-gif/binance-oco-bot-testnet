"""خروج يدوي فوري بأفضل سعر لحظي بأولوية عُليا (G1.47) — وحدة إضافية بحتة.

Immediate manual market-exit wiring (one-shot). This module is **purely additive**
and stays entirely out of the hot path:
  - لا تمسّ ولا تستورد ``on_price_tick`` / ``SafeExecutor.execute`` / ``reposition`` /
    ``create_oco`` / ``MonitoringEngine`` internals؛ ولا منفّذ ستوب واقٍ.
  - تُعيد استخدام مسار الخروج المُختبَر ``domain.market_exit.execute_market_exit``
    **حصريًّا** (قرار ``g1_47_manual_exit_safety``)، مسبوقًا ببوّابة التنفيذ الآمن
    ``ui.safe_execution.manual_exit_safety_gate`` (قيد منع البيع المزدوج البنيوي).
  - الأولوية العُليا **بنيوية**: بمجرّد وضع أمر الخروج يُغلق المركز (أو يوجد بيع حمائي
    قائم) فتصبح الوسائل الأربع (الحارس/btc-follow/إعادة التموضع/البراكِت) idempotent
    بلا فعل — لا سباق منفّذات ولا كسر لـ no-cancel-invariant.
  - الإلغاء هنا جزء من مسار ``execute_market_exit`` المبدوء بأمر المستخدم (ليس من
    منفّذ الستوب الواقي)، فيبقى no-cancel-invariant سليمًا.

Testnet فقط ضمن G1؛ ممنوع أيّ Live/T16 قبل بوّابة G1 (§10.5). ``dry_run`` افتراضيًّا
``True`` في ``run_manual_market_exit`` (لا أثر)؛ محوّل الواجهة يبني الـ callable
بـ ``dry_run=False`` للتنفيذ الفعلي على Testnet عند ضغط المستخدم.
"""
from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from ocobot.domain.market_exit import execute_market_exit, execute_exit_chase
from .safe_execution import manual_exit_safety_gate

_ZERO = Decimal("0")


def default_manual_exit_cid() -> str:
    """مُعرّف أمر عميل (<=36 حرفًا، Binance-safe) للخروج اليدوي."""
    return "mex-%s" % uuid4().hex[:20]


def run_manual_market_exit(
    *,
    client,
    symbol,
    base_asset,
    free_base_qty,
    monitored_qty,
    has_resting_protective_sell,
    reference_price,
    filters,
    exit_side="upper",
    client_order_id=None,
    order_list_id=None,
    kill_switch=None,
    notifier=None,
    dry_run=True,
    emergency_sl_pct=None,
    price_floor_pct=None,
    slip_pct=None,
    gap_ticks=None,
    allow_market=False,
    bid_getter=None,
    policy=None,
    chase_interval_s=None,
    sleeper=None,
    exit_source_noter=None,
):
    """ينفّذ الخروج اليدوي الأحادي: البوّابة أولًا ثم مسار الخروج المُختبَر.

    1) ``manual_exit_safety_gate`` (قيد منع البيع المزدوج). إن منعت ⇒
       ``{action: "ABORT_GATE", ...}`` بلا أي استدعاء للمنفّذ (لا بيع ثانٍ).
    2) ``execute_market_exit`` على ``target_qty = protective_qty`` المحسوبة من
       البوّابة؛ وهو بدوره يُعيد reconcile قبل الوضع (حماية مزدوجة). وضع واحد فقط.

    ``dry_run=True`` (الافتراضي) ⇒ معاينة خالصة بلا أثر (لا Live). يُعيد نفس قاموس
    نتيجة ``execute_market_exit`` أو قاموس ``ABORT_GATE``.
    """
    gate = manual_exit_safety_gate(
        has_resting_protective_sell=has_resting_protective_sell,
        free_base_qty=free_base_qty,
        monitored_qty=monitored_qty,
    )
    if not gate["allowed"]:
        return {
            "action": "ABORT_GATE",
            "placed": False,
            "reason": gate["reason"],
            "symbol": symbol,
            "exit_side": exit_side,
            "gate": gate,
        }

    # G1.52: وسم مصدر الخروج (MANUAL_EXIT) لحظة الإطلاق الفعلي — opt-in محروس.
    # default None ⇒ لا أثر؛ وفي dry_run (معاينة) لا نُسجّل لأنه لا خروج فعلي.
    if exit_source_noter is not None and not dry_run:
        try:
            exit_source_noter("MANUAL_EXIT")
        except Exception:
            pass

    cid = client_order_id or default_manual_exit_cid()
    if bid_getter is not None:
        # G1.49: المسار الموحّد — chase نازل IOC على BID حيّ (لا تعليق). opt-in عبر bid_getter.
        return execute_exit_chase(
            client=client,
            symbol=symbol,
            base_asset=base_asset or "",
            bid_getter=bid_getter,
            target_qty=gate["protective_qty"],
            filters=filters,
            client_order_id=cid,
            exit_side=exit_side,
            policy=policy,
            order_list_id=order_list_id,
            kill_switch=kill_switch,
            notifier=notifier,
            sleeper=sleeper,
            chase_interval_s=chase_interval_s,
            dry_run=dry_run,
        )
    return execute_market_exit(
        client=client,
        symbol=symbol,
        base_asset=base_asset or "",
        exit_side=exit_side,
        reference_price=reference_price,
        target_qty=gate["protective_qty"],
        filters=filters,
        client_order_id=cid,
        order_list_id=order_list_id,
        kill_switch=kill_switch,
        notifier=notifier,
        emergency_sl_pct=emergency_sl_pct,
        price_floor_pct=price_floor_pct,
        slip_pct=slip_pct,
        gap_ticks=gap_ticks,
        allow_market=allow_market,
        dry_run=dry_run,
    )


def build_manual_exit_fn(
    *,
    exit_broker,
    state_provider=None,
    selected_provider=None,
    filters_fn=None,
    base_asset_fn=None,
    kill_switch_getter=None,
    notifier_getter=None,
    exit_side="upper",
    dry_run=False,
    price_getter=None,
    policy=None,
    chase_interval_s=None,
    sleeper=None,
    exit_source_noter=None,
):
    """يبني ``callable`` أحاديًا بلا وسائط لزرّ «تنفيذ» في شاشة المراقبة.

    يقرأ الحالة/المختار وقت النداء (ربط متأخّر)، ثم يجمع مُدخلات البوّابة من
    ``exit_broker`` (الرصيد الحرّ + وجود بيع حمائي قائم) ويستدعي
    ``run_manual_market_exit``. يعمل على خيط الرَنَر (لا شبكة في طبقة الواجهة).

    fail-safe: أي استثناء ⇒ ``{action: "ERROR", ...}`` (لا يرمي إلى الواجهة).
    """

    def manual_exit_fn():
        try:
            state = state_provider() if callable(state_provider) else state_provider
            selected = None
            if selected_provider is not None:
                selected = selected_provider() if callable(selected_provider) else selected_provider
            if selected is None and state is not None:
                selected = getattr(state, "selected_oco", None)

            symbol = getattr(selected, "symbol", None) or getattr(state, "symbol", None)
            if not symbol:
                # G1.63: أشعِر حتى عند عدم وجود تحديد (مسار مبكِّر لا يمرّ بالمنفّذ).
                _res_ns = {"action": "ABORT_NO_SELECTION", "placed": False}
                try:
                    _n = notifier_getter() if callable(notifier_getter) else None
                    if callable(_n):
                        _n(_res_ns)
                except Exception:
                    pass
                return _res_ns

            base_asset = base_asset_fn(symbol) if callable(base_asset_fn) else None
            reference_price = (
                getattr(state, "reference_price", None)
                or getattr(state, "last_price", None)
                or getattr(selected, "current_price", None)
            )
            monitored_qty = getattr(selected, "quantity", None)
            if monitored_qty is None:
                monitored_qty = _ZERO
            filters = filters_fn(symbol) if callable(filters_fn) else None
            order_list_id = getattr(state, "target_order_list_id", None)
            if order_list_id is None:
                order_list_id = getattr(selected, "order_list_id", None)
            kill_switch = kill_switch_getter() if callable(kill_switch_getter) else None
            notifier = notifier_getter() if callable(notifier_getter) else None

            # مُدخلات البوّابة: الرصيد الحرّ + وجود بيع حمائي قائم (reconcile مسبق).
            free_base_qty = _ZERO
            if base_asset:
                free_base_qty = exit_broker.get_free_asset_qty(base_asset)
            resting = exit_broker.get_open_sell_orders(symbol)
            has_resting = bool(resting)

            result = run_manual_market_exit(
                client=exit_broker,
                symbol=symbol,
                base_asset=base_asset,
                free_base_qty=free_base_qty,
                monitored_qty=monitored_qty,
                has_resting_protective_sell=has_resting,
                reference_price=reference_price,
                filters=filters,
                exit_side=exit_side,
                order_list_id=order_list_id,
                kill_switch=kill_switch,
                notifier=notifier,
                bid_getter=(price_getter if callable(price_getter) else None),
                policy=policy,
                chase_interval_s=chase_interval_s,
                sleeper=sleeper,
                dry_run=dry_run,
                exit_source_noter=exit_source_noter,
            )
            # G1.63: ضمان إشعار عند كل ضغط. execute_market_exit يُطلِق notifier على
            #        PLACED فقط؛ هنا نُطلِقه لغير المنفَّذ (abort/gate/error) حتى لا يبقى
            #        الضغط صامتًا. مسار chase (bid_getter) يُطلِق لكل النتائج داخليًا ⇒
            #        لا نُكرِّر عندما يكون price_getter مُفعّلًا.
            try:
                if (callable(notifier) and not callable(price_getter)
                        and isinstance(result, dict)
                        and result.get("placed") is not True):
                    notifier(result)
            except Exception:
                pass
            return result
        except Exception as exc:  # fail-safe: لا يرمي إلى الواجهة
            # G1.63: أشعِر حتى عند الخطأ غير المتوقّع (لا يبقى الضغط صامتًا).
            _res_err = {"action": "ERROR", "placed": False, "error": str(exc)}
            try:
                _n = notifier_getter() if callable(notifier_getter) else None
                if callable(_n):
                    _n(_res_err)
            except Exception:
                pass
            return _res_err

    return manual_exit_fn
