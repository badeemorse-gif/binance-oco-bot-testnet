"""OCOBot Qt application bootstrap (T10a).

``build_app()`` returns a themed ``(app, window)`` pair and is CI-safe under
the offscreen platform. ``main()`` runs the event loop.
"""

import os

from ._qt import QApplication, QGuiApplication
from .theme import apply_theme
from .main_window import MainWindow
from . import i18n
from ocobot.config import AppConfig
from ocobot.core.preflight import run_preflight
from ocobot.core.connection_state import ConnectionState, ConnectionStatus
from ocobot.cli import _client_with_keys, _build_executor
from ocobot.core.audit_log import AuditLog
from ocobot.core.connection import build_gui_client, make_gui_connect_handler, make_gui_disconnect_handler
from ocobot.domain.oco_reader import OcoReader
from ocobot.domain.exchange_info import ExchangeInfoService
from ocobot.domain.selection import Selector
from ocobot.core.environment import Environment
from ocobot.app_wiring import SelectionPriceProvider, BtcPriceProvider, build_convert_executor, make_convert_cb
from ocobot.domain.monitoring import MonitoringEngine
from ocobot.domain.open_orders_reader import read_all_open_sell_orders
# G1.57: ناقلا lazy للـnotifier/store (مُعادان من محور تسليح الحارس) للخروج اليدوي.
from ocobot.ui.guardian_arm import _LazyNotifierShim, _LazyStoreShim


def build_app(argv=None, select_fn=None, executor=None, execute_cb=None, engine=None, price_provider=None, convert_cb=None, audit_path=None, guardian_supervisor=None):
    """Create-or-reuse the QApplication, apply the theme, build MainWindow.

    Returns a ``(app, window)`` tuple. Safe to call under
    ``QT_QPA_PLATFORM=offscreen`` for tests/CI.
    """
    app = QApplication.instance()
    if app is None:
        app = QApplication(argv if argv is not None else [])

    apply_theme(app)
    window = MainWindow(select_fn=select_fn, executor=executor, execute_cb=execute_cb, engine=engine, price_provider=price_provider, convert_cb=convert_cb, audit_path=audit_path, guardian_supervisor=guardian_supervisor)
    return app, window


def _clamp_window_to_screen(window):
    """احتوِ النافذة داخل availableGeometry عند الإطلاق (resize + توسيط) دون فرض سقف حجم دائم، كي يعمل زر التكبير."""
    screen = QGuiApplication.primaryScreen()
    if screen is None:
        return
    avail = screen.availableGeometry()
    hint = window.sizeHint()
    w = min(hint.width(), avail.width())
    h = min(hint.height(), avail.height())
    if w > 0 and h > 0:
        window.resize(w, h)
    frame = window.frameGeometry()
    frame.moveCenter(avail.center())
    window.move(frame.topLeft())


