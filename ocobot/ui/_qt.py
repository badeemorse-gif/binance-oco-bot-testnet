"""Qt compatibility shim.

Prefers PySide6, falls back to PyQt6. Re-exports the small set of Qt
symbols used by the OCOBot UI so the rest of the code stays binding-agnostic.

``QT_BINDING`` names the active binding ("PySide6" or "PyQt6").
"""

try:  # pragma: no cover - branch depends on installed binding
    from PySide6.QtWidgets import (
        QApplication,
        QMainWindow,
        QWidget,
        QLabel,
        QVBoxLayout,
        QHBoxLayout,
        QGridLayout,
        QStackedWidget,
        QFrame,
        QSizePolicy,
        QButtonGroup,
        QPushButton,
        QTableWidget,
        QTableWidgetItem,
        QHeaderView,
        QAbstractItemView,
        QCheckBox,
        QComboBox,
        QLineEdit,
        QMessageBox,
        QScrollArea,
        QFileDialog,
        QListWidget,
        QListWidgetItem,
    )
    from PySide6.QtCore import (
        Qt,
        Signal,
        Slot,
        QObject,
        QCoreApplication,
        QThread,
        QThreadPool,
        QRunnable,
        QTimer,
        QEventLoop,
    )
    from PySide6.QtGui import QFont, QPalette, QColor, QGuiApplication

    QT_BINDING = "PySide6"
except ImportError:  # pragma: no cover - exercised only without PySide6
    from PyQt6.QtWidgets import (
        QApplication,
        QMainWindow,
        QWidget,
        QLabel,
        QVBoxLayout,
        QHBoxLayout,
        QGridLayout,
        QStackedWidget,
        QFrame,
        QSizePolicy,
        QButtonGroup,
        QPushButton,
        QTableWidget,
        QTableWidgetItem,
        QHeaderView,
        QAbstractItemView,
        QCheckBox,
        QComboBox,
        QLineEdit,
        QMessageBox,
        QScrollArea,
        QFileDialog,
    )
    from PyQt6.QtCore import (
        Qt,
        QObject,
        QCoreApplication,
        QThread,
        QThreadPool,
        QRunnable,
        QTimer,
        QEventLoop,
        pyqtSignal as Signal,
        pyqtSlot as Slot,
    )
    from PyQt6.QtWidgets import QListWidget, QListWidgetItem
    from PyQt6.QtGui import QFont, QPalette, QColor, QGuiApplication

    QT_BINDING = "PyQt6"

__all__ = [
    "QApplication",
    "QMainWindow",
    "QWidget",
    "QLabel",
    "QVBoxLayout",
    "QHBoxLayout",
    "QGridLayout",
    "QStackedWidget",
    "QFrame",
    "QSizePolicy",
    "QButtonGroup",
    "QPushButton",
    "QTableWidget",
    "QTableWidgetItem",
    "QHeaderView",
    "QAbstractItemView",
    "QCheckBox",
    "QComboBox",
    "QLineEdit",
    "QMessageBox",
    "Qt",
    "QFont",
    "QPalette",
    "QColor",
    "QScrollArea",
    "QFileDialog",
    "QListWidget",
    "QListWidgetItem",
    "QGuiApplication",
    "Signal",
    "Slot",
    "QObject",
    "QCoreApplication",
    "QThread",
    "QThreadPool",
    "QRunnable",
    "QTimer",
    "QEventLoop",
    "QT_BINDING",
]
