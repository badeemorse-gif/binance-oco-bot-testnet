"""OCOBot Sidebar — right-side (RTL) navigation (T10b, step s1).

A vertical navigation rail matching docs/ui_mockups: a brand block
("OCOBot" + "إدارة أوامر OCO") followed by one checkable nav button per
screen, in mockup order and wording. The Sidebar owns no business logic;
it only emits which screen key was selected so the router can switch the
visible Content.

Uses the ``_qt`` shim and Palette D15 tokens from ``theme``.
"""

from ._qt import (
    Qt,
    QWidget,
    QLabel,
    QVBoxLayout,
    QPushButton,
    QButtonGroup,
    QSizePolicy,
)
from .theme import PALETTE
from .screens import SCREENS


class Sidebar(QWidget):
    """Right-side RTL navigation rail with one checkable entry per screen."""

    def __init__(self, on_select=None, parent=None):
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self._on_select = on_select
        # Fixed-width rail (mockup: 250px column), full height.
        self.setFixedWidth(250)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.setStyleSheet(
            "#Sidebar { background-color: %s; "
            "border-inline-start: 1px solid %s; }"
            % (PALETTE["SIDEBAR"], PALETTE["BORDER"])
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 22, 16, 22)
        layout.setSpacing(5)

        # Brand block.
        self.brand_name = QLabel("OCOBot", self)
        self.brand_name.setObjectName("SidebarBrandName")
        self.brand_sub = QLabel("إدارة أوامر OCO", self)
        self.brand_sub.setObjectName("SidebarBrandSub")
        self.brand_sub.setStyleSheet("color: %s;" % PALETTE["MUTED"])
        layout.addWidget(self.brand_name)
        layout.addWidget(self.brand_sub)

        # Nav buttons — one per screen, exclusive selection.
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons = {}
        self._keys_in_order = []

        for index, screen in enumerate(SCREENS):
            key = screen["key"]
            button = QPushButton(
                "%s  %s" % (screen["icon"], screen["nav_label"]), self
            )
            button.setObjectName("SidebarNavButton")
            button.setCheckable(True)
            button.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
            button.setProperty("screen_key", key)
            button.clicked.connect(
                lambda _checked=False, k=key: self._handle_click(k)
            )
            self._group.addButton(button, index)
            self._buttons[key] = button
            self._keys_in_order.append(key)
            layout.addWidget(button)

        layout.addStretch(1)

        # Default selection: first screen.
        if self._keys_in_order:
            self._buttons[self._keys_in_order[0]].setChecked(True)

    def _handle_click(self, key):
        """Mark the entry checked and notify the router callback."""
        button = self._buttons.get(key)
        if button is not None:
            button.setChecked(True)
        if self._on_select is not None:
            self._on_select(key)

    def button_for(self, key):
        """Return the nav button for a screen key (used by tests)."""
        return self._buttons.get(key)

    def keys(self):
        """Screen keys in sidebar (mockup) order."""
        return list(self._keys_in_order)

    def set_active(self, key):
        """Programmatically mark an entry active without emitting selection."""
        button = self._buttons.get(key)
        if button is not None:
            button.setChecked(True)
