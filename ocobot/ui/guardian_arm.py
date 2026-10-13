"""مِحور تسليح شبكة أمان المركز (Guardian Arming) — G1.30 / chunk_5 enabler.

هذه الوحدة **إضافية بحتة** وخارج المسار الحار تمامًا:
  - لا تمسّ ولا تستورد ``on_price_tick`` / ``MonitoringEngine.start`` /
    ``SafeExecutor.execute`` / ``create_oco`` / أي منطق تسعير/تموضع.
  - **مُطفأة افتراضيًّا**: لا تبني أي ``GuardianSupervisor`` إلا إذا ضُبط متغيّر
    البيئة ``OCOBOT_GUARDIAN`` على ``observe`` أو ``live``؛ فيبقى سلوك التطبيق
    العادي (بلا المتغيّر) مطابقًا تمامًا.

الأوضاع عبر ``OCOBOT_GUARDIAN``:
  - غير مضبوط / ``off`` ⇒ لا تسليح (يُعاد ``None``).
  - ``observe`` ⇒ ``dry_run=True`` (يكتشف ويُخطّط ويوقف المراقبة ويُنبّه، **بلا وضع
    أمر فعلي**).
  - ``live``    ⇒ ``dry_run=False`` (يضع وقفًا حمائيًّا واحدًا فعليًّا على Testnet).

تجاوزات اختيارية: ``OCOBOT_GUARDIAN_SL_PCT`` و ``OCOBOT_GUARDIAN_THRESHOLD``.

مشكلة «ما قبل الاتصال»: التسليح يحدث في ``app.main()`` قبل أن يتّصل المستخدم عبر
الواجهة (مفاتيح الجلسة تُضبط عند الاتصال). لذلك العميل يُبنى **lazy** عند كل نداء
عبر ``build_gui_client(AppConfig.from_env_vars())``، ويُعيد قيمًا آمنة إن لم يتّصل
بعد. وبالمثل تُقرأ النافذة الحيّة (محرّك شاشة 04 + نظام alerts) عبر ``window_getter``
وقت التشغيل (ربط متأخّر).
"""
from __future__ import annotations

import logging
import os
from decimal import Decimal, InvalidOperation
from types import SimpleNamespace
from ocobot.core.guardian_lazy_client import LazyGuardianRestClient

log = logging.getLogger(__name__)


def _mode() -> str:
    return (os.environ.get("OCOBOT_GUARDIAN") or "off").strip().lower()


def _build_config():
    from ocobot.domain.guardian import GuardianConfig

    kwargs = {}
    sl = os.environ.get("OCOBOT_GUARDIAN_SL_PCT")
    if sl:
        try:
            kwargs["emergency_sl_pct"] = Decimal(str(sl))
        except (InvalidOperation, ValueError):
            log.warning("OCOBOT_GUARDIAN_SL_PCT غير صالح: %s — سيُستعمل الافتراضي.", sl)
    th = os.environ.get("OCOBOT_GUARDIAN_THRESHOLD")
    if th:
        try:
            kwargs["threshold_seconds"] = float(th)
        except ValueError:
            log.warning("OCOBOT_GUARDIAN_THRESHOLD غير صالح: %s — سيُستعمل الافتراضي.", th)
    return GuardianConfig(**kwargs)


def build_guardian_supervisor(window_getter):
    """يبني ``GuardianSupervisor`` إن كان ``OCOBOT_GUARDIAN`` مفعّلًا، وإلا ``None``.

    ``window_getter``: ``callable`` يُعيد النافذة الحيّة (أو ``None``) — يُستعمل
    لقراءة محرّك شاشة ``04_dynamic_monitoring`` ونظام ``alerts`` وقت التشغيل
    (ربط متأخّر، فالنافذة تُبنى بعد هذا النداء).
    """
    mode = _mode()
    if mode not in ("observe", "live"):
        return None
    dry_run = mode != "live"

    from ocobot.core.guardian_broker import GuardianBroker, base_asset_of
    from ocobot.domain.exchange_info import ExchangeInfoService
    from ocobot.domain.guardian_supervisor import GuardianSupervisor
    from ocobot.domain.pricing import DEFAULT_GAP_TICKS

    lazy_client = LazyGuardianRestClient()
    broker = GuardianBroker(lazy_client)
    exchange_info = ExchangeInfoService(lazy_client)

    def base_asset_fn(symbol):
        try:
            return base_asset_of(symbol, exchange_info)
        except Exception:
            try:
                return base_asset_of(symbol)
            except Exception:
                return None

    def filters_fn(symbol):
        try:
            f = exchange_info.get_filters(symbol)
            if f is None:
                return None
            return SimpleNamespace(
                symbol=getattr(f, "symbol", symbol),
                tick_size=getattr(f, "tick_size", None),
                step_size=getattr(f, "step_size", None),
                gap_ticks=DEFAULT_GAP_TICKS,
            )
        except Exception:
            log.warning("تعذّر جلب فلاتر %s للحارس — سيُتخطّى التدخّل بأمان (NOOP).", symbol)
            return None

    def state_provider():
        w = window_getter()
        if w is None:
            return None
        try:
            screen = w.content.screen_for("04_dynamic_monitoring")
            return getattr(screen, "_engine", None) if screen is not None else None
        except Exception:
            return None

    def alert_cb(text):
        try:
            w = window_getter()
            notifier = getattr(w, "_alerts_notifier", None) if w is not None else None
            if notifier is not None and hasattr(notifier, "enqueue"):
                try:
                    from ocobot.alerts.formatting import escape_mdv2

                    notifier.enqueue(escape_mdv2(text))
                    return
                except Exception:
                    pass
            log.warning("GUARDIAN ALERT: %s", text)
        except Exception:
            pass

    supervisor = GuardianSupervisor(
        state_provider=state_provider,
        client=broker,
        alert_cb=alert_cb,
        config=_build_config(),
        dry_run=dry_run,
        base_asset_fn=base_asset_fn,
        filters_fn=filters_fn,
    )
    log.info("Guardian armed: mode=%s dry_run=%s", mode, dry_run)
    return supervisor

