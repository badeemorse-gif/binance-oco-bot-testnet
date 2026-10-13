"""Live connection state notifier (T10c).

``ConnectionStateNotifier`` is a tiny ``QObject`` that stores the latest
``ConnectionState`` and emits ``changed`` whenever it is updated, so a UI
element (the Topbar connection pill) can react via a Qt signal. It performs
NO network itself — state is produced by the services/preflight layer and
pushed in via ``set_state``.
"""

from ._qt import QObject, Signal


class ConnectionStateNotifier(QObject):
    """Holds the current connection state and signals changes to the UI."""

    changed = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = None

    @property
    def state(self):
        """The most recently set connection state (or ``None``)."""
        return self._state

    def set_state(self, state):
        """Store ``state`` and emit ``changed`` for connected UI slots."""
        self._state = state
        self.changed.emit(state)