def make_connect_wrapper(window, base_connect, cfg):
    # G1.24 P1: compute a guarded AuditLog for this construction context so the
    # lazily rebuilt monitoring executor/engine below record to the same audit
    # sink as the startup wiring. Same path rule as cli/completed_trades.
    audit_path = os.environ.get("OCOBOT_AUDIT_LOG", os.path.join(os.getcwd(), "ocobot_audit.jsonl"))
    try:
        _audit = AuditLog(audit_path)
    except Exception:
        _audit = None

    def _wrapped_connect(*args, **kwargs):
        result = base_connect(*args, **kwargs)
        if getattr(result, "ok", False):
            window.connection_notifier.set_state(
                ConnectionState(
                    status=ConnectionStatus.CONNECTED,
                    environment=cfg.env,
                    rest_base=cfg.rest_base(),
                    message="متصل",
                )
            )
            oo = window.content.screen_for("02_open_orders")
            if oo is not None and hasattr(oo, "set_source"):
                # G1.17: cold start skips the startup `if _client is not None:`
                # wiring (build_gui_client raised → _client None, no fixed-path
                # fallback since G1.15), so OpenOrdersScreen has _build_fn=None
                # and refresh() early-returns. On a successful connect we now
                # inject the data source + selector here (mirrors the startup
                # block), rebuilding the client lazily on the worker thread, so
                # the table actually renders rows. UI thread stays network-free.
                oo.set_source(
                    build_fn=lambda: read_all_open_sell_orders(
                        build_gui_client(AppConfig.from_env_vars())
                    ),
                    runner=window.runner,
                )
                try:
                    # Replicate the startup selector construction EXACTLY,
                    # rebuilding the client lazily. A selector failure must not
                    # block the orders table, so it is isolated.
                    _lazy_client = build_gui_client(AppConfig.from_env_vars())
                    _selector = Selector(
                        OcoReader(_lazy_client), ExchangeInfoService(_lazy_client)
                    )
                    if hasattr(oo, "set_selector"):
                        oo.set_selector(_selector)
                except Exception:
                    pass
                try:
                    oo.refresh()
                except Exception:
                    pass
            elif oo is not None and hasattr(oo, "refresh"):
                try:
                    oo.refresh()
                except Exception:
                    pass
            # G1.18: same regression as G1.17 but for screens 03/04. On cold
            # start build_gui_client raised → engine/executor/execute_cb/
            # price_provider/convert_cb were all None, so the five handlers in
            # SelectedOcoScreen (03) and DynamicMonitoringScreen (04) early-return
            # via their None guards. Now that connect succeeded the session keys
            # are set, so we rebuild the deps EXACTLY like the startup block
            # (build_gui_client + _build_executor + MonitoringEngine +
            # SelectionPriceProvider + build_convert_executor/make_convert_cb,
            # identical flags incl. dry_run=False) and re-inject them via the new
            # setters. Fully isolated (try/except, swallow/log) so a failure here
            # never crashes the connect flow, and we do NOT touch the screen-02
            # block above. No new blocking IO on the UI thread beyond the mirrored
            # pattern — the lazy client build matches what the 02 block already does.
            try:
                _lazy_cfg = AppConfig.from_env_vars()
                _lazy_client = build_gui_client(_lazy_cfg)
                _lazy_executor = _build_executor(_lazy_client, audit=_audit)
                _lazy_engine = MonitoringEngine(_lazy_executor, dry_run=False, audit=_audit)
                _lazy_price = SelectionPriceProvider(_lazy_cfg, _lazy_client)
                _lazy_convert_exec = build_convert_executor(_lazy_client, audit=None)
                _lazy_convert_cb = make_convert_cb(_lazy_convert_exec, _lazy_price)
                sel = window.content.screen_for("03_selected_and_edit")
                if sel is not None:
                    if hasattr(sel, "set_executor"):
                        sel.set_executor(_lazy_executor)
                    # نُبقي الأولويّة لـ executor.execute كما في بناء الإقلاع الأصلي
                    # (execute_cb كان None هناك) — لا نحقن execute_cb جديدًا.
                mon = window.content.screen_for("04_dynamic_monitoring")
                if mon is not None:
                    if hasattr(mon, "set_engine"):
                        mon.set_engine(_lazy_engine)
                    if hasattr(mon, "set_price_provider"):
                        mon.set_price_provider(_lazy_price)
                    if hasattr(mon, "set_convert_cb"):
                        mon.set_convert_cb(_lazy_convert_cb)
                    # G1.45: حقن موفّر سعر BTCUSDT الحيّ المستقلّ (الشبكة داخل الموفّر).
                    try:
                        if hasattr(mon, "set_btc_price_provider"):
                            mon.set_btc_price_provider(BtcPriceProvider(_lazy_cfg, _lazy_client))
                    except Exception:
                        pass
                    # G1.60: حقن مزوّد اقتراح النِّسب (klines⇒recommender) — الشبكة داخل الرَنَر.
                    try:
                        if hasattr(mon, "set_recommendation_provider"):
                            from ocobot.domain.klines import KlinesService as _KlinesSvc
                            from ocobot.app_wiring import build_recommendation_provider as _mk_rec
                            mon.set_recommendation_provider(_mk_rec(
                                _KlinesSvc(_lazy_client),
                                lambda _m=mon: getattr(getattr(_m, "_selected", None), "symbol", None)))
                    except Exception:
                        pass
                    # G1.47: ربط الخروج اليدوي الفوري — زرّ «تنفيذ» (Testnet فقط، dry_run=False).
                    # معزول ومتسامح: فشل هنا لا يمسّ باقي الحقن ولا تدفّق الاتصال.
                    try:
                        if hasattr(mon, "set_manual_exit_fn"):
                            from ocobot.core.market_exit_broker import MarketExitBroker as _MeBroker
                            from ocobot.core.guardian_broker import base_asset_of as _me_base_of
                            from ocobot.domain.pricing import DEFAULT_GAP_TICKS as _ME_GAP
                            from types import SimpleNamespace as _MeNS
                            from .manual_exit import build_manual_exit_fn as _build_manual_exit_fn
                            from ocobot.domain.completed_trades import make_exit_source_recorder as _mk_exit_src
                            # G1.57: مُطلِق تنبيه ✋ ثريّ للخروج اليدوي عبر notifier(result) عند PLACED.
                            from ocobot.alerts.bridge import make_manual_exit_notifier as _mk_manual_notifier
                            _me_broker = _MeBroker(_lazy_client)
                            _me_exinfo = ExchangeInfoService(_lazy_client)

                            def _me_base_asset_fn(symbol):
                                try:
                                    return _me_base_of(symbol, _me_exinfo)
                                except Exception:
                                    try:
                                        return _me_base_of(symbol)
                                    except Exception:
                                        return None

                            def _me_filters_fn(symbol):
                                try:
                                    f = _me_exinfo.get_filters(symbol)
                                    if f is None:
                                        return None
                                    return _MeNS(
                                        symbol=getattr(f, "symbol", symbol),
                                        tick_size=getattr(f, "tick_size", None),
                                        step_size=getattr(f, "step_size", None),
                                        min_qty=getattr(f, "min_qty", None),
                                        min_notional=getattr(f, "min_notional", None),
                                        gap_ticks=_ME_GAP,
                                    )
                                except Exception:
                                    return None

                            mon.set_manual_exit_fn(
                                _build_manual_exit_fn(
                                    exit_broker=_me_broker,
                                    state_provider=lambda e=_lazy_engine: getattr(e, "state", None),
                                    selected_provider=lambda m=mon: getattr(m, "_selected", None),
                                    filters_fn=_me_filters_fn,
                                    base_asset_fn=_me_base_asset_fn,
                                    kill_switch_getter=lambda e=_lazy_engine: getattr(e, "kill_switch", None),
                                    # G1.57: مُطلِق ✋ ثريّ — يُستدعى notifier(result) عند PLACED.
                                    #        shim lazy يحلّ window._alerts_notifier/_alerts_store وقت التشغيل.
                                    notifier_getter=lambda w=window: _mk_manual_notifier(
                                        notifier=_LazyNotifierShim(lambda: w),
                                        store=_LazyStoreShim(lambda: w),
                                    ),
                                    exit_side="upper",
                                    dry_run=False,
                                    exit_source_noter=_mk_exit_src(_audit),
                                )
                            )
                    except Exception:
                        pass
                # G1.19 fix v2: also inject the lazy price provider into the main window
                # so _show_selected seeds live price for pre-existing (old) OCO orders.
                if hasattr(window, "set_price_provider"):
                    window.set_price_provider(_lazy_price)
            except Exception:
                pass
        return result
    return _wrapped_connect


