"""OCOBot Content region + router (T10b, step s3).

A ``QStackedWidget`` holding one EMPTY placeholder screen per nav entry, in
mockup order. ``show_screen(key)`` switches the visible screen; the router
maps screen keys to stack indices. No business logic and no real content —
the actual screen content is T11–T13 (out of scope here).

Uses the ``_qt`` shim and Palette D15 tokens from ``theme``.
"""

from ._qt import (
    Qt,
    QWidget,
    QLabel,
    QVBoxLayout,
    QStackedWidget,
)
from .theme import PALETTE
from .screens import SCREENS
from .dashboard import DashboardScreen
from .open_orders import OpenOrdersScreen
from .selected_oco import SelectedOcoScreen
from .monitoring import DynamicMonitoringScreen
from .safe_execution import SafeExecutionScreen
from .demo_mode import DemoModeScreen
from .connection_screen import ConnectionScreen
from .completed_trades import CompletedTradesScreen
from .alerts import AlertsScreen


class PlaceholderScreen(QWidget):
    """An empty structural screen (title only) — no content, no logic."""

    def __init__(self, key, title, parent=None):
        super().__init__(parent)
        self.setObjectName("Screen_%s" % key)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.screen_key = key

        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 26, 26, 26)
        self.heading = QLabel(title, self)
        self.heading.setObjectName("ScreenHeading")
        layout.addWidget(self.heading)
        layout.addStretch(1)


class ContentRouter(QStackedWidget):
    """Stacked Content region that routes between placeholder screens."""

    def __init__(self, parent=None, runner=None, executor=None, execute_cb=None,
                 engine=None, price_provider=None, on_execution_result=None,
                 convert_cb=None, audit_path=None):
        super().__init__(parent)
        self._runner = runner
        self._executor = executor
        self._execute_cb = execute_cb
        self._engine = engine
        self._price_provider = price_provider
        self._on_execution_result = on_execution_result
        # G1.13 (إضافي): callback التحويل إلى OCO — يُمرَّر لشاشة 02 بلا شبكة هنا.
        self._convert_cb = convert_cb
        # G1.24 P1: audit log path forwarded into CompletedTradesScreen so it
        # reads from the SAME sink the monitoring wiring writes. Default None →
        # the screen falls back to OCOBOT_AUDIT_LOG / cwd (backward compatible).
        self._audit_path = audit_path
        self.setObjectName("ContentRouter")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setStyleSheet(
            "#ContentRouter { background-color: %s; }" % PALETTE["BG"]
        )

        self._index_by_key = {}
        self._screens = {}
        self._keys_in_order = []

        for screen in SCREENS:
            key = screen["key"]
            if key == "01_dashboard":
                page = DashboardScreen(self)
            elif key == "02_open_orders":
                # CHUNK 1: شاشة 02 عرض+اختيار فقط — لم تعد تستقبل convert_cb.
                page = OpenOrdersScreen(self)
            elif key == "03_selected_and_edit":
                on_execution_result = self._on_execution_result
                page = SelectedOcoScreen(self, runner=runner, executor=executor, execute_cb=execute_cb, on_execution_result=on_execution_result)
            elif key == "04_dynamic_monitoring":
                # G1.13 (CHUNK 1): يُمرَّر convert_cb لشاشة المراقبة (04) هنا (تخزين فقط).
                # G1.46.1: مرّر audit_path نفسه (مِصرف التدقيق) حتى تعبّئ شاشة المراقبة
                # بطاقة نتيجة الصفقة تلقائيًّا من نفس مصدر شاشة الصفقات المنتهية.
                page = DynamicMonitoringScreen(self, engine=engine, price_provider=price_provider, runner=runner, convert_cb=self._convert_cb, audit_path=self._audit_path)
            elif key == "05_safe_execution":
                page = SafeExecutionScreen(self)
            elif key == "06_demo":
                page = DemoModeScreen(self)
            elif key == "07_connection":
                page = ConnectionScreen(self, runner=runner)
            elif key == "08_completed_trades":
                # G1.14: شاشة الصفقات المنتهية — قراءة فقط عبر الـ domain
                # (load_completed_trades + DismissStore)؛ لا خدمات شبكة.
                # G1.24 P1: مرّر audit_path حتى تقرأ الشاشة من نفس مِصرف التدقيق.
                page = CompletedTradesScreen(self, runner=runner, audit_path=audit_path)
            elif key == "09_alerts":
                # G1.25 step_5: قسم تنبيهات Telegram — كلّ الشبكة عبر runner
                # (لا شبكة متزامنة على خيط الواجهة). AlertsStore بمسارات افتراضية.
                page = AlertsScreen(self, runner=runner)
            else:
                page = PlaceholderScreen(key, screen["title"], self)
            index = self.addWidget(page)
            self._index_by_key[key] = index
            self._screens[key] = page
            self._keys_in_order.append(key)

        # Default to the first screen.
        if self._keys_in_order:
            self.setCurrentIndex(self._index_by_key[self._keys_in_order[0]])

    def show_screen(self, key):
        """Switch the visible Content screen to ``key``. Returns True on success."""
        index = self._index_by_key.get(key)
        if index is None:
            return False
        self.setCurrentIndex(index)
        return True

    def current_key(self):
        """Screen key of the currently visible Content screen."""
        widget = self.currentWidget()
        return getattr(widget, "screen_key", None)

    def screen_for(self, key):
        """Return the placeholder screen widget for a key (used by tests)."""
        return self._screens.get(key)

    def keys(self):
        """Screen keys in router (mockup) order."""
        return list(self._keys_in_order)
