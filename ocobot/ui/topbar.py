"""OCOBot Topbar — title + two Pills (T10b shell, T10c live connection).

Matches docs/ui_mockups: a screen title on the leading edge and, on the
trailing edge, two Pills — Environment and Connection. The Connection Pill
starts with an initial value and is driven live under T10c via
``set_connection_state`` below. The Topbar itself makes no network calls.

Uses the ``_qt`` shim and Palette D15 tokens from ``theme``.
"""

from ._qt import (
    Qt,
    QWidget,
    QLabel,
    QHBoxLayout,
    QSizePolicy,
    QPushButton,
    Signal,
)
from .theme import PALETTE
from ocobot.core.connection_state import ConnectionStatus
from . import i18n


# Maps a ConnectionStatus to the (Arabic label, Palette accent key) shown on
# the live connection Pill. Palette keys resolve against ``theme.PALETTE``.
_CONNECTION_DISPLAY = {
    ConnectionStatus.CONNECTED: ("متصل", "GREEN"),
    ConnectionStatus.CONNECTING: ("جارٍ الاتصال", "AMBER"),
    ConnectionStatus.ERROR: ("خطأ اتصال", "RED"),
    ConnectionStatus.DISCONNECTED: ("غير متصل", "MUTED"),
}


class Pill(QLabel):
    """A rounded status chip. ``set_accent`` restyles it for live updates."""

    def __init__(self, text, accent, parent=None):
        super().__init__(text, parent)
        self.setObjectName("Pill")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self._apply_style(accent)

    def _apply_style(self, accent):
        self.setStyleSheet(
            "#Pill { border: 1px solid %s; border-radius: 12px; "
            "padding: 6px 13px; color: %s; }" % (PALETTE["BORDER"], accent)
        )

    def set_accent(self, text, accent):
        """Update the Pill text and accent color (live restyle)."""
        self.setText(text)
        self._apply_style(accent)


class Topbar(QWidget):
    """Header strip: leading title + trailing Environment/Connection Pills."""

    # G1.12: emitted when the compact disconnect button is clicked. Wired by
    # the app to a single isolated disconnect handler (no network here).
    disconnect_requested = Signal()

    # G1.20: emitted when the language-toggle button is clicked. Wired by the
    # app to toggle the UI language and refresh translated widgets.
    language_toggle_requested = Signal()

    def __init__(self, title="", parent=None):
        super().__init__(parent)
        self.setObjectName("Topbar")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setStyleSheet(
            "#Topbar { border-bottom: 1px solid %s; }" % PALETTE["BORDER"]
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(26, 16, 26, 16)
        layout.setSpacing(10)

        self.title_label = QLabel(title, self)
        self.title_label.setObjectName("TopbarTitle")
        layout.addWidget(self.title_label)

        layout.addStretch(1)

        # Initial Pills; the Connection Pill starts disconnected and is
        # updated live via ``set_connection_state`` / ``refresh_connection``.
        self.env_pill = Pill("Testnet", PALETTE["AMBER"], self)
        self.env_pill.setObjectName("EnvironmentPill")
        self.conn_pill = Pill("غير متصل", PALETTE["MUTED"], self)
        self.conn_pill.setObjectName("ConnectionPill")

        layout.addWidget(self.env_pill)
        layout.addWidget(self.conn_pill)

        # G1.20: compact language-toggle button. Its visible label comes from
        # ``i18n.toggle_label()`` (the literal lives in i18n, not here). Emits
        # ``language_toggle_requested``; the app toggles the language.
        self._lang_btn = QPushButton(i18n.toggle_label(), self)
        self._lang_btn.setObjectName("languageToggle")
        self._lang_btn.clicked.connect(self.language_toggle_requested.emit)
        layout.addWidget(self._lang_btn)

        # G1.12: compact isolated disconnect button next to the connection
        # pill. Emits ``disconnect_requested``; the app routes it through a
        # single disconnect handler (state toggle only, no network).
        self._disconnect_btn = QPushButton("قطع الاتصال", self)
        self._disconnect_btn.setObjectName("TopbarDisconnect")
        self._disconnect_btn.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        self._disconnect_btn.setStyleSheet(
            "QPushButton#TopbarDisconnect { color: %s; background: transparent; "
            "border: 1px solid %s; border-radius: 12px; padding: 5px 11px; }"
            % (PALETTE["RED"], PALETTE["BORDER"])
        )
        self._disconnect_btn.clicked.connect(self.disconnect_requested.emit)
        layout.addWidget(self._disconnect_btn)

    def set_language_label(self):
        """Refresh the language-toggle button label from ``i18n``."""
        self._lang_btn.setText(i18n.toggle_label())

    def set_title(self, title):
        """Update the displayed screen title."""
        self.title_label.setText(i18n.translate_for_current(title))

    def set_connection_state(self, state):
        """Reflect a ConnectionState (has ``.status``) or ConnectionStatus.

        Maps the status to the live Pill label + Palette accent. No network.
        """
        status = getattr(state, "status", state)
        label, accent_key = _CONNECTION_DISPLAY.get(
            status, _CONNECTION_DISPLAY[ConnectionStatus.DISCONNECTED]
        )
        # G1.12: a user-initiated disconnect is marked with detail
        # "USER_DISCONNECT" so it renders RED while a plain (idle) DISCONNECTED
        # stays MUTED. Non-breaking: no existing DISCONNECTED entry changes.
        if status == ConnectionStatus.DISCONNECTED and getattr(state, "detail", None) == "USER_DISCONNECT":
            accent_key = "RED"
        self.conn_pill.set_accent(i18n.translate_for_current(label), PALETTE[accent_key])

    def set_environment(self, env):
        """يحدّث شارة البيئة من المصدر الفعلي (AppConfig.env). Testnet-only أثناء G1."""
        value = getattr(env, "value", env)      # يقبل Environment enum أو نصًّا
        label = str(value).capitalize()         # 'testnet' -> 'Testnet'
        self.env_pill.set_accent(label, PALETTE["AMBER"])