def main():  # pragma: no cover - interactive entry point
    # G1.8: قفل البيئة على Testnet لكامل الجلسة + حقن backend حقيقي. G1.3: select_fn لتأسيس Live context عند الاختيار.
    import os
    os.environ["OCOBOT_ENV"] = Environment.TESTNET.value  # Testnet-lock صريح — يمنع أي انزلاق لـ live بغضّ النظر عن قيمة OCOBOT_ENV الخارجية
    _cfg = AppConfig.from_env_vars()
    # G1.24 P1: audit path (same rule as cli/completed_trades) + guarded AuditLog
    # wired into the monitoring executor + engine, and threaded into the window.
    audit_path = os.environ.get("OCOBOT_AUDIT_LOG", os.path.join(os.getcwd(), "ocobot_audit.jsonl"))
    try:
        _audit = AuditLog(audit_path)
    except Exception:
        _audit = None
    try:
        _client = build_gui_client(_cfg)
    except Exception:
        _client = None
    _selector = Selector(OcoReader(_client), ExchangeInfoService(_client)) if _client is not None else None
    _executor = _build_executor(_client, audit=_audit) if _client is not None else None
    _engine = MonitoringEngine(_executor, dry_run=False, audit=_audit) if (_client is not None and _executor is not None) else None
    _price = SelectionPriceProvider(_cfg, _client) if _client is not None else None
    # G1.13 (CHUNK 1): بناء callback التحويل إلى OCO (wiring) — يُمرَّر لشاشة 04.
    _convert_exec = build_convert_executor(_client, audit=None) if _client is not None else None
    _convert_cb = make_convert_cb(_convert_exec, _price) if _convert_exec is not None else None
    def _select(order_list_id):
        if _selector is None or _price is None:
            return None
        selected = _selector.select(order_list_id)
        try:
            _price.set_symbol(getattr(selected, "symbol", None))
            p = _price.get_price()
            if p is not None:
                selected.current_price = p  # G1.8: سعر حيّ على الهدف يصل لكل الشاشات
        except Exception:
            pass  # لا نُفشل الاختيار بسبب تعذّر الـ feed
        return selected
    # G1.30 chunk_5: تسليح شبكة أمان المركز — مُبوّد ومُطفأ افتراضيًّا عبر OCOBOT_GUARDIAN.
    # ربط متأخّر: المُشرِف يقرأ النافذة الحيّة (محرّك شاشة 04 + alerts) وقت التشغيل
    # عبر window_getter، لأن النافذة تُبنى في السطر التالي. البيئة مقفولة على Testnet أعلاه.
    from .guardian_arm import build_guardian_supervisor
    _guardian_box = {"window": None}
    _guardian_supervisor = build_guardian_supervisor(lambda: _guardian_box["window"])
    app, window = build_app(select_fn=_select, executor=_executor, engine=_engine, price_provider=_price, convert_cb=_convert_cb, audit_path=audit_path, guardian_supervisor=_guardian_supervisor)
    _guardian_box["window"] = window

    # G1.31 (chunk_3): جعل شبكة أمان المركز مرئيّة ومتحكَّمًا بها من شاشة المراقبة.
    # نبني مخزن حالة + محوّلًا خالصًا يقرأ وضع الشاشة (Off/Observe/Live، افتراضيًّا
    # Off) ويمنع التدخّل عند Off. المُشرِف قد يكون None (البيئة غير مضبوطة) والمحوّل
    # يتحمّل ذلك ويعرض DISABLED فقط. ثم نوجّه نبضة مؤقّت الحارس القائم إلى
    # ``adapter.tick`` بدل نبضة المُشرِف الخام — ربط إضافي بحت، الافتراضي بلا تغيير.
    try:
        from ocobot.domain.guardian_status import GuardianMode as _GuardianMode
        from ocobot.domain.guardian_status import GuardianStatusStore as _GuardianStatusStore
        from .guardian_wiring import GuardianStatusAdapter as _GuardianStatusAdapter

        _guardian_store = _GuardianStatusStore()
        _mon_screen = window.content.screen_for("04_dynamic_monitoring")
        if _mon_screen is not None and hasattr(_mon_screen, "set_guardian_status"):
            _guardian_store.subscribe(_mon_screen.set_guardian_status)

        # G1.45: حقن موفّر سعر BTCUSDT الحيّ المستقلّ (الشبكة داخل الموفّر؛ لا شبكة في الواجهة).
        try:
            if _client is not None and _mon_screen is not None and hasattr(_mon_screen, "set_btc_price_provider"):
                _mon_screen.set_btc_price_provider(BtcPriceProvider(_cfg, _client))
        except Exception:
            pass

        # G1.60: حقن مزوّد اقتراح النِّسب (klines⇒recommender) — الشبكة داخل الرَنَر خارج خيط Qt.
        try:
            if _client is not None and _mon_screen is not None and hasattr(_mon_screen, "set_recommendation_provider"):
                from ocobot.domain.klines import KlinesService as _KlinesSvc
                from ocobot.app_wiring import build_recommendation_provider as _mk_rec
                _mon_screen.set_recommendation_provider(_mk_rec(
                    _KlinesSvc(_client),
                    lambda _s=_mon_screen: getattr(getattr(_s, "_selected", None), "symbol", None)))
        except Exception:
            pass

        def _guardian_mode_getter(_screen=_mon_screen):
            if _screen is not None and hasattr(_screen, "guardian_mode"):
                try:
                    return _screen.guardian_mode()
                except Exception:
                    return _GuardianMode.OFF
            return _GuardianMode.OFF

        # G1.31/chunk_5a: إن لم يُسلّح الحارس عبر البيئة (المُشرِف None) نبني مُشرِفًا
        # خاملًا للتحكّم وقت التشغيل من الواجهة — دون المساس بالسلوك المختوم (G1.30)
        # ولا بالمسار الحار. النشاط محكوم بالمحوّل: OFF ⇒ لا tick ولا تدخّل ولا شبكة.
        _adapter_supervisor = _guardian_supervisor
        if _adapter_supervisor is None:
            try:
                from .guardian_arm import build_guardian_supervisor_for_ui as _build_ui_sup
                _adapter_supervisor = _build_ui_sup(lambda: _guardian_box["window"])
            except Exception:
                _adapter_supervisor = None

        _guardian_adapter = _GuardianStatusAdapter(
            supervisor=_adapter_supervisor,
            store=_guardian_store,
            mode_getter=_guardian_mode_getter,
        )

        # G1.44 / chunk_4: دفع حالة عرض شبكة أمان المركز دون استدعاء tick ثانٍ.
        #   التِّك المشترك يحدث مرّة واحدة في _combined_tick؛ هنا نشتقّ الحالة من
        #   سطح المُشرِف العامّ ونعرضها (دفاعيّ، لا يرمي).
        def _push_guardian_display(mode):
            try:
                from ocobot.domain.guardian_status import GuardianStatus as _GS
                from ocobot.domain.guardian_status import GuardianUiState as _GUIS
                from .guardian_wiring import derive_ui_state as _derive_ui
                sup = _adapter_supervisor
                if mode is _GuardianMode.OFF or sup is None:
                    _guardian_store.set(_GS(mode=_GuardianMode.OFF, state=_GUIS.DISABLED))
                    return
                decision = getattr(sup, "last_decision", None)
                armed = bool(getattr(sup, "_armed", False))
                state = _derive_ui(mode, decision, armed)
                _guardian_store.set(_GS(mode=mode, state=state))
            except Exception:
                pass
        # G1.32b: ربط قوس الخروج بالسعر — إضافيّ ومُطفأ افتراضيًّا (المفتاح في الواجهة).
        _bracket_wiring = None
        try:
            import os as _bx_os
            from ocobot.core.guardian_lazy_client import LazyGuardianRestClient as _BxLazy
            from ocobot.core.market_exit_broker import MarketExitBroker as _BxBroker
            from ocobot.core.guardian_broker import base_asset_of as _bx_base_of
            from ocobot.domain.exchange_info import ExchangeInfoService as _BxExInfo
            from ocobot.domain.pricing import DEFAULT_GAP_TICKS as _BX_GAP
            from .bracket_wiring import BracketExitWiring as _BxWiring
            from ocobot.alerts.bridge import make_market_exit_notifier as _mk_bx_notifier
            from types import SimpleNamespace as _BxNS
            _bx_client = _BxLazy()
            _bx_broker = _BxBroker(_bx_client)
            _bx_exinfo = _BxExInfo(_bx_client)

            def _bx_filters(symbol):
                try:
                    f = _bx_exinfo.get_filters(symbol)
                    if f is None:
                        return None
                    return _BxNS(symbol=getattr(f, 'symbol', symbol),
                                tick_size=getattr(f, 'tick_size', None),
                                step_size=getattr(f, 'step_size', None),
                                min_qty=getattr(f, 'min_qty', None),
                                min_notional=getattr(f, 'min_notional', None),
                                gap_ticks=_BX_GAP)
                except Exception:
                    return None

            def _bx_base(symbol):
                try:
                    return _bx_base_of(symbol, _bx_exinfo)
                except Exception:
                    try:
                        return _bx_base_of(symbol)
                    except Exception:
                        return None

            def _bx_selected(_screen=_mon_screen):
                return getattr(_screen, '_selected', None) if _screen is not None else None

            def _bx_config(_screen=_mon_screen):
                if _screen is not None and hasattr(_screen, 'bracket_config'):
                    try:
                        return _screen.bracket_config()
                    except Exception:
                        return None
                return None

            def _bx_price(_screen=_mon_screen):
                return getattr(_screen, '_current_price', None) if _screen is not None else None

            def _bx_kill():
                eng = getattr(_mon_screen, '_engine', None)
                return getattr(eng, 'kill_switch', None) if eng is not None else None

            # G1.46: مُطلِق وسم مصدر الخروج (PRICE_BRACKET) — إضافة بحتة محروسة.
            def _bx_exit_source(source):
                eng = getattr(_mon_screen, '_engine', None)
                if eng is not None and hasattr(eng, 'note_exit_source'):
                    try:
                        eng.note_exit_source(source)
                    except Exception:
                        pass

            if _mon_screen is not None and hasattr(_mon_screen, 'bracket_config'):
                _bracket_wiring = _BxWiring(
                    broker=_bx_broker, config_getter=_bx_config,
                    price_getter=_bx_price, selected_getter=_bx_selected,
                    filters_fn=_bx_filters, base_asset_fn=_bx_base,
                    dry_run_getter=lambda: (_bx_os.environ.get('OCOBOT_BRACKET', '').strip().lower() != 'live'),
                    kill_switch_getter=_bx_kill,
                    exit_source_noter=_bx_exit_source,
                    # G1.62: مُطلِق تنبيه 🧷 ثريّ لقوس الخروج بالسعر عبر notifier(result) عند PLACED.
                    #        كان مفقودًا في الإنتاج (الدالة مستعملة في الاختبارات فقط) ⇒ القوس كان صامتًا.
                    #        shim lazy يحلّ window._alerts_notifier/_alerts_store وقت التشغيل.
                    notifier=_mk_bx_notifier(
                        notifier=_LazyNotifierShim(lambda: window),
                        store=_LazyStoreShim(lambda: window),
                    ),
                )
        except Exception:
            _bracket_wiring = None

        # G1.44 / chunk_4: محوّل حالة حارس هبوط BTC المستقلّ + مخزنه + مؤشّره.
        # يتشارك نفس المُشرِف مع شبكة أمان المركز؛ لذا نضبط بوّابتَي التشغيل ثم
        # نستدعي supervisor.tick() **مرّة واحدة** عندما يكون أيّ من الحارسين غير OFF،
        # ثم ندفع لقطتَي الحالة. OFF/OFF ⇒ لا tick إطلاقًا (السلوك الافتراضي محفوظ).
        _btc_follow_adapter = None
        try:
            from ocobot.domain.guardian_status import GuardianStatusStore as _BtcStore
            from .btc_follow_wiring import BtcFollowStatusAdapter as _BtcAdapter

            _btc_store = _BtcStore()
            if _mon_screen is not None and hasattr(_mon_screen, "set_btc_follow_status"):
                _btc_store.subscribe(_mon_screen.set_btc_follow_status)

            def _btc_mode_getter(_screen=_mon_screen):
                if _screen is not None and hasattr(_screen, "btc_follow_mode"):
                    try:
                        return _screen.btc_follow_mode()
                    except Exception:
                        return _GuardianMode.OFF
                return _GuardianMode.OFF

            _btc_follow_adapter = _BtcAdapter(
                supervisor=_adapter_supervisor,
                store=_btc_store,
                mode_getter=_btc_mode_getter,
            )
        except Exception:
            _btc_follow_adapter = None

        def _combined_tick():
            # G1.44: تِك مدموج يضمن supervisor.tick() مرّة واحدة لكل دورة.
            # 1) اقرأ وضعَي الحارسين.
            try:
                _pos_mode = _guardian_mode_getter()
            except Exception:
                _pos_mode = _GuardianMode.OFF
            try:
                _btc_mode = (
                    _btc_follow_adapter.apply_runtime()
                    if _btc_follow_adapter is not None
                    else _GuardianMode.OFF
                )
            except Exception:
                _btc_mode = _GuardianMode.OFF

            # 2) اضبط تشغيل شبكة أمان المركز من وضعها (OFF ⇒ enabled=False).
            _sup = _adapter_supervisor
            if _sup is not None and hasattr(_sup, "set_guardian_runtime"):
                try:
                    _sup.set_guardian_runtime(
                        enabled=(_pos_mode is not _GuardianMode.OFF),
                        dry_run=(_pos_mode is not _GuardianMode.LIVE),
                    )
                except Exception:
                    pass

            # 3) tick مرّة واحدة فقط إن كان أيّ من الحارسين غير OFF.
            if _sup is not None and (
                _pos_mode is not _GuardianMode.OFF or _btc_mode is not _GuardianMode.OFF
            ):
                try:
                    _sup.tick()
                except Exception:
                    pass

            # 4) ادفع لقطتَي الحالة (شبكة الأمان عبر محوّلها بوضع OFF-aware، وBTC).
            try:
                _guardian_adapter.tick() if _pos_mode is _GuardianMode.OFF else None
            except Exception:
                pass
            # شبكة الأمان: ادفع الحالة دائمًا عبر مسار العرض (push) دون tick ثانٍ.
            try:
                _push_guardian_display(_pos_mode)
            except Exception:
                pass
            if _btc_follow_adapter is not None:
                try:
                    _btc_follow_adapter.push_status(_btc_mode)
                except Exception:
                    pass
            if _bracket_wiring is not None:
                try:
                    _bracket_wiring.tick()
                except Exception:
                    pass

        if hasattr(window, "set_guardian_tick"):
            window.set_guardian_tick(_combined_tick)
        if hasattr(window, "start_guardian_timer_if_needed"):
            window.start_guardian_timer_if_needed()
    except Exception:
        # ربط إضافي بحت: أي فشل لا يكسر التطبيق ولا المسار الحار ولا السلوك الافتراضي.
        pass
    i18n.apply_direction(app, window)  # G1.20 step_3_wire: فرض اتجاه RTL على مستوى التطبيق (العربية افتراضيًا)
    window.set_environment(_cfg.env)  # G1.8: يخزّن البيئة للداشبورد + يحدّث شارة التوب-بار
    _conn_screen = window.content.screen_for("07_connection")
    if _conn_screen is not None and hasattr(_conn_screen, "set_connect_handler"):
        # G1.15: wrap the connect handler so a successful connection propagates
        # beyond the connection screen's own pill — flip the top-left status
        # (connection_notifier → topbar GREEN "متصل") and refresh Open Orders.
        # Mirrors the _do_disconnect pattern below. No network here (handler
        # itself does the IO on the AsyncRunner); UI stays network-free.
        _base_connect = make_gui_connect_handler()
        _wrapped_connect = make_connect_wrapper(window, _base_connect, _cfg)
        _conn_screen.set_connect_handler(_wrapped_connect)
    # G1.12: single isolated disconnect path shared by BOTH buttons (Topbar +
    # ConnectionScreen). Clears the session key source and flips both
    # indicators to red. Synchronous, no network.
    _disconnect_handler = make_gui_disconnect_handler()

    def _do_disconnect(*_a, **_k):
        state = _disconnect_handler()
        window.connection_notifier.set_state(state)      # topbar → red via USER_DISCONNECT
        if _conn_screen is not None and hasattr(_conn_screen, "set_connection_state"):
            _conn_screen.set_connection_state("DISCONNECTED_USER")  # screen → red
        # G1.24 A1 (disconnect): on connection teardown, notify the active
        # monitored session so a monitor_closed(stopped_disconnect) event is
        # written. Mirrors the kill_switch wiring: we obtain the engine from the
        # DynamicMonitoringScreen (screen_for 04) exactly like _on_kill_switch_clicked
        # reads self._engine, then CALL engine.notify_disconnect() (no args — real
        # signature). Fully isolated/None-safe so a teardown never crashes; never
        # cancels any order on Binance (engine method is cancel-free by design).
        try:
            mon = window.content.screen_for("04_dynamic_monitoring")
            _eng = getattr(mon, "_engine", None) if mon is not None else None
            if _eng is not None and getattr(getattr(_eng, "state", None), "enabled", False):
                _eng.notify_disconnect()  # real signature: notify_disconnect(self)
                if mon is not None:
                    if hasattr(mon, "stop_live_updates"):
                        mon.stop_live_updates()
                    if hasattr(mon, "_refresh_live_panel"):
                        mon._refresh_live_panel()
        except Exception:
            pass

    if _conn_screen is not None and hasattr(_conn_screen, "set_disconnect_handler"):
        _conn_screen.set_disconnect_handler(_do_disconnect)
    window.topbar.disconnect_requested.connect(_do_disconnect)
    _clamp_window_to_screen(window)
    window.show()
    window.refresh_connection(lambda: run_preflight(AppConfig.from_env_vars()))
    if _client is not None:
        oo = window.content.screen_for("02_open_orders")
        if oo is not None and hasattr(oo, "set_source"):
            # G1.13 (CHUNK 1): شاشة 02 تُغذّى بكل أوامر البيع (مستقلة + OCO مدموجة)
            # مع شارات النوع عبر set_open_sell_orders، بدل OCO فقط. set_source يحقن
            # build_fn + runner فيعمل refresh على خيط منفصل ثم set_open_sell_orders.
            oo.set_source(
                build_fn=lambda: read_all_open_sell_orders(
                    build_gui_client(AppConfig.from_env_vars())
                ),
                runner=window.runner,
            )
            if hasattr(oo, "set_selector") and _selector is not None:
                oo.set_selector(_selector)
            oo.refresh()
    return app.exec()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
