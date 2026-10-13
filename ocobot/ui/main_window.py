"""OCOBot main window.

T10a: minimal shell (title "OCOBot", full RTL).
T10b: navigation shell — right-side Sidebar (RTL) + Topbar (title + two
static Pills) + a Content region routed by ``QStackedWidget``. Selecting a
Sidebar entry switches the visible Content screen and updates the Topbar
title. No business logic, no network (that is T10c and T11–T13).
"""

from ._qt import Qt, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QScrollArea, QApplication, QTimer
from .theme import set_base_font_scale
from .sidebar import Sidebar
from .topbar import Topbar
from .content import ContentRouter
from .screens import SCREENS
from .async_exec import AsyncRunner
from .connection import ConnectionStateNotifier
from . import i18n
from ocobot.domain.selection import build_dashboard, DASH
from ocobot.alerts import TelegramClient, Notifier
from ocobot.alerts.storage import AlertsStore
from ocobot.alerts.bridge import AlertsAuditBridge


class MainWindow(QMainWindow):
    """Top-level window hosting the OCOBot navigation shell."""

    def __init__(self, parent=None, runner=None, select_fn=None, executor=None, execute_cb=None,
                 engine=None, price_provider=None, convert_cb=None, audit_path=None,
                 guardian_supervisor=None, guardian_interval_ms=1000):
        super().__init__(parent)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowMinimizeButtonHint | Qt.WindowType.WindowMaximizeButtonHint | Qt.WindowType.WindowCloseButtonHint)
        self._zoom = 1.0
        self.setWindowTitle(i18n.translate_for_current("OCOBot"))
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

        # Injected selection callable (services layer owns any IO). The UI never
        # constructs a REST client nor performs network directly (P2/P3).
        self._select_fn = select_fn

        # T13: injected MonitoringEngine + live-price provider (WS+REST fallback)
        # forwarded down into the Dynamic Monitoring screen. Backward-compatible
        # defaults = None; the UI performs no network itself (D11/D14).
        self._engine = engine
        self._price_provider = price_provider
        self._environment = None  # G1.8: البيئة الفعلية للعرض في الداشبورد
        # G1.24 P1: audit log path threaded down to CompletedTradesScreen so the
        # UI reads closed trades from the SAME sink the monitoring wiring writes.
        # Backward-compatible default = None (screen falls back to its own rule).
        self.audit_path = audit_path

        # Title lookup for each screen key (verbatim mockup titles).
        self._title_by_key = {s["key"]: s["title"] for s in SCREENS}

        central = QWidget(self)
        central.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

        # Root layout: horizontal so the Sidebar sits on the right under RTL
        # (first-added widget takes the trailing/right edge), and the main
        # column (Topbar over Content) fills the rest.
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Right-side Sidebar (RTL): added first so it anchors to the right.
        self.sidebar = Sidebar(on_select=self._on_nav_select, parent=central)

        # Main column: Topbar on top, Content below.
        self.main_column = QWidget(central)
        self.main_column.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        column_layout = QVBoxLayout(self.main_column)
        column_layout.setContentsMargins(0, 0, 0, 0)
        column_layout.setSpacing(0)

        # Async execution layer: keeps ALL IO off the UI thread. Optionally
        # injectable (e.g. for tests). The UI never performs network directly.
        # Created BEFORE the ContentRouter so the runner (and any injected
        # executor/execute_cb) can be forwarded down into the Selected screen
        # for off-UI-thread Activate execution.
        self.runner = runner or AsyncRunner()

        self.topbar = Topbar(parent=self.main_column)
        # G1.13 (إضافي): callback التحويل إلى OCO (محقون من wiring) يُمرَّر لشاشة 02.
        self._convert_cb = convert_cb
        self.content = ContentRouter(parent=self.main_column, runner=self.runner, executor=executor, execute_cb=execute_cb, engine=engine, price_provider=price_provider, on_execution_result=self._handle_execution_result, convert_cb=convert_cb, audit_path=self.audit_path)
        column_layout.addWidget(self.topbar)
        self._content_scroll = QScrollArea(self.main_column)
        self._content_scroll.setWidgetResizable(True)
        self._content_scroll.setStyleSheet("QScrollArea { border: none; }")
        self._content_scroll.setWidget(self.content)
        column_layout.addWidget(self._content_scroll, 1)

        # Wire selection: choosing an OCO row in the Open Orders screen
        # establishes the live context (via the injected select_fn) and shows
        # the Selected screen. No IO here — the callable owns any network.
        oo = self.content.screen_for("02_open_orders")
        if oo is not None and hasattr(oo, "set_on_select"):
            oo.set_on_select(self.handle_oco_selection)
        # G1.13 (إضافي): مسار "كل أوامر البيع" — عند اختيار صفّ بيع نُغذّي الأقسام
        # المستهلِكة (03/04/01) بنفس SelectedOCO عبر _show_selected.
        # CHUNK 1: التحويل لم يعد يمرّ عبر شاشة 02؛ convert_cb يُمرَّر إلى شاشة 04
        # (DynamicMonitoringScreen) من داخل ContentRouter.
        if oo is not None and hasattr(oo, "set_on_sell_select"):
            oo.set_on_sell_select(self._show_selected)

        root.addWidget(self.sidebar)
        root.addWidget(self.main_column, 1)

        self.setCentralWidget(central)

        # Live connection indicator: notifier emits ConnectionState changes,
        # the Topbar connection Pill reacts. No network here.
        self.connection_notifier = ConnectionStateNotifier(self)
        self.connection_notifier.changed.connect(self.topbar.set_connection_state)
        self.topbar.language_toggle_requested.connect(self._on_language_toggle)

        # Sync initial Topbar title with the default (first) screen.
        default_keys = self.content.keys()
        if default_keys:
            self._sync_title(default_keys[0])

        # G1.25 step_6: window-level alerts wiring — READ-ONLY audit→Telegram.
        # ONE AlertsStore + ONE Notifier whose providers reflect the CURRENT
        # on-disk settings each call (so toggling enabled/recipients/token takes
        # effect without a restart). The bridge tails the audit LOG FILE only —
        # it never touches MonitoringEngine/SafeExecutor/pricing and performs no
        # synchronous network (the HTTP happens inside the Notifier worker).
        # Everything is guarded so alerts can NEVER break the UI or hot path.
        self._alerts_store = None
        self._alerts_notifier = None
        self._alerts_bridge = None
        self._alerts_timer = None
        try:
            self._alerts_store = AlertsStore()

            def _client_provider(_store=self._alerts_store):
                # Build a client ONLY when a token is present; otherwise return
                # None so the Notifier worker skips sending (verified tolerant).
                try:
                    token = _store.get_token()
                except Exception:
                    return None
                if not token:
                    return None
                try:
                    return TelegramClient(token)
                except Exception:
                    return None

            self._alerts_notifier = Notifier(
                client_provider=_client_provider,
                recipients_provider=self._alerts_store.recipients_provider,
                enabled_provider=self._alerts_store.enabled_provider,
            )
            self._alerts_notifier.start()

            self._alerts_bridge = AlertsAuditBridge(
                notifier=self._alerts_notifier,
                store=self._alerts_store,
                audit_path=self.audit_path,
                start_at_end=True,
            )

            # Window-level 1s timer: polls the bridge regardless of which screen
            # is visible. The slot wraps poll_once in try/except so it can NEVER
            # raise into the Qt event loop.
            self._alerts_timer = QTimer(self)
            self._alerts_timer.setInterval(1000)
            self._alerts_timer.timeout.connect(self._on_alerts_tick)
            self._alerts_timer.start()
        except Exception:
            # Any failure to wire alerts is non-fatal: the window still works.
            pass

        # G1.30 (chunk_3): ربط إضافي بحت لمُشرِف شبكة أمان المركز (Guardian).
        # خامل افتراضيًّا: لا يُشغَّل أي مؤقّت إلا إذا حُقن ``guardian_supervisor``
        # صراحةً. فعند عدم الحقن (الوضع الافتراضي) لا يتغيّر سلوك المشروع إطلاقًا،
        # ولا يُمسّ المسار الحار. المؤقّت يستدعي ``supervisor.tick()`` خارج خيط
        # الواجهة عبر الـ runner (AsyncRunner)، وكل شيء محروس بحيث لا يرمي أبدًا
        # في حلقة Qt. الوضع الفعلي (dry_run=False) يُسلَّح في chunk_5 عبر حقن
        # مُشرِف غير-dry_run — ليس هنا.
        self._guardian_supervisor = guardian_supervisor
        # G1.31 (chunk_3): نبضة بديلة اختيارية (محوّل حالة الحارس). افتراضيًّا None
        # فتبقى النبضة تستدعي ``supervisor.tick()`` الخام (سلوك chunk_5 دون تغيير).
        self._guardian_tick = None
        self._guardian_interval_ms = int(guardian_interval_ms)
        self._guardian_timer = None
        try:
            if self._guardian_supervisor is not None:
                self._guardian_timer = QTimer(self)
                self._guardian_timer.setInterval(int(guardian_interval_ms))
                self._guardian_timer.timeout.connect(self._on_guardian_tick)
                self._guardian_timer.start()
        except Exception:
            # الربط إضافي بحت: أي فشل في توصيله لا يكسر النافذة ولا المسار الحار.
            self._guardian_timer = None

    def set_guardian_tick(self, tick_fn):
        """G1.31 (chunk_3): حقن نبضة بديلة (محوّل الحالة) تُستدعى بدل ``supervisor.tick``.

        تخزين فقط؛ None-safe. المحوّل خالص (بلا Qt/شبكة) ويمنع التدخّل في وضع Off.
        """
        self._guardian_tick = tick_fn

    def _on_guardian_tick(self):
        """دورة إشراف واحدة خارج خيط الواجهة. يجب ألّا ترمي في حلقة Qt أبدًا.

        فعّالة فقط أثناء المراقبة النشطة (المُشرِف نفسه يعيد ``None`` خارجها فلا
        أثر). تمرّ عبر الـ runner لإبقاء أي قراءة شبكة (في المحوّل) خارج خيط
        الواجهة. محروسة بالكامل.
        """
        try:
            # G1.31 (chunk_3): لو حُقن محوّل حالة الحارس (GuardianStatusAdapter)
            # عبر ``set_guardian_tick`` فنبضته تُستدعى بدل نبضة المُشرِف الخام —
            # فهو يقرأ وضع الواجهة (Off/Observe/Live) ويمنع التدخّل في وضع Off.
            # ``tick`` كلاهما محروس هنا؛ المحوّل خالص (بلا Qt/شبكة).
            tick_fn = getattr(self, "_guardian_tick", None)
            if tick_fn is None:
                sup = getattr(self, "_guardian_supervisor", None)
                if sup is None:
                    return
                tick_fn = sup.tick
            runner = getattr(self, "runner", None)
            if runner is not None and hasattr(runner, "submit"):
                runner.submit(tick_fn, on_error=lambda _exc: None)
            else:
                tick_fn()
        except Exception:
            pass

    def start_guardian_timer_if_needed(self):
        """G1.31 (chunk_3): يُشغّل مؤقّت الحارس عندما لا يُحقن مُشرِف لكن تُحقن نبضة
        بديلة (محوّل الحالة) — حتى تعمل لوحة الوضع/الحالة حتى بلا مُشرِف. محروس،
        idempotent، لا يُنشئ مؤقّتًا ثانيًا إن كان قائمًا.
        """
        try:
            if getattr(self, "_guardian_timer", None) is not None:
                return
            if getattr(self, "_guardian_tick", None) is None:
                return
            self._guardian_timer = QTimer(self)
            self._guardian_timer.setInterval(getattr(self, "_guardian_interval_ms", 1000))
            self._guardian_timer.timeout.connect(self._on_guardian_tick)
            self._guardian_timer.start()
        except Exception:
            self._guardian_timer = None

    def _shutdown_guardian(self):
        """يوقف مؤقّت الحارس بأمان (idempotent). لا يمسّ أي أمر على Binance."""
        try:
            if getattr(self, "_guardian_timer", None) is not None:
                self._guardian_timer.stop()
        except Exception:
            pass

    def _on_alerts_tick(self):
        """Drive one read-only bridge poll. Must NEVER raise into the UI."""
        try:
            if self._alerts_bridge is not None:
                self._alerts_bridge.poll_once()
        except Exception:
            pass

    def _shutdown_alerts(self):
        """Stop the alerts timer + Notifier worker gracefully (idempotent)."""
        try:
            if self._alerts_timer is not None:
                self._alerts_timer.stop()
        except Exception:
            pass
        try:
            if self._alerts_notifier is not None:
                self._alerts_notifier.stop()
        except Exception:
            pass

    def closeEvent(self, event):
        """Tear down the window-level alerts worker + timer before closing."""
        self._shutdown_alerts()
        self._shutdown_guardian()
        try:
            super().closeEvent(event)
        except Exception:
            pass

    def set_audit_path(self, audit_path):
        """G1.25 step_6: allow late injection of the audit path for the bridge.

        The engine wiring may resolve the audit path after the window is built.
        Point the bridge at the new file and (re)anchor its cursor to the end so
        historical events are not replayed. Guarded; never raises.
        """
        self.audit_path = audit_path
        try:
            if self._alerts_bridge is not None and self._alerts_store is not None:
                self._alerts_bridge = AlertsAuditBridge(
                    notifier=self._alerts_notifier,
                    store=self._alerts_store,
                    audit_path=audit_path,
                    start_at_end=True,
                )
        except Exception:
            pass

    def set_price_provider(self, provider):
        # G1.19 fix v2: allow late injection of the live-price provider after
        # connection (مسار فرع «الاتصال» الجديد) so _show_selected can seed the
        # live/reference price for pre-existing (old) OCO orders. Storage only.
        self._price_provider = provider

    def _apply_zoom(self):
        app = QApplication.instance()
        if app is not None:
            self._zoom = set_base_font_scale(app, self._zoom)

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta > 0:
                self._zoom = min(2.5, round(self._zoom + 0.1, 3))
            elif delta < 0:
                self._zoom = max(0.8, round(self._zoom - 0.1, 3))
            self._apply_zoom()
            event.accept()
        else:
            super().wheelEvent(event)

    def keyPressEvent(self, event):
        if (event.modifiers() & Qt.KeyboardModifier.ControlModifier) and event.key() == Qt.Key.Key_0:
            self._zoom = 1.0
            self._apply_zoom()
            event.accept()
        else:
            super().keyPressEvent(event)

    def refresh_connection(self, preflight_fn):
        """Run ``preflight_fn`` off the UI thread; push its result to the pill.

        ``preflight_fn`` is a services-layer callable (it owns any IO). On
        success its returned ConnectionState is handed to the notifier, which
        updates the Topbar connection Pill via the ``changed`` signal.
        """
        self.runner.submit(
            preflight_fn,
            on_result=self.connection_notifier.set_state,
        )

    def _on_nav_select(self, key):
        """Route to the selected screen and update the Topbar title."""
        if self.content.show_screen(key):
            self._sync_title(key)
            # G1.24 P1b: whenever the completed-trades screen becomes visible,
            # re-read the audit file so newly closed trades appear without a
            # restart. Read-only refresh via the domain; no network here.
            if key == "08_completed_trades":
                screen = self.content.screen_for(key)
                if screen is not None and hasattr(screen, "refresh"):
                    screen.refresh()
            # G1.25 step_5: whenever the alerts screen becomes visible, re-read
            # its persisted settings (bot/recipients/enabled) and reflect them.
            # Read-only reload via AlertsStore; no network here.
            if key == "09_alerts":
                screen = self.content.screen_for(key)
                if screen is not None and hasattr(screen, "reload_settings"):
                    screen.reload_settings()

    def _sync_title(self, key):
        """Set the Topbar title to match the given screen key."""
        title = self._title_by_key.get(key, "")
        self.topbar.set_title(title)

    def _on_language_toggle(self):
        i18n.toggle_language()
        app = QApplication.instance()
        i18n.apply_direction(app, self)
        i18n.retranslate_widget_tree(self)
        self.topbar.set_language_label()

    def navigate_to(self, key):
        """Programmatic navigation: mark Sidebar active + switch Content."""
        self.sidebar.set_active(key)
        self._on_nav_select(key)

    def handle_oco_selection(self, order_list_id):
        """Establish the live context for the chosen OCO (off the UI thread).

        ``self._select_fn`` is a services-layer callable (owns any IO). Its
        result (a SelectedOCO) is handed to :meth:`_show_selected`.
        """
        if self._select_fn is None:
            return
        if self.runner:
            self.runner.submit(
                self._select_fn, order_list_id, on_result=self._show_selected
            )
        else:
            self._show_selected(self._select_fn(order_list_id))

    def _show_selected(self, selected):
        """Feed the selected identity into the consumer screens and navigate.

        G1.3: التحديد يؤسّس Live context ويُغذّي الأقسام المستهلِكة كلها
        (Selected/Manual Edit 03، Dynamic Monitoring 04، Dashboard 01) بنفس
        SelectedOCO — عرض فقط (P3: لا مساس بأي orderListId آخر).
        """
        sel = self.content.screen_for("03_selected_and_edit")
        if sel is not None:
            sel.set_selected(selected)
        mon = self.content.screen_for("04_dynamic_monitoring")
        if mon is not None and hasattr(mon, "set_selected"):
            mon.set_selected(selected)
        # G1.19: بذر السعر الحيّ لكلّ اختيار (OCO قديم أو أمر مستقل) على نمط
        # app.py::_select لكن خارج خيط الواجهة عبر الرَنَر. المسار المتجاوِز لـ
        # select_fn (open_orders → _show_selected) لم يكن يستدعي set_symbol/
        # get_price فيبقى reference=None فتظهر «تعذّر البدء — لا سعر حيّ بعد».
        # كل شيء محروس بـ hasattr/getattr + try/except: أي نقص (مزوّد/رمز/setter)
        # = No-Op آمن لا يرمي ولا يُعطّل تغذية الشاشات القائمة.
        try:
            provider = getattr(self, "_price_provider", None)
            runner = getattr(self, "runner", None)
            symbol = getattr(selected, "symbol", None)
            if provider is not None and runner is not None and symbol:
                def _seed_price(_sym=symbol, _p=provider):
                    # يعمل على خيط العامل: شبكة فقط عبر المزوّد المحقون (D14).
                    if hasattr(_p, "set_symbol"):
                        _p.set_symbol(_sym)
                    return _p.get_price() if hasattr(_p, "get_price") else None

                def _on_price(price, _sel=selected, _sel03=sel, _mon=mon):
                    # يعمل على خيط الواجهة: يبذر السعر على الهدف والشاشتين عبر
                    # setters موجودة فقط. محروس حتى لا يرمي أبدًا.
                    try:
                        if price is None:
                            return
                        try:
                            _sel.current_price = price
                        except Exception:
                            pass
                        if _mon is not None and hasattr(_mon, "set_current_price"):
                            _mon.set_current_price(price)
                        if _sel03 is not None and hasattr(_sel03, "set_current_price"):
                            _sel03.set_current_price(price)
                    except Exception:
                        pass

                runner.submit(_seed_price, on_result=_on_price)
        except Exception:
            pass  # لا نُفشل تغذية الشاشات بسبب تعذّر بذر السعر الحيّ (G1.19)
        dash = self.content.screen_for("01_dashboard")
        if dash is not None and hasattr(dash, "update_snapshot"):
            dash.update_snapshot(
                build_dashboard(
                    selected,
                    environment=self._dashboard_environment(),
                    connection=self._dashboard_connection(),
                )
            )
        self.navigate_to("03_selected_and_edit")

    def _handle_execution_result(self, result, selected=None):
        """Populate the Safe Execution screen (05) and navigate to it.

        Called when an activation completes. Defensive: any failure to reach or
        populate the screen is swallowed so it never breaks the caller.
        """
        try:
            screen = self.content.screen_for("05_safe_execution")
            if screen is not None and hasattr(screen, "show_result"):
                screen.show_result(result, selected=selected)
        except Exception:
            pass
        try:
            self.navigate_to("05_safe_execution")
        except Exception:
            pass

    def set_environment(self, env):
        """G1.8: يخزّن البيئة الفعلية (AppConfig.env) ويحدّث شارة التوب-بار."""
        value = getattr(env, "value", env)
        self._environment = str(value).capitalize()
        self.topbar.set_environment(env)

    def _dashboard_environment(self):
        state = self.connection_notifier.state
        env = getattr(state, "environment", None) if state is not None else None
        if env is not None:
            return str(getattr(env, "value", env)).capitalize()
        if getattr(self, "_environment", None):
            return self._environment
        return DASH

    def _dashboard_connection(self):
        state = self.connection_notifier.state
        if state is None:
            return DASH
        try:
            return "متصل" if state.is_connected() else "غير متصل"
        except Exception:
            return DASH