# === G1.31 / chunk_5a: مسار إضافي لتسليح الحارس وقت التشغيل من الواجهة (لا يمسّ المختوم أعلاه) ===

def _build_supervisor_core(window_getter, dry_run):
    """بناء GuardianSupervisor مُهيّأ (بلا بوّابة بيئة) — نسخة مستقلّة للمسار الإضافي.

    لا تمسّ build_guardian_supervisor المختوم (G1.30). خاملة: LazyGuardianRestClient
    لا يتّصل عند الإنشاء؛ المُشرِف لا يتدخّل إلا عند tick() الذي يقوده محوّل الواجهة.
    """
    from ocobot.core.guardian_broker import GuardianBroker, base_asset_of
    from ocobot.domain.exchange_info import ExchangeInfoService
    from ocobot.domain.guardian_supervisor import GuardianSupervisor
    from ocobot.domain.pricing import DEFAULT_GAP_TICKS

    lazy_client = LazyGuardianRestClient()
    broker = GuardianBroker(lazy_client)
    exchange_info = ExchangeInfoService(lazy_client)

    def base_asset_fn(symbol):
        try:
            return base_asset_of(symbol, exchange_info)
        except Exception:
            try:
                return base_asset_of(symbol)
            except Exception:
                return None

    def filters_fn(symbol):
        try:
            f = exchange_info.get_filters(symbol)
            if f is None:
                return None
            return SimpleNamespace(
                symbol=getattr(f, "symbol", symbol),
                tick_size=getattr(f, "tick_size", None),
                step_size=getattr(f, "step_size", None),
                gap_ticks=DEFAULT_GAP_TICKS,
            )
        except Exception:
            log.warning("تعذّر جلب فلاتر %s للحارس — سيُتخطّى التدخّل بأمان (NOOP).", symbol)
            return None

    def state_provider():
        w = window_getter()
        if w is None:
            return None
        try:
            screen = w.content.screen_for("04_dynamic_monitoring")
            return getattr(screen, "_engine", None) if screen is not None else None
        except Exception:
            return None

    def alert_cb(text):
        try:
            w = window_getter()
            notifier = getattr(w, "_alerts_notifier", None) if w is not None else None
            if notifier is not None and hasattr(notifier, "enqueue"):
                try:
                    from ocobot.alerts.formatting import escape_mdv2

                    notifier.enqueue(escape_mdv2(text))
                    return
                except Exception:
                    pass
            log.warning("GUARDIAN ALERT: %s", text)
        except Exception:
            pass

    # === G1.44 / chunk_4: بناء وحقن تبعيات حارس هبوط BTC (إضافيّ، لا يمسّ المختوم) ===
    # BtcFollowSupervisor مُفعَّل (enabled=True) لكن تشغيله الفعلي محكوم حصريًّا
    # بـ set_btc_runtime عبر محوّل الواجهة (الافتراضي OFF ⇒ NOOP تامّ، لا شبكة).
    from ocobot.core.market_exit_broker import MarketExitBroker
    from ocobot.domain.btc_follow import BtcFollowConfig
    from ocobot.domain.btc_follow_supervisor import BtcFollowSupervisor
    from ocobot.domain.market_exit import execute_market_exit

    # محوّل خروج يحقّق MarketExitClient فوق نفس العميل الكسول (لا شبكة عند الإنشاء).
    exit_broker = MarketExitBroker(lazy_client)

    def _btc_price_fn():
        """سحب سعر BTCUSDT الحالي من تغذية النافذة بأمان؛ None إن تعذّر (fail-safe).

        لا شبكة في طبقة الواجهة: نقرأ موفّر السعر المحقون من شاشة 04 إن توفّر؛
        وإلا نُعيد None فيبقى حارس BTC بلا عيّنات ⇒ NOOP.
        """
        try:
            w = window_getter()
            if w is None:
                return None
            screen = w.content.screen_for("04_dynamic_monitoring")
            if screen is None:
                return None
            provider = getattr(screen, "_btc_price_provider", None)
            if provider is None:
                return None
            price = provider() if callable(provider) else None
            return price
        except Exception:
            return None

    btc_follow = BtcFollowSupervisor(
        config=BtcFollowConfig(enabled=True),
        price_fn=_btc_price_fn,
    )

    def btc_exit_fn(symbol, base_asset, btc_decision, state, engine, **_):
        """خروج دفاعي سفلي (تضييق) عبر منفّذ الخروج المُختبَر — محروس بالكامل.

        لا يُلغي داخل منفّذ الوقف؛ يمرّر order_list_id ليحرّر المنفّذ الرصيد ثم
        يُعيد reconcile قبل الوضع (منع البيع المزدوج بنيويًّا). exit_side="lower"
        دائمًا (لا بيع عارٍ، لا هيدج). dry_run=False (التحكيم الحيّ يتمّ في المُشرِف).
        """
        try:
            reference_price = getattr(state, "reference_price", None)
            if reference_price is None:
                reference_price = getattr(state, "last_price", None)
            selected = getattr(engine, "selected_oco", None) if engine is not None else None
            if selected is None:
                selected = getattr(state, "selected_oco", None)
            target_qty = getattr(selected, "quantity", None)
            filters = filters_fn(symbol)
            order_list_id = getattr(state, "target_order_list_id", None)
            if order_list_id is None:
                order_list_id = getattr(selected, "order_list_id", None)
            kill_switch = getattr(engine, "kill_switch", None) if engine is not None else None
            cid = _default_btc_cid()
            w = window_getter()
            notifier = getattr(w, "_alerts_notifier", None) if w is not None else None
            return execute_market_exit(
                client=exit_broker,
                symbol=symbol,
                base_asset=base_asset or "",
                exit_side="lower",
                reference_price=reference_price,
                target_qty=target_qty,
                filters=filters,
                client_order_id=cid,
                order_list_id=order_list_id,
                kill_switch=kill_switch,
                notifier=notifier,
                dry_run=False,
            )
        except Exception as exc:
            return {"action": "ERROR", "placed": False, "error": str(exc)}

    def btc_alert_cb(text):
        # نفس توجيه alert_cb: enqueue إلى _alerts_notifier عبر escape_mdv2، وإلا log.
        try:
            w = window_getter()
            notifier = getattr(w, "_alerts_notifier", None) if w is not None else None
            if notifier is not None and hasattr(notifier, "enqueue"):
                try:
                    from ocobot.alerts.formatting import escape_mdv2

                    notifier.enqueue(escape_mdv2(text))
                    return
                except Exception:
                    pass
            log.warning("BTC GUARD ALERT: %s", text)
        except Exception:
            pass

    return GuardianSupervisor(
        state_provider=state_provider,
        client=broker,
        alert_cb=alert_cb,
        config=_build_config(),
        dry_run=dry_run,
        base_asset_fn=base_asset_fn,
        filters_fn=filters_fn,
        btc_follow=btc_follow,
        btc_exit_fn=btc_exit_fn,
        btc_alert_cb=btc_alert_cb,
    )


def _default_btc_cid():
    """مُعرّف أمر عميل <=36 حرفًا لخروج حارس BTC (Binance-safe)."""
    from uuid import uuid4
    return "btcg-%s" % uuid4().hex[:20]


def build_guardian_supervisor_for_ui(window_getter):
    """G1.31/chunk_5a: يبني مُشرِفًا خاملًا للتحكّم وقت التشغيل من الواجهة — دائمًا (بلا بوّابة بيئة).

    لا يمسّ build_guardian_supervisor المختوم (G1.30). الافتراضي dry_run=True (رصد).
    النشاط محكوم حصريًّا بمحوّل الواجهة (GuardianStatusAdapter): في وضع OFF لا يُستدعى
    tick إطلاقًا فلا تدخّل ولا شبكة. يُستعمل عندما يُعيد build_guardian_supervisor None
    (أي OCOBOT_GUARDIAN غير مضبوط) ليتيح للمستخدم تسليح/إطفاء الحارس من الواجهة.
    """
    try:
        supervisor = _build_supervisor_core(window_getter, dry_run=True)
        log.info("Guardian (UI runtime) built inert: dry_run=True (mode controlled by UI)")
        return supervisor
    except Exception:
        log.warning("تعذّر بناء مُشرِف الواجهة الخامل — سيبقى العرض DISABLED.")
        return None
